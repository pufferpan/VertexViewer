"""资产索引的存储层：SQLite（单文件、原子替换）。

以前索引是 `fileindex.json(.gz)` / `index.tsv.gz` 两个纯文件，散落在
`data/`、exe 目录、`%LOCALAPPDATA%` 里，用户经常遇到「找不到文件」和
「重建完文件又不见了」。现在统一存成**一个** SQLite 数据库：

    %LOCALAPPDATA%\\VertexViewer\\index.db

- 位置固定在用户目录，永远不跟着 `data/` 或 exe 移动，也不会被清缓存误删；
- 写入是「临时库 + `os.replace`」的原子替换，中途断电也不会留下半个文件；
- 启动时先查库（含 `meta` 表的条数、生成时间），没有再退回旧格式或现场重建。

对外只有三个函数：`db_path()`、`load_all()`、`build(progress_cb=None)`。
读旧格式（`index.tsv.gz` / `fileindex.json.gz`）的「导入」逻辑也在 build 里。
"""
from __future__ import annotations

import io
import os
import sqlite3
import sys
import time

DB_NAME = "index.db"
_APP = "VertexViewer"


def _localapp() -> str:
    return (os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"))


def db_path() -> str:
    """索引数据库位置（固定，不随 exe/data 变化）。"""
    override = os.environ.get("VERTEXVIEWER_INDEX_DB")
    if override:
        return override
    return os.path.join(_localapp(), _APP, DB_NAME)


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=20)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def is_ready() -> bool:
    """库存在、表结构在、条数 > 0。"""
    path = db_path()
    if not os.path.isfile(path) or os.path.getsize(path) < 4096:
        return False
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key='count'").fetchone()
            return bool(row) and int(row[0]) > 0
    except Exception:                                            # noqa: BLE001
        return False


def count() -> int:
    try:
        with sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True, timeout=5) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key='count'").fetchone()
            return int(row[0]) if row else 0
    except Exception:                                            # noqa: BLE001
        return 0


def load_all() -> dict:
    """把整库读成 `{vpath: [pak, loc]}`（和旧接口兼容）。"""
    out = {}
    path = db_path()
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30) as conn:
        paks = dict(conn.execute("SELECT id, name FROM paks"))
        for vpath, pid, loc in conn.execute("SELECT vpath, pak, loc FROM assets"):
            out[vpath] = [paks.get(pid, ""), loc]
    return out


def _write(rows, out_path: str, source: str, models=None) -> int:
    """把 (vpath, pak, loc) 三元组写进临时库，最后原子替换。"""
    tmp = out_path + ".tmp"
    for stale in (tmp, tmp + "-journal", tmp + "-wal"):
        try:
            os.remove(stale)
        except OSError:
            pass
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    conn = _connect(tmp)
    n = 0
    try:
        # pak 名只有几百个，单独一张表存 id：比每行重复 40 字节省一半体积
        conn.execute("CREATE TABLE paks (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        conn.execute("CREATE TABLE assets (vpath TEXT PRIMARY KEY, "
                     "pak INTEGER NOT NULL, loc INTEGER NOT NULL) WITHOUT ROWID")
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        # 改枪用的「模型目录」：游戏内中文名 / 槽位 / 枪族码，全部在建索引时算好，
        # 之后弹窗直接查库，不用再去翻 90 万个路径、也不用为了看名字解包资产。
        conn.execute("CREATE TABLE models (vpath TEXT PRIMARY KEY, cn TEXT, "
                     "slot TEXT, gun TEXT, kind TEXT) WITHOUT ROWID")
        pak_ids = {}
        batch = []
        for vpath, pak_name, loc in rows:
            pid = pak_ids.get(pak_name)
            if pid is None:
                pid = len(pak_ids) + 1
                pak_ids[pak_name] = pid
                conn.execute("INSERT INTO paks VALUES (?,?)", (pid, pak_name))
            batch.append((vpath, pid, loc))
            if len(batch) >= 20000:
                conn.executemany("INSERT OR REPLACE INTO assets VALUES (?,?,?)", batch)
                n += len(batch)
                batch.clear()
        if batch:
            conn.executemany("INSERT OR REPLACE INTO assets VALUES (?,?,?)", batch)
            n += len(batch)
        if models:
            mrows = list(models)
            for i in range(0, len(mrows), 20000):
                conn.executemany(
                    "INSERT OR REPLACE INTO models VALUES (?,?,?,?,?)", mrows[i:i+20000])
            conn.execute("INSERT INTO meta VALUES ('models', ?)", (str(len(mrows)),))
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('models_rev', ?)", (MODELS_REV,))
        conn.executemany("INSERT INTO meta VALUES (?,?)",
                         [("count", str(n)),
                          ("source", source),
                          ("created", time.strftime("%Y-%m-%d %H:%M:%S")),
                          ("version", "3")])
        conn.commit()
    finally:
        conn.close()
    os.replace(tmp, out_path)
    return n


def build(progress_cb=None) -> int:
    """从游戏 pak 重建索引，落盘成单一 `index.db`。

    进度回调按 `(done_paks, total_paks)` 调用；返回写入条数。
    """
    from core import loader as L                  # 延迟导入，避免循环

    pairs = L.rebuild_index_from_paks()                  # {vpath: [pak, loc]}
    if callable(progress_cb):
        progress_cb(1, 1, "写入数据库…")
    if not pairs:
        return 0

    def _rows():
        for vpath, value in pairs.items():
            try:
                pak, loc = value
            except Exception:                                # noqa: BLE001
                continue
            yield (vpath, str(pak), int(loc))

    try:
        from core import gunsmith as G
        models = list(G.catalog_rows(pairs.keys()))
    except Exception:                                            # noqa: BLE001
        models = None
    n = _write(_rows(), db_path(), source="paks", models=models)
    print(f"[indexdb] built {n} 条 -> {db_path()}", file=sys.stderr)
    return n


def import_from(path: str, kind: str) -> int:
    """把旧格式导入成数据库（保留兼容，不用再依赖那些文件）。"""
    from core import loader as L

    if kind == "tsv":
        pairs = L._load_index_tsv(path)
    else:
        pairs = L._load_index_json(path, gz=(kind == "json.gz"))

    def _rows():
        for vpath, value in pairs.items():
            try:
                pak, loc = value
            except Exception:                                # noqa: BLE001
                continue
            yield (vpath, str(pak), int(loc))

    try:
        from core import gunsmith as G
        models = list(G.catalog_rows(pairs.keys()))
    except Exception:                                            # noqa: BLE001
        models = None
    n = _write(_rows(), db_path(), source=f"import:{os.path.basename(path)}",
               models=models)
    print(f"[indexdb] imported {n} 条 from {path}", file=sys.stderr)
    return n


def drop() -> None:
    """清掉数据库（恢复出厂设置用）。"""
    for path in (db_path(), db_path() + ".tmp"):
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 模型目录（改枪用）
# --------------------------------------------------------------------------- #
def _ro(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)


def has_models() -> bool:
    try:
        with _ro(db_path()) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='models'"
            ).fetchone()
            if not row:
                return False
            cnt = conn.execute("SELECT COUNT(*) FROM models").fetchone()
            return bool(cnt) and int(cnt[0]) > 0
    except Exception:                                            # noqa: BLE001
        return False


def load_models() -> list:
    """[(vpath, cn, slot, gun, kind), …]"""
    try:
        with _ro(db_path()) as conn:
            return list(conn.execute(
                "SELECT vpath, cn, slot, gun, kind FROM models"))
    except Exception:                                            # noqa: BLE001
        return []


MODELS_REV = "3"      # Include native Dev/Att tactical equipment and non-3P meshes.


def models_rev() -> str:
    path = db_path()
    if not os.path.isfile(path):
        return ""
    try:
        with sqlite3.connect(path, timeout=10) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key='models_rev'").fetchone()
        return row[0] if row else ""
    except Exception:                                        # noqa: BLE001
        return ""


def models_look_stale() -> bool:
    """目录里混进了贴图/UI 资产（老版本建的表）就认为要重刷。"""
    path = db_path()
    if not os.path.isfile(path):
        return False
    try:
        with sqlite3.connect(path, timeout=10) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM models WHERE "
                "lower(vpath) NOT LIKE '%.uasset'"
            ).fetchone()
        return bool(row and row[0])
    except Exception:                                        # noqa: BLE001
        return False


def refresh_models(max_seconds: float = 60.0) -> int:
    """重刷 models 目录（过滤规则变了以后用一次）。"""
    path = db_path()
    if not os.path.isfile(path):
        return 0
    try:
        with sqlite3.connect(path, timeout=20) as conn:
            conn.execute("DELETE FROM models")
            conn.commit()
    except Exception:                                        # noqa: BLE001
        return 0
    return ensure_models(max_seconds=max_seconds, force=True)


def ensure_models(max_seconds: float = 20.0, force: bool = False) -> int:
    """老库没有 models 表时，现场补一份（只扫武器相关路径，约 1~3 秒）。"""
    import time as _t
    path = db_path()
    if not os.path.isfile(path):
        return 0
    if has_models() and not force:
        return 0
    from core import loader as L
    from core import gunsmith as G
    t0 = _t.time()
    try:
        with sqlite3.connect(path, timeout=20) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS models (vpath TEXT PRIMARY KEY, "
                         "cn TEXT, slot TEXT, gun TEXT, kind TEXT) WITHOUT ROWID")
            batch = []
            n = 0
            for row in G.catalog_rows(L.index().keys()):
                batch.append(row)
                if len(batch) >= 20000:
                    conn.executemany("INSERT OR REPLACE INTO models VALUES (?,?,?,?,?)", batch)
                    n += len(batch)
                    batch.clear()
                if _t.time() - t0 > max_seconds:
                    break
            if batch:
                conn.executemany("INSERT OR REPLACE INTO models VALUES (?,?,?,?,?)", batch)
                n += len(batch)
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('models', ?)", (str(n),))
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('models_rev', ?)", (MODELS_REV,))
            conn.commit()
        print(f"[indexdb] models catalog {n} 条", file=sys.stderr)
        return n
    except Exception as exc:                                     # noqa: BLE001
        print(f"[indexdb] models catalog failed: {exc}", file=sys.stderr)
        return 0
