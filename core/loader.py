"""High level facade: virtual pak path -> `core.types.ModelBundle`.

Only this module knows how the pak layer, the uasset parser, the texture
decoder, the material parser and the Chinese-name table fit together; the UI
and the renderer talk to `load_model()` and nothing else.

Everything here is defensive: any stage that is still missing / not yet able to
parse an asset degrades to a smaller bundle instead of raising, because half a
model in the viewport beats a traceback in a Qt slot.
"""
from __future__ import annotations

import glob
import gzip
import io
import json
import os
import re
import shutil
import sys
import threading
from copy import deepcopy
from functools import lru_cache
from typing import Dict, List, Optional

from .types import Material, Mesh, ModelBundle, Texture

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


# 启动加载进度：给加载界面读的「真进度」，不是假动画。
#   stage   当前阶段（中文，直接显示给用户）
#   done    已完成单位数（压缩字节 / 已装载条目）
#   total   总单位数；0 表示这个阶段没法量化（此时 UI 显示不定进度条）
#   detail  细节文本（"3.1/8.5 MB"、"812000/937088 个资产"）
PROGRESS: Dict[str, object] = {"stage": "", "done": 0, "total": 0, "detail": ""}
_PROGRESS_LOCK = threading.Lock()


def _set_progress(stage: Optional[str] = None, done: Optional[int] = None,
                  total: Optional[int] = None, detail: Optional[str] = None) -> None:
    with _PROGRESS_LOCK:
        if stage is not None:
            PROGRESS["stage"] = stage
        if done is not None:
            PROGRESS["done"] = int(done)
        if total is not None:
            PROGRESS["total"] = int(total)
        if detail is not None:
            PROGRESS["detail"] = detail


def progress() -> Dict[str, object]:
    """加载界面用的进度快照（线程安全）。"""
    with _PROGRESS_LOCK:
        return dict(PROGRESS)


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _bundle_dir() -> str:
    """打包后资源所在目录（PyInstaller 解包目录 / 源码仓库根目录）。"""
    if _frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return ROOT


INDEX_NAMES = ("index.tsv.gz", "fileindex.json.gz", "fileindex.json")


def _has_index(d: str) -> bool:
    return any(os.path.exists(os.path.join(d, n)) for n in INDEX_NAMES)


def _find_index_dir(root: str, max_depth: int = 3):
    """在 root 下有限深度地找放索引的目录。

    兼容网友自己解压时多套一层（VertexViewer/VertexViewer/data）或者把 data 改名的情况。
    """
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return None
    base_depth = root.rstrip(os.sep).count(os.sep)
    for cur, dirs, _files in os.walk(root):
        depth = cur.rstrip(os.sep).count(os.sep) - base_depth
        if depth > max_depth:
            dirs[:] = []
            continue
        if _has_index(cur):
            return cur
        dirs[:] = [d for d in dirs if d.lower() not in
                   ("cache", "logs", "uemodel", "icons", "__pycache__")]
    return None


def _work_dir() -> str:
    r"""工作目录（放自定义图标表、可选覆盖用的 names.json 等）。

    顺序：VERTEXVIEWER_WORK > **当前安装目录**/data > 安装目录自己 > 打包资源 > 安装目录/work。

    这里**不再按「哪个目录里有索引文件」挑目录**：索引已经搬到
    ``%LOCALAPPDATA%\VertexViewer\index.db``，跟安装目录无关了；以前的
    `_has_index()` 嗅探会让别人机器上残留的 ``data/fileindex.json.gz``
    （旧版本留下的）把 WORK 抢走，诊断报告里 WORK 指向一个奇怪的目录就是这个原因。

    也绝不回落到开发机绝对路径：以前那个回落就是
    ``FileNotFoundError: 'G:\\xmcl-fetch\\work\\fileindex.json'`` 的来源。
    """
    env = os.environ.get("VERTEXVIEWER_WORK")
    if env and os.path.isdir(env):
        return env
    exe_dir = os.path.dirname(os.path.abspath(
        sys.executable if _frozen() else __file__))
    bundle = _bundle_dir()
    cands = [
        os.path.join(exe_dir, "data"),
        exe_dir,
        os.path.join(bundle, "data"),
        os.path.join(bundle, "work"),
        bundle,
        os.path.join(exe_dir, "work"),
    ]
    if not _frozen():
        cands.insert(0, os.path.abspath(os.path.join(ROOT, "work")))
        cands.insert(1, os.path.abspath(os.path.join(ROOT, "..", "work")))
    for c in cands:
        if os.path.isdir(c):
            return c
    return cands[0]


def _version_stamp() -> str:
    try:
        from .version import stamp
        return stamp()
    except Exception:                                            # noqa: BLE001
        return "?"


def search_report() -> str:
    """把「到底去哪些地方找过索引」写成一段人能看懂的诊断文本。"""
    localapp = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    exe_dir = os.path.dirname(os.path.abspath(
        sys.executable if _frozen() else __file__))
    lines = [f"版本：{_version_stamp()}",
             f"是否打包运行：{_frozen()}",
             f"exe 目录：{exe_dir}",
             f"数据目录 WORK：{WORK}",
             f"索引文件：{_located_index() or '（没找到）'}"]
    for d in (os.path.join(exe_dir, "data"), WORK):
        try:
            names = sorted(os.listdir(d)) if os.path.isdir(d) else []
        except Exception:                                        # noqa: BLE001
            names = []
        if names:
            lines.append(f"{d} 里有：{', '.join(names[:12])}")
        else:
            lines.append(f"{d} 不存在或是空的")
    return "\n".join(lines)


BUNDLE = _bundle_dir()
WORK = _work_dir()

# 游戏根目录：VERTEXVIEWER_GAME > %LOCALAPPDATA%\VertexViewer\config.json > 常见安装位置
_CONFIG = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                       "VertexViewer", "config.json")
_DEFAULT_GAMES = [
    r"G:\Game\Game",
    r"D:\Game\Game",
    r"E:\Game\Game",
    r"C:\Game\Game",
    r"D:\Program Files\Game\Game",
]


def _read_config() -> dict:
    try:
        with open(_CONFIG, "r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:                                            # noqa: BLE001
        return {}


def _write_config(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_CONFIG), exist_ok=True)
        with open(_CONFIG, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception as exc:                                     # noqa: BLE001
        print(f"[loader] config write failed: {exc}", file=sys.stderr)


def _pak_files(paks: str) -> list:
    try:
        return [e for e in os.scandir(paks)
                if e.is_file() and e.name.lower().endswith(".pak")]
    except OSError:
        return []


def _pak_score(paks: str) -> tuple:
    """(pak 个数, pak 总字节)。个数优先：装了全量包的机器一定比残包多。"""
    files = _pak_files(paks)
    total = 0
    for e in files:
        try:
            total += e.stat().st_size
        except OSError:
            pass
    return (len(files), total)


_LEGACY_CONFIGS = [
    os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                 "DFViewer", "config.json"),
    os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                 "DFMapViewer", "config.json"),
]


def _candidate_roots() -> list:
    """所有可能是游戏安装根的分支：环境变量、配置、旧版配置、默认路径、盘符扫出来的。"""
    env = os.environ.get("VERTEXVIEWER_GAME")
    cfg = _read_config()
    cands: list = []

    def _add(path) -> None:
        if not path:
            return
        try:
            path = os.path.abspath(path)
        except (OSError, ValueError):
            return
        if path not in cands:
            cands.append(path)

    _add(env)
    _add(cfg.get("game_root"))
    # 旧版（改名前）配置里记着的安装根：用户从旧版升级上来时，那才是全量安装
    for legacy in _LEGACY_CONFIGS:
        try:
            with open(legacy, encoding="utf-8") as fh:
                _add(json.load(fh).get("game_root"))
        except Exception:                                          # noqa: BLE001
            pass
    for cached in (cfg.get("known_roots") or []):
        _add(cached)
    for root in _DEFAULT_GAMES:
        _add(root)
    for drive in "CDEFGHIJ":
        base = drive + ":\\"
        if not os.path.isdir(base):
            continue
        for name in ("Game", "DeltaForce", "Games\\Game",
                     "Steam\\steamapps\\common\\Game"):
            root = os.path.join(base, name)
            _add(root)
            _add(os.path.join(root, "Game"))
        for found in _scan_drive_for_game(base):
            _add(found)
    return cands


def find_game_root() -> Optional[str]:
    """返回安装根（其下某一层有 Content\\Paks）。

    以前是「第一个命中就返回」，结果配置里记着一个只装了 9 个 pak 的残包时，
    隔壁 61G 的全量安装永远轮不到，模型库里就只剩一小撮资产。
    现在把候选都称一遍挑 pak 最多的；候选都像残包时再深度扫第三层，
    并在配置里的目录明显更少时自动改配置。
    """
    cfg = _read_config()
    saved = cfg.get("game_root")
    best, best_root = (0, 0), None
    saved_score = (0, 0)
    for root in _candidate_roots():
        paks = _paks_under(root)
        if not paks:
            continue
        score = _pak_score(paks)
        if saved and os.path.abspath(saved) == root:
            saved_score = score
        if score > best:
            best, best_root = score, root
    if not best_root or best[0] < 20:
        # 只找到残包：完整版常常装在 `盘:\\WeGameApps\\rail_apps\\<游戏>`（三层），
        # 两层扫描看不到。这时才付一次深度扫描的代价，结果缓存进配置的 known_roots。
        deep: list = []
        for drive in "CDEFGHIJ":
            base = drive + ":\\"
            if os.path.isdir(base):
                deep.extend(_deep_scan_for_game(base))
        for root in deep:
            paks = _paks_under(root)
            if not paks:
                continue
            score = _pak_score(paks)
            if score > best:
                best, best_root = score, root
        if deep:
            try:
                cfg["known_roots"] = sorted(set(deep))
                _write_config(cfg)
            except Exception as exc:                                # noqa: BLE001
                print("[loader] config write failed: %s" % exc, file=sys.stderr)
    if not best_root:
        return None
    # 只有「明显更全」才自动切换，别把用户手动指定的目录抢掉
    if saved and os.path.abspath(saved) != best_root:
        if best[0] >= 20 and best[0] >= saved_score[0] * 2:
            print("[loader] 自动改用资源更全的游戏目录：%s（%d 个 pak；配置里的 %s 只有 %d 个）"
                  % (best_root, best[0], saved, saved_score[0]), file=sys.stderr)
            try:
                cfg["game_root"] = best_root
                _write_config(cfg)
            except Exception as exc:                                # noqa: BLE001
                print("[loader] config write failed: %s" % exc, file=sys.stderr)
    return best_root


_SKIP_SCAN_DIRS = {"$recycle.bin", "system volume information", "windows", "program files",
                   "program files (x86)", "programdata", "recovery", "perflogs", "intel",
                   "amd", "nvidia", "temp", "tmp"}


def _scan_drive_for_game(base: str) -> list:
    """在盘符根下扫两层目录，返回所有含 DeltaForce/Content/Paks 的目录。"""
    found: list = []
    try:
        tops = [e for e in os.scandir(base) if e.is_dir()]
    except OSError:
        return found
    tops = [e for e in tops if e.name.lower() not in _SKIP_SCAN_DIRS]
    for top in tops:
        if _paks_under(top.path):
            found.append(top.path)
    for top in tops:
        try:
            subs = [e for e in os.scandir(top.path) if e.is_dir()]
        except OSError:
            continue
        if len(subs) > 400:
            continue
        for sub in subs:
            if _paks_under(sub.path):
                found.append(sub.path)
    return found


def _deep_scan_for_game(base: str, max_dirs: int = 24000) -> list:
    """扫到第三层目录（盘:\\WeGameApps\\rail_apps\\<游戏>）。

    只在浅层候选都不像完整安装时调用一次，结果写进配置的 known_roots，
    下次启动直接用它，不会每次都扫。
    """
    found: list = []
    seen = 0

    def _take(path: str, cap: int) -> list:
        nonlocal seen
        try:
            subs = [e for e in os.scandir(path) if e.is_dir()]
        except OSError:
            return []
        if len(subs) > cap:
            return []
        out = []
        for e in subs:
            seen += 1
            if seen > max_dirs:
                break
            if e.name.lower() in _SKIP_SCAN_DIRS:
                continue
            out.append(e.path)
        return out

    for top in _take(base, 400):
        if _paks_under(top):
            found.append(top)
            continue
        for mid in _take(top, 400):
            if _paks_under(mid):
                found.append(mid)
                continue
            for leaf in _take(mid, 200):
                if _paks_under(leaf):
                    found.append(leaf)
    return found


def set_game_root(root: str) -> str:
    """记住用户选的游戏根，返回真正的 Paks 目录。"""
    global PAK_DIR, OODLE_DLL
    root = os.path.abspath(root)
    cfg = _read_config()
    cfg["game_root"] = root
    _write_config(cfg)
    paks = _paks_under(root)
    if paks:
        PAK_DIR = paks
    dll = _oodle_under(root)
    if dll:
        OODLE_DLL = dll
    return PAK_DIR


def _paks_under(root: str) -> Optional[str]:
    for sub in ("", "Game", "DeltaForce"):
        p = os.path.join(root, sub, "DeltaForce", "Content", "Paks")
        if os.path.isdir(p):
            return p
        p2 = os.path.join(root, sub, "Content", "Paks")
        if os.path.isdir(p2):
            return p2
    return None


def _oodle_under(root: str) -> Optional[str]:
    for sub in ("DeltaForce\\Binaries\\Win64", "Binaries\\Win64"):
        p = os.path.join(root, sub, "oo2core_8_win64.dll")
        if os.path.exists(p):
            return p
    return None


_GAME_ROOT = find_game_root()
# 没找到游戏目录就留空：主窗口启动时会弹目录选择器（
# 以前这里回落到开发机的绝对路径，换台机器就是「路径不存在」的怪状态）。
PAK_DIR = _paks_under(_GAME_ROOT) if _GAME_ROOT else ""
VAULT = os.path.join(WORK, "AESKey1.json")
OODLE_DLL = (_oodle_under(_GAME_ROOT) if _GAME_ROOT else "") or ""

_INDEX: Optional[Dict[str, list]] = None
INDEX_ERROR = ""
_INDEX_LOCK = threading.Lock()
_PAKS: Dict[str, object] = {}
_PAK_LOCK = threading.Lock()
_VAULT = None
_OODLE = None
_LEGACY_CLEANED = False


# --------------------------------------------------------------------------- #
# pak plumbing
# --------------------------------------------------------------------------- #
def _legacy_index_dirs() -> list:
    """旧版可能留下 fileindex.json(.gz) 的目录（升级上来时会先导入再删掉）。"""
    localapp = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    exe_dir = os.path.dirname(os.path.abspath(
        sys.executable if _frozen() else __file__))
    # 只在「用户目录 / exe 旁边」清理：打包资源目录里的东西是开发机自己放的，
    # 删了会把我自己的 work/index.tsv.gz 也带走。
    return [os.path.join(localapp, "VertexViewer", "index"),
            os.path.join(exe_dir, "data"),
            os.path.join(exe_dir, "work")]


def cleanup_legacy_index() -> list:
    """把旧版的 fileindex.json / index.tsv.gz 删除，返回删掉的文件列表。

    只删「旧格式索引文件」，不碰别的。导入到 index.db 的活儿由
    `_load_index_any()` 负责（它读到旧文件时会先 `indexdb.import_from`）。
    """
    removed = []
    for d in _legacy_index_dirs():
        for name in INDEX_NAMES:
            path = os.path.join(d, name)
            if not os.path.exists(path):
                continue
            try:
                os.remove(path)
                removed.append(path)
            except OSError as exc:                                # noqa: BLE001
                print(f"[loader] 旧索引删不掉 {path}: {exc}", file=sys.stderr)
        try:
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
                removed.append(d + os.sep)
        except OSError:
            pass
    if removed:
        print("[loader] 清理旧版索引文件：" + "; ".join(removed), file=sys.stderr)
    return removed


def _located_index():
    """返回 (路径, 类型)，类型是 'tsv' / 'json.gz' / 'json'。

    依次在 WORK、exe 旁边、打包资源、以及 exe 底下有限深度里找，
    认三种文件名：index.tsv.gz（新）、fileindex.json.gz（旧包）、fileindex.json。
    旧版留在 %LOCALAPPDATA%\\VertexViewer\\index 的文件也会被认出来（导入后即删）。
    """
    localapp = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    exe_dir = os.path.dirname(os.path.abspath(
        sys.executable if _frozen() else __file__))
    dirs = [WORK,
            os.path.join(exe_dir, "data"),
            exe_dir,
            os.path.join(BUNDLE, "data"),
            os.path.join(BUNDLE, "work"),
            BUNDLE,
            os.path.join(exe_dir, "work"),
            os.path.join(localapp, "VertexViewer", "index")]
    seen = []
    for d in dirs:
        d = os.path.abspath(d)
        if d in seen:
            continue
        seen.append(d)
        for name, kind in (("index.tsv.gz", "tsv"),
                           ("fileindex.json.gz", "json.gz"),
                           ("fileindex.json", "json")):
            p = os.path.join(d, name)
            if os.path.exists(p) and os.path.getsize(p) > 1024:
                return p, kind
    for root in (exe_dir, BUNDLE):
        d = _find_index_dir(root)
        if not d:
            continue
        for name, kind in (("index.tsv.gz", "tsv"),
                           ("fileindex.json.gz", "json.gz"),
                           ("fileindex.json", "json")):
            p = os.path.join(d, name)
            if os.path.exists(p) and os.path.getsize(p) > 1024:
                return p, kind
    return None, None


def _load_index_json(path: str, gz: bool) -> Dict[str, list]:
    """旧格式：一个 {vpath: [pak, 偏移]} 的大 JSON。gz 时边解压边报进度。"""
    total = max(1, os.path.getsize(path))
    _set_progress("正在解压资产索引", 0, total, "")
    if gz:
        chunks = []
        done = 0
        with open(path, "rb") as raw:
            with gzip.GzipFile(fileobj=raw) as g:
                while True:
                    chunk = g.read(1 << 20)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    done += len(chunk)
                    _set_progress(None, min(done, total), total,
                                  f"{done / 1048576:.1f} MB")
        blob = b"".join(chunks)
    else:
        with open(path, "rb") as fh:
            blob = fh.read()
        _set_progress(None, total, total, "")
    _set_progress("正在解析资产索引", 0, 0, "旧 JSON 格式")
    out = json.loads(blob.decode("utf-8"))
    del blob
    print(f"[loader] index loaded -> {len(out)} 条（{os.path.basename(path)}）",
          file=sys.stderr)
    return out


def _load_index_tsv(path: str) -> Dict[str, list]:
    """逐行读 TSV，顺手把真实进度写进 PROGRESS。

    进度单位是**压缩字节**（`raw.tell()`），所以进度条不会走完还卡着；
    文本里再带上「已装载 N/总数 个资产」让人看到具体数字。
    """
    total_bytes = max(1, os.path.getsize(path))
    _set_progress("正在装载资产索引", 0, total_bytes, "0 个资产")
    out: Dict[str, list] = {}
    expected = 0
    with open(path, "rb") as raw:
        with gzip.GzipFile(fileobj=raw) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as fh:
                head = fh.readline().strip()
                if head.startswith("#VERTEXVIEWER-INDEX"):
                    parts = head.split("\t")
                    if len(parts) >= 3:
                        try:
                            expected = int(parts[2])
                        except Exception:                      # noqa: BLE001
                            expected = 0
                n = 0
                step = 20000
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        vpath, pak, loc = line.rsplit("\t", 2)
                        out[vpath] = [pak, int(loc)]
                    except Exception:                          # noqa: BLE001
                        continue
                    n += 1
                    if n % step == 0:
                        done = raw.tell()
                        _set_progress(None, done, total_bytes,
                                      f"{n}/{expected or '?'} 个资产")
                _set_progress(None, total_bytes, total_bytes, f"{n} 个资产")
    extra = os.path.join(WORK, "fileindex_extra.json")
    if os.path.exists(extra):
        try:
            with open(extra, encoding="utf-8") as fh:
                out.update(json.load(fh))
        except Exception as exc:                               # noqa: BLE001
            print(f"[loader] index {extra} unavailable: {exc}", file=sys.stderr)
    print(f"[loader] index streamed -> {len(out)} 条（{os.path.basename(path)}）",
          file=sys.stderr)
    return out


def index() -> Dict[str, list]:
    global _INDEX
    if _INDEX is None:
        with _INDEX_LOCK:
            if _INDEX is None:
                _INDEX = _load_index_any()
    return _INDEX


def reset_index() -> None:
    """忘掉内存里的索引，下次 index() 重新定位并加载（设置页重建索引后调用）。"""
    global _INDEX, INDEX_ERROR
    with _INDEX_LOCK:
        _INDEX = None
    INDEX_ERROR = ""
    _MATERIAL_CACHE.clear()
    _MESH_CACHE.clear()
    skins = sys.modules.get("core.weapon_skins")
    if skins is not None:
        skins.clear_cache()



def _cache_index_path() -> str:
    localapp = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(localapp, "VertexViewer", "index", "index.tsv.gz")


def _dump_tsv(out: Dict[str, list], path: str) -> None:
    """把内存索引写成和 tools/make_index_tsv.py 一样的流式 TSV（下次启动秒开）。"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
                fh = io.TextIOWrapper(gz, encoding="utf-8", newline="")
                fh.write(f"#VERTEXVIEWER-INDEX\t1\t{len(out)}\n")
                for vpath, (pak, loc) in out.items():
                    fh.write(f"{vpath}\t{pak}\t{loc}\n")
                fh.flush()
        print(f"[loader] index rebuilt -> {path}（{len(out)} 条）", file=sys.stderr)
    except Exception as exc:                                   # noqa: BLE001
        print(f"[loader] index cache write failed: {exc}", file=sys.stderr)


def rebuild_index_from_paks() -> Dict[str, list]:
    """最后兜底：直接读游戏目录里的 .pak 索引，现场拼一份资产表。

    这样即使 data/index.tsv.gz 丢了、名字改了、格式换了，只要游戏装着，库就能用。
    344 个 pak 大约 40 秒，进度条会一个个数着走。
    """
    global INDEX_ERROR
    from .pak import PakFile
    paks = sorted(glob.glob(os.path.join(PAK_DIR, "*.pak"))) if PAK_DIR else []
    if not paks:
        INDEX_ERROR = (
            "既没有资产索引文件，也读不到游戏 pak。\n" + search_report()
            + "\n\n请用「打开游戏目录」指向游戏安装目录（里面有 DeltaForce/Content/Paks），"
              "或者把 data 目录放回 VertexViewer.exe 旁边。")
        print("[loader] " + INDEX_ERROR.replace("\n", " | "), file=sys.stderr)
        return {}
    print(f"[loader] index missing -> rebuilding from {len(paks)} paks", file=sys.stderr)
    out: Dict[str, list] = {}
    for i, path in enumerate(paks, 1):
        name = os.path.basename(path)
        _set_progress("正在从游戏 paks 重建索引", i - 1, len(paks),
                      f"{i - 1}/{len(paks)} 个 pak · 已收 {len(out)} 个资产")
        try:
            pak = PakFile(path, keyvault())
        except Exception as exc:                               # noqa: BLE001
            print(f"[loader] pak skip {name}: {exc}", file=sys.stderr)
            continue
        try:
            mount = pak.mount_point or ""
            if mount and not mount.endswith("/"):
                mount += "/"
            for rel, loc in pak.entries.items():
                out[mount + rel.replace("\\", "/")] = [name, loc]
        finally:
            pak.close()
        _set_progress(None, i, len(paks),
                      f"{i}/{len(paks)} 个 pak · 已收 {len(out)} 个资产")
    # 索引只存 SQLite（%LOCALAPPDATA%\VertexViewer\index.db），这里不再落任何
    # 中间文件：以前写 index.tsv.gz，用户会看到「新文件」又搞不清哪个才是索引。
    if not out and not INDEX_ERROR:
        INDEX_ERROR = ("从游戏 pak 里没读出资产。\n" + search_report()
                       + "\n\n如果 data 目录里缺 AESKey1.json（pak 密钥），"
                         "重建索引会失败 —— 把 data 目录补全即可。")
    INDEX_ERROR = "" if out else (
        "游戏 pak 里没读到任何资产，游戏目录可能选错了。\n" + search_report())
    return out

def _index_stamp() -> str:
    """当前 pak 集合的指纹：目录 + 个数 + 最新 mtime。换目录/装了新包都会变。"""
    paks = _pak_files(PAK_DIR) if PAK_DIR else []
    if not paks:
        return ""
    newest = 0.0
    for e in paks:
        try:
            newest = max(newest, e.stat().st_mtime)
        except OSError:
            pass
    return "%s|%d|%d" % (os.path.abspath(PAK_DIR), len(paks), int(newest))


def _index_stamp_path() -> str:
    localapp = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(localapp, "VertexViewer", "index", "pakset.txt")


def _read_index_stamp() -> str:
    try:
        with open(_index_stamp_path(), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _write_index_stamp(stamp: str) -> None:
    if not stamp:
        return
    try:
        path = _index_stamp_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(stamp)
    except OSError:
        pass


def _load_index_any() -> Dict[str, list]:
    """索引来源顺序：SQLite 库 → 旧格式文件（导入库）→ 现场扫描 pak 重建。"""
    global INDEX_ERROR
    from . import indexdb

    merged: Dict[str, list] = {}
    stamp = _index_stamp()
    if indexdb.is_ready() and stamp and _read_index_stamp() != stamp:
        # 索引是上一次用另一套 pak 建的（比如之前只识别到 9 个 pak 的残包），
        # 直接复用会「有名字但打不开」。pak 集合变了就丢掉重建。
        print("[loader] pak 集合变了（%s），重建索引" % stamp, file=sys.stderr)
        try:
            indexdb.drop()
        except Exception as exc:                               # noqa: BLE001
            print("[loader] index drop failed: %s" % exc, file=sys.stderr)
    if indexdb.is_ready():
        try:
            merged = indexdb.load_all()
            if merged:
                print(f"[loader] index(db) -> {len(merged)} 条（{indexdb.db_path()}）",
                      file=sys.stderr)
                # 库里已经有数据了，旧版散落的 fileindex.json 就是垃圾——
                # 留着会让人（和诊断报告）误以为「还在用 fileindex.json」。
                global _LEGACY_CLEANED
                if not _LEGACY_CLEANED:
                    _LEGACY_CLEANED = True
                    try:
                        cleanup_legacy_index()
                    except Exception as exc:                   # noqa: BLE001
                        print(f"[loader] 旧索引清理失败：{exc}", file=sys.stderr)
        except Exception as exc:                               # noqa: BLE001
            print(f"[loader] index db unreadable: {exc}", file=sys.stderr)
            merged = {}
    if not merged:
        path, kind = None, None
        try:
            path, kind = _located_index()
            if path:
                if kind == "tsv":
                    merged = _load_index_tsv(path)
                else:
                    merged = _load_index_json(path, gz=(kind == "json.gz"))
        except Exception as exc:                               # noqa: BLE001
            import traceback
            print(f"[loader] index load failed: {exc}", file=sys.stderr)
            traceback.print_exc()
            merged = {}
        if merged and path:
            # 顺手导进 SQLite：旧格式文件以后删掉也不影响启动
            try:
                indexdb.import_from(path, kind or "tsv")
            except Exception as exc:                           # noqa: BLE001
                print(f"[loader] index import skipped: {exc}", file=sys.stderr)
            else:
                # 导入成功就把旧文件删掉：用户机器上不该再出现 fileindex.json
                try:
                    cleanup_legacy_index()
                except Exception as exc:                       # noqa: BLE001
                    print(f"[loader] 旧索引清理失败：{exc}", file=sys.stderr)
    if not merged:
        # 自愈：没库也没文件，就现场从 pak 重建并存进 SQLite
        try:
            merged = rebuild_index_from_paks()
        except Exception as exc:                               # noqa: BLE001
            print(f"[loader] rebuild failed: {exc}", file=sys.stderr)
            merged = {}
        if merged:
            try:
                indexdb.build()
            except Exception as exc:                           # noqa: BLE001
                print(f"[loader] index db write failed: {exc}", file=sys.stderr)
            else:
                _write_index_stamp(stamp)
    extra = os.path.join(WORK, "fileindex_extra.json")
    if os.path.exists(extra):
        try:
            with open(extra, encoding="utf-8") as fh:
                merged.update(json.load(fh))
        except Exception as exc:                               # noqa: BLE001
            print(f"[loader] index {extra} unavailable: {exc}", file=sys.stderr)
    if not merged and not INDEX_ERROR:
        INDEX_ERROR = (
            "没有可用的资产索引，也没能从游戏 pak 重建。\n"
            + search_report()
            + "\n\n请用「打开游戏目录」指向装了该游戏的目录"
              "（里面有 DeltaForce/Content/Paks）。")
        print("[loader] " + INDEX_ERROR.replace("\n", " | "), file=sys.stderr)
    return merged


def data_file(name: str) -> str:
    r"""静态数据文件（names.json / mesh_catalog.json / AESKey1.json / pakinfo.json）的真实路径。

    这些文件以前只放 exe 旁的 `data/`，结果别人只拷了 `VertexViewer.exe` 或者漏拷
    `data/` 就全是英文名、报「找不到文件」。现在**优先用打包进程序内部的那份**
    （`_internal/dfdata/`，跟 exe 一起走、不会被漏拷），`data/` 只当可选覆盖。

    返回空字符串表示四处都没有。
    """
    exe_dir = os.path.dirname(os.path.abspath(
        sys.executable if _frozen() else __file__))
    bundle = _bundle_dir()
    cands = []
    env = os.environ.get("VERTEXVIEWER_WORK")
    if env:
        cands.append(os.path.join(env, name))
    cands += [
        os.path.join(exe_dir, "data", name),          # 用户自己放的覆盖版
        os.path.join(bundle, "dfdata", name),         # 随 exe 打包的那份
        os.path.join(bundle, "_internal", "dfdata", name),
        os.path.join(bundle, "_internal", "work", name),
        os.path.join(bundle, "_internal", "data", name),
        os.path.join(bundle, "work", name),
        os.path.join(exe_dir, name),
    ]
    if not _frozen():
        cands.append(os.path.abspath(os.path.join(ROOT, "work", name)))
    for path in cands:
        if path and os.path.isfile(path):
            return path
    return ""


def _vault_candidates() -> List[str]:
    """密钥库可能的位置：data/ 被删了也要能读到，所以多找几个地方。"""
    out = []
    hit = data_file("AESKey1.json")
    if hit:
        out.append(hit)
    for extra in (VAULT,
                  os.path.join(_bundle_dir(), "_internal", "work", "AESKey1.json"),
                  os.path.join(_bundle_dir(), "work", "AESKey1.json")):
        if extra not in out:
            out.append(extra)
    return out


def keyvault():
    global _VAULT
    if _VAULT is None:
        from .pak import load_keyvault
        for path in _vault_candidates():
            if not os.path.isfile(path):
                continue
            try:
                _VAULT = load_keyvault(path)
                if _VAULT:
                    if path != VAULT:
                        print(f"[loader] keyvault fallback -> {path}", file=sys.stderr)
                    break
            except Exception as exc:                             # noqa: BLE001
                print(f"[loader] keyvault {path}: {exc}", file=sys.stderr)
        if _VAULT is None:
            _VAULT = {}
    return _VAULT


def oodle():
    """Oodle 解压器（实现在 core/oodle.py，按 dll 查找顺序自动定位）。"""
    global _OODLE
    if _OODLE is None:
        from .oodle import get_oodle
        _OODLE = get_oodle()
    return _OODLE


def pak_for(name: str):
    with _PAK_LOCK:
        pak = _PAKS.get(name)
        if pak is None:
            from .pak import PakFile
            pak = PakFile(os.path.join(PAK_DIR, name), keyvault())
            _PAKS[name] = pak
        if not hasattr(pak, '_viewer_read_lock'):
            pak._viewer_read_lock = threading.RLock()
        return pak


def siblings(vpath: str) -> Dict[str, str]:
    """'x.uasset' -> {'uasset': ..., 'uexp': ..., 'ubulk': ...} virtual paths."""
    base, ext = os.path.splitext(vpath)
    out = {ext.lstrip(".").lower(): vpath}
    idx = index()
    for want in ("uexp", "ubulk", "uptnl", "m.ubulk"):
        cand = f"{base}.{want}"
        if cand in idx:
            out[want.replace("m.", "")] = cand
    return out


def read_entry(vpath: str) -> bytes:
    """Read one pak entry (decrypt + Oodle). Cached by `cache.py` when the UI
    is driving; direct pak reads here are for CLI / tests."""
    idx = index()
    ent = idx.get(vpath)
    if ent is None:
        raise KeyError(vpath)
    pakname = ent[0]
    pak = pak_for(pakname)
    # Model loading and the inspection index can read the same shared handle.
    # Keep each seek/read/decompress operation together on that archive.
    with pak._viewer_read_lock:
        return pak.read(vpath, oodle())


def load_blobs(vpath: str) -> Dict[str, bytes]:
    """Fetch the .uasset plus its .uexp / .ubulk sidecars."""
    out: Dict[str, bytes] = {}
    for kind, spath in siblings(vpath).items():
        try:
            out[kind] = read_entry(spath)
        except Exception as exc:                                  # noqa: BLE001
            print(f"[loader] {kind} {spath}: {type(exc).__name__}: {exc}", file=sys.stderr)
    return out


# --------------------------------------------------------------------------- #
# asset classification
# --------------------------------------------------------------------------- #
_MESH_RE = re.compile(r"(^|/)(SM_|SKM_|StaticMesh|SkeletalMesh)", re.I)
_NAME_CACHE: Dict[str, Optional[str]] = {}

# 贴图绑定策略。FModel 导出时会先按包路径把贴图摆到模型自己的目录里，
# 所以「按目录找」才是与游戏一致的语义；全局同名猜图只作为可选的老行为。
STRICT_DIRS: bool = True

# `*_NRMMap` 是「法线 RG + 粗糙度 B + AO A」打包图。参考实现
# （DeltaModelViewer / 用户给的 .blend）**只把 RG 当法线**，粗糙度仍然是材质标量；
# 打开这个开关才会从 B 通道合成 ORM（会更亮更油，和参考实现不一致）。
NRM_ROUGHNESS: bool = False


def set_strict_dirs(on: bool) -> None:
    """打开后贴图只从模型/材质自己的目录取（FModel 语义），找不到就留空。"""
    global STRICT_DIRS
    STRICT_DIRS = bool(on)
_TEXDIR_RE = re.compile(r"/Textures?/|^T_|/T_", re.I)
_MATDIR_RE = re.compile(r"/Materials?/|(^|/)(M_|MI_|MIC_)", re.I)


# 商城皮肤/展柜模型放在 `Content/Commerical/`（游戏里就是这个拼写，另有少量
# `Commercial/`），布局和 `Models/` 完全不同：
#   Commerical/WeaponAppear/Ma1/<皮肤>/MP7/Model/<部件>/<部件>_3P.uasset
#   Commerical/PropAppear/Ma2/<道具>/<道具>_1P.uasset
# 以前「是不是网格」的判断只认 `/Content/Models/`，于是这五万多个皮肤模型在
# 模型库里一条都看不到（`list_models("Models/")` 直接按路径把它筛掉了）。
# 注意必须带上 `/Content/`：`BluePrints/UI/.../Commercial/...` 里也有一堆叫
# Commercial 的子目录（UMG 控件），那些是蓝图不是模型，不能算进来。
_COMMERCIAL_MARKERS = ("/content/commerical/", "/content/commercial/")
# 这些目录里是材质/贴图/贴图孪生/动画/特效/UI 图集，不是网格
# （`Ani`/`Anmi`/`SP`/`BakedSprite`/`Atlas` 都是游戏里实际用过的拼法）
_MESH_SKIP_DIRS = ("/textures/", "/texture/", "/materials/", "/material/",
                   "/gentexdir/", "/gentexdirhd/", "/gentexdirlod/",
                   "/anim/", "/animation/", "/animations/", "/anims/",
                   "/animlayer/", "/aimns/", "/ainm/", "/anm/", "/anima/",
                   "/ani/", "/anmi/", "/aniamtion/", "/montage/", "/curve/",
                   "/effect/", "/effects/", "/particle/", "/particles/",
                   "/fx/", "/audio/", "/sound/", "/icon/", "/icons/",
                   "/baked", "/sprite", "/sp/", "/sourcetexture/", "/atlas/",
                   "/ui/", "/render/", "/preview/", "/thumb/")
_MESH_SKIP_SUFFIXES = ("_skeleton", "_physicsasset", "_destructible", "_sk",
                       "_animsequence", "_montage", "_blendspace", "_poseasset")
# 名字里带这些词的资产基本是图集/贴图/贴纸，不是能渲染的网格
_MESH_SKIP_NAME_PARTS = ("icon", "sprite", "baked", "texture", "font", "logo",
                         "pattern", "sticker", "decal")


def is_commercial(vpath: str) -> bool:
    """是不是 `Content/Commerical/`（商城皮肤/展柜）里的资产。"""
    low = str(vpath).replace("\\", "/").lower()
    return any(m in low for m in _COMMERCIAL_MARKERS)


def commercial_like_mesh(vpath: str) -> bool:
    """Commerical/ 里「看起来是可渲染网格」的资产（不在类名目录里时的兜底）。

    `work/mesh_catalog.json` 只扫过 `Models/`，所以这些资产的 `asset_class()` /
    `is_mesh()` 都是 None（未知）；靠路径 + 文件名把网格、材质、贴图、骨骼、
    物理体区分开，既能把它们列出来，也不会把 `.uasset` 贴图混进模型库。
    """
    low = str(vpath).replace("\\", "/").lower()
    if not low.endswith(".uasset"):
        return False
    if not is_commercial(low):
        return False
    if any(d in low for d in _MESH_SKIP_DIRS):
        return False
    stem = low.rsplit("/", 1)[-1]
    if any(s in stem for s in _MESH_SKIP_SUFFIXES):
        return False
    if any(w in stem for w in _MESH_SKIP_NAME_PARTS):
        return False
    # 材质实例 / 贴图 / 蓝图 / 数据表之类的前缀
    if stem.startswith(("t_", "mi_", "mpc_", "mf_", "ns_", "abp_", "bp_", "wbp_",
                        "da_", "dt_", "st_", "ps_", "e_", "ac_", "hu_", "wi_",
                        "p_", "fx_", "vfx_")):
        return False
    return True


def classify(vpath: str) -> str:
    if _MESH_RE.search(os.path.basename(vpath)) or "/Models/" in vpath and "/Textures/" not in vpath:
        return "mesh"
    if commercial_like_mesh(vpath):
        return "mesh"
    if "/Textures/" in vpath or _TEXDIR_RE.search(os.path.basename(vpath)):
        return "texture"
    if _MATDIR_RE.search(vpath):
        return "material"
    return "other"


def model_dir(vpath: str) -> str:
    """Directory that owns a mesh asset (used to find GenTexDirHD twins)."""
    return os.path.dirname(vpath)


def tex_dir_for(vpath: str) -> Optional[str]:
    """`.../Content/Models/X/Y/M_Foo/SM_Foo.uasset` -> `.../Content/GenTexDirHD/Game/Models/X/Y/M_Foo`

    `Commerical/`（皮肤）同理映射到 `GenTexDirHD/Game/Commerical/…`；贴图更常见的
    位置是同级的 `Texture/HD/`，那条路由 `textures_in()` 直接扫目录负责。
    """
    d = model_dir(vpath)
    for marker, prefix in (("/Content/Models/", "Models"),
                           ("/Content/Commerical/", "Commerical"),
                           ("/Content/Commercial/", "Commercial")):
        if marker in d:
            rel = d.split(marker, 1)[1]
            return f"../../../DeltaForce/Content/GenTexDirHD/Game/{prefix}/{rel}"
    return None


def textures_in(dir_vpath: str, limit: int = 32):
    """All T_* texture assets that live under one directory (recursive, 1 level).

    该游戏的目录名有两种拼法：`Textures/`（武器/载具）和 `Texture/`（道具/皮肤）。
    只认复数会让整类道具变成「有材质没贴图」。
    """
    prefix = dir_vpath.rstrip("/") + "/"
    out = []
    for k in _under(prefix):
        low = k.lower()
        if ("/textures/" in low or "/texture/" in low) and low.endswith(".uasset"):
            out.append(k)
            if len(out) >= limit:
                break
    return out


# --------------------------------------------------------------------------- #
# model loading
# --------------------------------------------------------------------------- #
def load_model(vpath: str, *, lod: int = 0, want_textures: bool = True,
               want_cn: bool = True) -> ModelBundle:
    """The one entry point the UI calls."""
    bundle = ModelBundle()
    bundle.mesh = load_mesh(vpath, lod=lod)
    # 有些 1P 包只有壳没有几何（`props_collect_Buliding_500_1P` 连 ubulk 都没有），
    # 直接回退到同目录能渲染的变体，别让用户点了卡片看到一片空。
    if bundle.mesh is None or not getattr(bundle.mesh, "lods", None):
        bundle.mesh = _load_mesh_fallback(vpath, lod=lod)
    bundle.display_name = os.path.splitext(os.path.basename(vpath))[0]

    if bundle.mesh is not None and bundle.mesh.lods:
        # 材质一律**直接从包里的材质资产读**（FModel 也是这么干的），
        # 不再读模型目录里可能存在的 material .json —— 那份 json 经常是
        # 别的工具留下的旧数据，读它反而把正确的节点参数盖掉。
        bundle.materials = load_materials_for(bundle.mesh, vpath)
        # 很多 3P 模型的材质是「虚拟材质/特效材质」，包里没有 BaseColor 贴图，
        # 打开就是一片灰白；同一件物品的 UI / LAY / HD 变体往往贴图齐全。
        # 这里自动借一份过来（几何还是用用户点的那个），并在状态栏说明来源。
        if not bundle.mesh.material_paths and not _has_any_base(bundle.materials):
            alt = _borrow_materials(bundle.mesh, vpath)
            if alt is not None:
                bundle.materials, src = alt
                bundle.material_note = f"这套材质原包没有贴图，已借用 {src} 的材质"
                print(f"[loader] {os.path.basename(vpath)} 借材质 <- {src}", flush=True)
        if want_textures:
            bundle.textures = load_textures_for(bundle.materials)
        if not bundle.mesh.material_paths:
            bundle.materials = _order_materials(bundle.materials, vpath)

    if want_cn:
        try:
            from .cnnames import resolve_cn
            bundle.display_name_cn = resolve_cn(vpath) or ""
        except Exception:                                          # noqa: BLE001
            bundle.display_name_cn = ""
    return bundle


_VARIANT_SUFFIXES = ("_3P", "_1P", "_LAY", "_HD", "_LAY_HD", "_3P_HD", "_1P_HD")

# 材质名里这些词没有区分度（几乎每个材质都带），算分时丢掉
_MAT_STOP = {"m", "mi", "hd", "bp", "body", "mesh", "sk", "skm", "1p", "3p", "ui",
             "lay", "parts", "part", "mat", "inst", "material", "parent"}


def _mat_tokens(text: str) -> List[str]:
    low = str(text).lower().replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    raw = re.split(r"[_\-\s]+", low)
    return [t for t in raw if t and t not in _MAT_STOP]


def _order_materials(materials, vpath: str):
    """把「最像这个模型自己的」材质排到第一位。

    干员/皮肤网格的导出体里找不到 section 表（见 docs/NOTES-24 §6），整个网格
    只能用 `materials[0]`；而材质槽第 0 个未必是本体的那套（皮肤网格里常常是
    Head/BP/Lower 之类排在前面），挑错了整只角色就是别人的贴图 —— 用户看到的
    「材质混乱」多半是这个。这里按词重合度重排，顺序稳定、不改变材质内容。
    """
    if not materials or len(materials) < 2:
        return materials
    stem = os.path.splitext(os.path.basename(str(vpath)))[0]
    tokens = set(_mat_tokens(stem))
    if not tokens:
        return materials
    scored = []
    for i, mat in enumerate(materials):
        mt = set(_mat_tokens(getattr(mat, "name", "") or getattr(mat, "pak_path", "")))
        scored.append((len(tokens & mt), -i, i))
    scored.sort(reverse=True)
    best = scored[0][0]
    if best <= 0:
        return materials
    order = [i for _score, _neg, i in scored]
    return [materials[i] for i in order]



def _load_mesh_fallback(vpath: str, *, lod: int = 0):
    """同一件物品换个变体再试（1P 空包 → 3P/LAY）。"""
    stem, ext = os.path.splitext(vpath)
    low = stem.lower()
    for suf in _VARIANT_SUFFIXES:
        if low.endswith(suf.lower()):
            base = stem[: -len(suf)]
            for alt in _VARIANT_SUFFIXES:
                if alt.lower() == suf.lower():
                    continue
                cand = base + alt + ext
                try:
                    mesh = load_mesh(cand, lod=lod)
                except Exception:                          # noqa: BLE001
                    mesh = None
                if mesh is not None and getattr(mesh, "lods", None):
                    print(f"[loader] {os.path.basename(vpath)} 没有几何，回退到 {os.path.basename(cand)}",
                          flush=True)
                    return mesh
            break
    return None


def _has_any_base(materials) -> bool:
    """这套材质里有没有任何一张 BaseColor？没有就当「贴图丢了」。"""
    return any(getattr(m, "base_color_texture", "") for m in (materials or ()))


# 借材质时的优先级：UI 最全（游戏里物品栏就是它），其次 LAY（大厅展示），
# 再其次 HD/1P；最后才回头借 3P 自己的兄弟。
_BORROW_SUFFIXES = ("_UI", "_LAY", "_HD", "_LAY_HD", "_3P_HD", "_1P_HD", "_1P", "_3P")


def _borrow_materials(mesh, vpath: str):
    """同一件物品换个变体去读材质，返回 (materials, 变体名) 或 None。"""
    stem, ext = os.path.splitext(vpath)
    low = stem.lower()
    for suf in _BORROW_SUFFIXES:
        if not low.endswith(suf.lower()):
            continue
        base = stem[: -len(suf)]
        for alt in _BORROW_SUFFIXES:
            if alt.lower() == suf.lower():
                continue
            cand = base + alt + ext
            if "/textures/" in cand.lower().replace("\\", "/"):
                continue                       # 贴图目录下同名前缀的不是网格
            try:
                mats = load_materials_for(mesh, cand)
            except Exception:                                   # noqa: BLE001
                continue
            if _has_any_base(mats):
                return mats, os.path.basename(cand)
        break
    return None


_MESH_CACHE: Dict[tuple, object] = {}

def load_mesh(vpath: str, *, lod: int = 0) -> Optional[Mesh]:
    try:
        from .mesh import load_mesh_from_blobs
    except Exception:                                              # noqa: BLE001
        try:
            from .mesh import load_mesh_from_bytes as _legacy
            load_mesh_from_blobs = lambda v, b: _legacy(             # noqa: E731
                b.get("uasset", b""), b.get("uexp", b""), b.get("ubulk"), v)
        except Exception as exc:                                   # noqa: BLE001
            print(f"[loader] mesh parser not ready: {exc}", file=sys.stderr)
            return None
    key = (vpath, int(lod))
    hit = _MESH_CACHE.get(key)
    if hit is not None:
        return hit
    blobs = load_blobs(vpath)
    if "uasset" not in blobs:
        return None
    try:
        mesh = load_mesh_from_blobs(vpath, blobs)
    except Exception as exc:                                       # noqa: BLE001
        print(f"[loader] mesh parse failed for {vpath}: {exc}", file=sys.stderr)
        return None
    # 渲染直接使用本次解析的数据。旧的按文件名缓存的 .uemodel 没有来源或
    # 解析器版本校验，还丢失 UV/切线信息，不能反过来覆盖刚读出的几何。
    # .uemodel 仍通过导出器按需生成。
    # 骨骼网格解一次要十几秒（容器扫描），来回点同一个资产必须命中缓存。
    _MESH_CACHE[key] = mesh
    while len(_MESH_CACHE) > 32:                                  # 32 个网格够用
        _MESH_CACHE.pop(next(iter(_MESH_CACHE)))
    return mesh


MATERIAL_TEX_HINTS = (
    ("basecolormap", "base_color_texture"), ("basecolor", "base_color_texture"),
    ("albedo", "base_color_texture"), ("diffuse", "base_color_texture"),
    ("mramap", "orm_texture"), ("mra", "orm_texture"), ("orm", "orm_texture"),
    ("metallicroughness", "orm_texture"), ("occlusionroughness", "orm_texture"),
    ("normalmap", "normal_texture"), ("normal", "normal_texture"),
    ("emissivemap", "emissive_texture"), ("emissive", "emissive_texture"),
    ("maskmap", "mask_texture"),
)

# 材质里 texture 参数名 -> 渲染槽位。参数名是美术手写的，写法五花八门，
# 一律先小写去空格再查表；`RoughnessMap`/`MetallicMap` 是单通道贴图，
# 不能塞进 orm 槽（否则玻璃件会渲成一块铬），单独存到 roughness_texture 里。
PARAM_SLOT = {
    "basecolormap": "base_color_texture", "basecolor": "base_color_texture",
    "basemap": "base_color_texture", "basecolortexture": "base_color_texture",
    "diffusemap": "base_color_texture", "diffuse": "base_color_texture",
    "albedomap": "base_color_texture", "albedo": "base_color_texture",
    "colormap": "base_color_texture",
    "normalmap": "normal_texture", "normal": "normal_texture",
    "normaltexture": "normal_texture",
    "mramap": "orm_texture", "mra": "orm_texture", "ormmap": "orm_texture",
    "orm": "orm_texture", "armmap": "orm_texture",
    "emissivemap": "emissive_texture", "emissive": "emissive_texture",
    "emissivemaskmap": "emissive_texture", "emissionmaskmap": "emissive_texture",
    "maskmap": "mask_texture",
    "roughnessmap": "roughness_texture", "roughness": "roughness_texture",
    "metallicmap": "metallic_texture", "metallic": "metallic_texture",
    "heightmap": "height_texture",
}


_SLOT_TOKENS = {
    "base_color_texture": ("basecolormap", "basecolor", "albedo", "diffuse",
                           "colormap", "_bc", "_c", "_d", "_diff"),
    "normal_texture": ("normalmap", "normal", "nrm", "_n", "_nce"),
    "orm_texture": ("mra", "orm", "arm", "_mc", "masksmap", "ao"),
    "roughness_texture": ("roughness", "_r", "rough"),
    "metallic_texture": ("metallic", "_m"),
    "emissive_texture": ("emissive", "_e", "_em", "_mask"),
}


def _slot_ok(slot: str, ref: str) -> bool:
    """槽位语义校验：`orm` 里塞了一张 `_BC` 会让模型变成铬/纯白，必须拦掉。

    该游戏的道具材质常常只有 `_BC` + `_NRM` 两张图，早前按参数顺序兜底填槽，
    会把 `_BC` 重复塞进 orm ⇒ 金属度直接读成红色通道（0.8 左右）+ 粗糙度读绿
    通道，于是“纯白只有一点点贴图”。这里按文件名 token 验一遍。
    """
    low = str(ref or "").lower()
    if not low:
        return False
    toks = _SLOT_TOKENS.get(slot)
    if not toks:
        return True
    stem = low.rsplit("/", 1)[-1].replace(".uasset", "")
    for tok in toks:
        if tok.startswith("_"):
            if stem.endswith(tok) or f"{tok}_" in stem or f"{tok}map" in stem:
                return True
        elif tok in stem:
            return True
    return False


def _validate_slots(mat) -> None:
    # A declared engine parameter determines its channel. Some real character
    # textures use _C1, _CSSS, _HD or constant-color names instead of _C/_MRA.
    declared = {}
    for name, value in (getattr(mat, 'texture_params', None) or {}).items():
        slot = PARAM_SLOT.get(str(name).replace(' ', '').replace('_', '').lower())
        if slot and str(value).startswith('/Game/'):
            declared[slot] = '../../../DeltaForce/Content/' + str(value)[6:].split('.', 1)[0] + '.uasset'
    for slot in ("base_color_texture", "normal_texture", "orm_texture",
                 "roughness_texture", "metallic_texture", "emissive_texture"):
        ref = getattr(mat, slot, "")
        if ref and ref != declared.get(slot) and not _slot_ok(slot, ref):
            setattr(mat, slot, "")


def _fill_from_params(mat, base_dir: str = "") -> None:
    """把材质资产里自带的 texture/scalar 参数落实到渲染槽位。

    这是「材质怎么上才对」的关键：`M_Head_..._HD` 自己在 `texture_params` 里
    写死了 `BaseColorMap / MRAMap / NormalMap`，玻璃件 `M_HAAVK_094_G` 写的是
    `NormalMap / RoughnessMap + Metallic 1.0`。别人（目录猜图）只是兜底，
    不能反过来把材质自己写死的槽位覆盖掉。
    """
    base_dir = base_dir or ""
    params = getattr(mat, "texture_params", None) or {}
    for pname, ref in list(params.items()):
        key = str(pname).replace(" ", "").replace("_", "").lower()
        slot = PARAM_SLOT.get(key)
        if slot is None or not ref:
            continue
        if getattr(mat, slot, ""):
            continue
        resolved = resolve_texture_ref(str(ref), base_dir)
        if resolved:
            setattr(mat, slot, resolved)

    scal = {str(k).replace(" ", "").lower(): v
            for k, v in (getattr(mat, "scalar_params", None) or {}).items()}
    has_orm = bool(getattr(mat, "orm_texture", ""))
    if not has_orm:
        for key, attr in (("metallic", "metallic"), ("roughness", "roughness")):
            if key in scal:
                try:
                    setattr(mat, attr, max(0.0, min(1.0, float(scal[key]))))
                except (TypeError, ValueError):
                    pass


def resolve_asset(ref: str, base_dir: str = "") -> Optional[str]:
    """Resolve a material reference (bare name / relative / virtual path)."""
    if not ref:
        return None
    idx = index()
    ref = ref.replace("\\", "/")
    if ref.startswith('/Game/'):
        exact = '../../../DeltaForce/Content/' + ref[6:].split('.', 1)[0] + '.uasset'
        return exact if exact in idx else None
    if ref in idx:
        return ref
    name = os.path.basename(ref)
    if not name.lower().endswith(".uasset"):
        name += ".uasset"
    candidates = []
    for pre in ("../../../DeltaForce/Content/", "../../../"):
        candidates.append(pre + ref.lstrip("./"))
        if base_dir:
            candidates.append(pre + base_dir.lstrip("./") + "/" + ref.lstrip("./"))
    if base_dir:
        candidates += [f"{base_dir}/Materials/{name}", f"{base_dir}/{name}"]
    for c in candidates:
        if c in idx:
            return c
    # last resort: unique suffix match
    if STRICT_DIRS:
        # FModel 语义：解析不到就空着，绝不在全库随便挑一个同名资产
        # （这一步以前会 return hits[0]，把别的模型的图/材质套上来）
        return None
    hits = [k for k in idx if k.endswith("/" + name)]
    if len(hits) == 1:
        return hits[0]
    return hits[0] if hits else None


def _is_ui_asset(path: str) -> bool:
    """UI/图标类资产不能当模型贴图用。

    `Commerical/Icon/ItemIconWeapon_*` 之类的图标图里印着武器图 + 序列号文字，
    一旦被当固有色套到模型上，模型就变成「金色图集 + 6864」那种鬼样子。
    """
    low = (path or "").lower()
    return any(token in low for token in
               ("/icon/", "itemicon", "/ui/", "uicon", "/uiicon/", "/font/",
                "/thumbnail/", "/gallery/"))


def _stem_bonus(texture_vpath: str, model_stem: str) -> int:
    """贴图名和模型名共享的 token 越多越可信（+0~30）。

    武器/载具的 `GenTexDirHD/.../Textures` 里常有多件共用的大图集
    （`T_VMGen_BaseColorMap_<hash>`），只按「命中 BaseColorMap」挑会挑到别人那本，
    模型表面就会采样到图集里别的部位、甚至出现「6864」这种印字。名字对得上的优先。
    """
    if not model_stem:
        return 0
    mt = {t for t in re.split(r"[^a-z0-9]+", model_stem.lower()) if len(t) > 2}
    tt = {t for t in re.split(r"[^a-z0-9]+", os.path.basename(texture_vpath).lower()) if len(t) > 2}
    if not mt or not tt:
        return 0
    return min(30, 10 * len(mt & tt))


_UNDER_CACHE: Dict[str, list] = {}


def _under(prefix: str) -> list:
    """`index()` 里以 prefix 开头的键（带缓存：一次载入会查同一个目录很多次）。"""
    hit = _UNDER_CACHE.get(prefix)
    if hit is None:
        hit = [k for k in index() if k.startswith(prefix)]
        _UNDER_CACHE[prefix] = hit
    return hit


def _slots_from_dir(dir_vpath: str, slots: Dict[str, str],
                    model_stem: str = "") -> None:
    """从贴图目录里挑 base/normal/orm —— 用打分而不是「命中第一个就算」。

    参考 DeltaModelViewer 的做法：官方贴图导出的名字里一定带
    `BaseColorMap`/`NormalMap` 这种明示词，所以打分时明示词排最前；
    同时用负分把 `Mask/MRA/ORM/Emissive/UI/Logo/Decal` 这类挡在 base 槽之外
    （以前按 `_c` 后缀兜底，会把发光图/遮罩图当成固有色，渲出来一片金灿灿）。
    """
    root = dir_vpath.rstrip("/")
    cands = [k for k in _under(root + "/T")
             if (k.startswith(root + "/Textures/") or k.startswith(root + "/Texture/"))
             and k.lower().endswith(".uasset")
             and not _is_ui_asset(k)]
    if not cands:
        return

    def stem(name: str) -> str:
        return os.path.basename(name).split(".")[0].lower()

    def _tokens(name: str) -> List[str]:
        return [t for t in re.split(r"[^a-z0-9]+", name) if t]

    def score(name: str, kind: str) -> int:
        s = stem(name)
        toks = _tokens(s)

        def hit(pat: str) -> bool:
            """按「token 前缀」匹配，而不是裸子串。

            裸子串会出事：`BaseColorMap` 里含 `orm`（col**orm**ap），
            于是固有色图被当成 ORM 图直接判负——这就是枪械件丢固有色贴图的原因。
            """
            p = pat.strip("_")
            if not p:
                return False
            if len(p) <= 2:
                return any(t == p for t in toks)
            return any(t == p or t.startswith(p) for t in toks)

        if kind == "base":
            good = (("basecolormap", 100), ("basecolor", 92), ("albedomap", 84),
                    ("albedo", 80), ("diffusemap", 76), ("diffuse", 70),
                    ("colormap", 64), ("_c", 52), ("_d", 44))
            bad = ("mask", "mra", "orm", "arm", "emissive", "emi", "normal",
                   "nrm", "nce", "rough", "metal", "ao", "spec", "utility",
                   "logo", "decal", "icon", "ui", "hdri", "sky",
                   "gradient", "noise", "halftone", "hatch", "pattern")
        elif kind == "normal":
            good = (("normalmap", 100), ("nrmmap", 96), ("normal", 92), ("nrm", 84),
                    ("nce", 78), ("_n", 56))
            bad = ("basecolor", "basecolormap", "albedo", "diffuse", "mask", "mra",
                   "orm", "emissive", "rough", "metal", "ui", "icon", "logo", "decal")
        else:                                            # orm
            good = (("mramap", 100), ("mra", 92), ("ormmap", 88), ("orm", 84),
                    ("arm", 76), ("_r", 40))
            bad = ("basecolor", "basecolormap", "albedo", "diffuse", "normal", "nrm",
                   "mask", "emissive", "ui", "icon", "logo", "decal")
        best = 0
        for token, pts in good:
            if hit(token):
                best = max(best, pts)
        if best == 0:
            return 0
        if any(hit(token) for token in bad):
            return best - 1000
        return best

    for kind, slot in (("base", "base_color_texture"),
                       ("normal", "normal_texture"),
                       ("orm", "orm_texture")):
        if slot in slots:
            continue
        ranked = sorted(((score(k, kind) + _stem_bonus(k, model_stem), k)
                         for k in cands), key=lambda t: -t[0])
        if ranked and ranked[0][0] > 0:
            slots[slot] = ranked[0][1]

    # 发光图：只认明示词，别把 `_E` 后缀的遮罩误塞进来
    if "emissive_texture" not in slots:
        for k in cands:
            s = stem(k)
            if ("emissivemap" in s or "emissive" in s) and "mask" not in s:
                slots["emissive_texture"] = k
                break



_SKIN_DIR_CACHE: Dict[str, set] = {}


def _skin_tex_dirs(stem: str) -> set:
    """皮肤（`Commerical/WeaponAppear/<赛季>/<皮肤>/.../Texture/`）贴图目录。

    该游戏的武器皮肤不复用本体贴图：本体在 `GenTexDirHD/.../<部位>/Textures`，
    皮肤在 `WeaponAppear/.../<皮肤名>/Common/Texture`，目录名里带着模型名。
    这里按「目录名 == 模型名(去后缀)」逆查，命中就用皮肤那套图，
    否则皮肤模型会套上本体贴图，看着就是「材质位置不对」。
    """
    key = stem.lower()
    if key in _SKIN_DIR_CACHE:
        return _SKIN_DIR_CACHE[key]
    if not _SKIN_DIR_CACHE:
        for k in index():
            low = k.lower()
            if "/weaponappear/" not in low:
                continue
            if "/texture/" not in low and "/textures/" not in low:
                continue
            d = k.rsplit('/', 1)[0]
            _SKIN_DIR_CACHE.setdefault(os.path.basename(d).lower(), set()).add(d)
    return _SKIN_DIR_CACHE.get(key, set())


_TEXNAME_CACHE: Dict[str, str] = {}

# 贴图全局缓存：HD 角色一次要解 16 张 2048²BC7（≈64MB 解码），
# 来回点同一个模型不能每次都重解一遍。
_GLOBAL_TEX_CACHE: Dict[str, object] = {}
_TEX_CACHE_BYTES = 0
_TEX_CACHE_LIMIT = 640 * 1024 * 1024


def _remember_texture(resolved: str, tex) -> None:
    global _TEX_CACHE_BYTES
    if tex is None:
        return
    rgba = getattr(tex, "rgba", None)
    nbytes = int(getattr(rgba, "nbytes", 0) or 0)
    if nbytes and _TEX_CACHE_BYTES + nbytes > _TEX_CACHE_LIMIT:
        _GLOBAL_TEX_CACHE.clear()
        _TEX_CACHE_BYTES = 0
    if resolved not in _GLOBAL_TEX_CACHE:
        _TEX_CACHE_BYTES += nbytes
    _GLOBAL_TEX_CACHE[resolved] = tex


def clear_texture_cache() -> None:
    global _TEX_CACHE_BYTES
    _GLOBAL_TEX_CACHE.clear()
    _TEX_CACHE_BYTES = 0


_STEM_SLOT_CACHE: Dict[str, Dict[str, str]] = {}

_SLOT_SUFFIXES = (
    ("_basecolormap", "base_color_texture"),
    ("_basecolor", "base_color_texture"),
    ("_albedo", "base_color_texture"),
    ("_diffuse", "base_color_texture"),
    ("_c_hd", "base_color_texture"),
    ("_c", "base_color_texture"),
    ("_nrmmap", "normal_texture"),
    ("_normalmap", "normal_texture"),
    ("_nrm", "normal_texture"),
    ("_normal", "normal_texture"),
    ("_n", "normal_texture"),
    ("_mramap", "orm_texture"),
    ("_mra", "orm_texture"),
    ("_orm", "orm_texture"),
    ("_maskmap", "mask_texture"),
    ("_roughnessmap", "roughness_texture"),
    ("_roughness", "roughness_texture"),
    ("_r", "roughness_texture"),
    ("_emissivemap", "emissive_texture"),
    ("_emissive", "emissive_texture"),
)

_MODEL_SUFFIX_RE = re.compile(r"_(1p|3p|ui|hd|sk|lod\d|skeleton)$", re.I)
_MAT_SUFFIX_RE = re.compile(r"_(mt|mi|mic|mat|inst)$", re.I)


def _texture_name_map() -> Dict[str, str]:
    """`贴图文件名(小写,无扩展) -> vpath`，只收 /Textures/ 下的图，建一次缓存。"""
    if _TEXNAME_CACHE:
        return _TEXNAME_CACHE
    for k in index():
        low = k.lower()
        if not low.endswith(".uasset") or "/textures/" not in low:
            continue
        base = low.rsplit("/", 1)[-1][:-len(".uasset")]
        _TEXNAME_CACHE.setdefault(base, k)
    return _TEXNAME_CACHE


def _stem_variants(vpath: str, mat_name: str = "") -> list:
    """模型名 / 材质名 → 用来找同一套贴图的候选前缀（高优先在前）。"""
    out: list = []
    for raw in (mat_name or "", os.path.splitext(os.path.basename(vpath or ""))[0]):
        stem = _MAT_SUFFIX_RE.sub("", str(raw or "").strip())
        stem = _MODEL_SUFFIX_RE.sub("", stem)
        if not stem:
            continue
        low = stem.lower()
        if low not in out:
            out.append(low)
        # `M_Kai_SOL_001_Body` 有时贴图叫 `M_Kai_SOL_001_Body_C`，也可能带 `_HD`
        hd = (stem + "_HD").lower()
        if hd not in out:
            out.append(hd)
    return out


def _stem_texture_slots(model_vpath: str, mat_name: str = "") -> Dict[str, str]:
    """按名字前缀找「同一套」贴图（找得到就返回 slot -> vpath）。"""
    key = (model_vpath or "", mat_name or "")
    hit = _STEM_SLOT_CACHE.get(str(key))
    if hit is not None:
        return hit
    names = _texture_name_map()
    slots: Dict[str, str] = {}
    mat_stem = _MODEL_SUFFIX_RE.sub("", _MAT_SUFFIX_RE.sub("", str(mat_name or "").strip())).lower()
    for stem in _stem_variants(model_vpath, mat_name):
        if len(stem) < 6:
            continue
        for suffix, slot in _SLOT_SUFFIXES:
            if slot in slots:
                continue
            vpath = names.get(stem + suffix)
            if vpath and not _is_ui_asset(vpath):
                slots[slot] = vpath
        if "base_color_texture" in slots:
            break
    # 材质自己名下有名字（`M_Kai_002_Hair_MT`）却找不到图，就不要套模型那套
    # 身体贴图 —— 头发、面罩这类是单独资产，宁可留空也别糊一张身体皮上去。
    if mat_stem and len(mat_stem) >= 6 and "base_color_texture" not in slots:
        slots = {}
    _STEM_SLOT_CACHE[str(key)] = slots
    return slots


def slots_for_model(model_vpath: str) -> Dict[str, str]:
    """模型对应的贴图槽位。三处都找，先近后远：

    1. `<模型目录>/Textures/`（角色/道具习惯把贴图放在自己目录下）
    2. `GenTexDirHD/Game/Models/<同 tail>/Textures/`（武器/载具的分离贴图目录）
    3. 按「模型名 + C/MRA/N」在全局索引里模糊找一遍
    """
    slots: Dict[str, str] = {}
    stem = os.path.basename(model_vpath).split(".")[0]
    stem = re.sub(r"_(1P|3P|UI|HD|SK)$", "", stem)
    base = model_dir(model_vpath)
    _slots_from_dir(base, slots, stem)
    tex_dir = tex_dir_for(model_vpath)
    if tex_dir:
        _slots_from_dir(tex_dir, slots, stem)
    for skin_dir in _skin_tex_dirs(stem):
        _slots_from_dir(skin_dir, slots, stem)
    if "base_color_texture" not in slots:
        # 4. 按「目录名 == 模型名」在 GenTexDirHD/LD 里找（虚拟机生成的贴图叫
        #    T_VMGen_BaseColorMap_<hash>，名字里根本没有模型名，只能靠目录认领）。
        slots.update(_gen_tex_slots_by_stem(stem, model_vpath))
    if not slots and not STRICT_DIRS:
        stem = os.path.basename(model_vpath).split(".")[0]
        stem = re.sub(r"_(1P|3P|UI|HD|SK)$", "", stem)
        for pre, stem_ in ((".C", "_C"), (".MRA", "_MRA"), (".N", "_N")):
            want = (stem + stem_).lower()
            for k in index():
                if not k.lower().endswith(".uasset") or "/textures/" not in k.lower():
                    continue
                if os.path.basename(k).split(".")[0].lower() == want:
                    _slots_from_dir(os.path.dirname(k), slots)
                    break
            if slots:
                break
    return slots


_GEN_STEM_CACHE: Dict[str, Dict[str, str]] = {}


def _gen_tex_slots_by_stem(stem: str, model_vpath: str = "") -> Dict[str, str]:
    """GenTexDirHD 里「目录名以模型名开头」的那一套贴图。

    武器/载具的贴图由虚拟机烘焙生成，文件名是 `T_VMGen_BaseColorMap_<hash>`，
    任何「名字前缀」匹配都碰不到它们；但目录名还是模型名 + 皮肤名，比如
    `Mag_45-26R_VectorExt2_065_VirusHealer/Textures/`。所以按目录前缀认领，
    同一件物品有多个皮肤时优先选和模型路径里皮肤名一致的那个。

    说明：选错皮肤只是「颜色不对」，不选才是「一片灰白」，所以宁可选。
    """
    key = ((stem or "") + "|" + (model_vpath or "")).lower()
    if not stem or len(stem) < 5:
        return {}
    hit = _GEN_STEM_CACHE.get(key)
    if hit is not None:
        return hit
    slots: Dict[str, str] = {}
    idx = index()
    low_stem = stem.lower()
    low_path = (model_vpath or "").lower()
    cands: list = []
    for k in idx:
        low = k.lower().replace("\\", "/")
        if "/gentexdir" not in low or "/textures/" not in low:
            continue
        dir_vpath = k.rsplit("/", 1)[0]
        # 拿到的是 .../<Model>/Textures，`_slots_from_dir` 要的是 <Model> 那一层
        if dir_vpath.lower().endswith("/textures") or dir_vpath.lower().endswith("/texture"):
            dir_vpath = dir_vpath.rsplit("/", 1)[0]
        name = dir_vpath.rsplit("/", 1)[-1].lower()
        if name == low_stem or name.startswith(low_stem + "_"):
            cands.append(dir_vpath)
    # 去重并排序：目录名完全等于模型名 > 皮肤名出现在模型路径里 > 名字短的
    seen = set()
    uniq = []
    for d in cands:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    uniq.sort(key=lambda d: (
        d.rsplit("/", 1)[-1].lower() != low_stem,
        d.rsplit("/", 1)[-1].lower().replace(low_stem, "") not in low_path,
        len(d),
    ))
    for dir_vpath in uniq[:4]:
        _slots_from_dir(dir_vpath, slots)
        if "base_color_texture" in slots:
            break
    _GEN_STEM_CACHE[key] = slots
    return slots


def gen_tex_slots(dir_vpath: Optional[str]) -> Dict[str, str]:
    """`GenTexDirHD/.../<Model>/Textures/T_VMGen_*Map_<hash>.uasset` -> slot map."""
    if not dir_vpath:
        return {}
    slots: Dict[str, str] = {}
    _slots_from_dir(dir_vpath, slots)
    return slots


def synthetic_material(model_vpath: str, name: str = "") -> Optional["Material"]:
    """No material asset found: build one straight from the texture dirs."""
    slots = slots_for_model(model_vpath)
    if not slots:
        return None
    mat = Material(name=name or os.path.basename(model_dir(model_vpath)),
                   pak_path=model_vpath)
    mat.base_color_texture = slots.get("base_color_texture", "")
    mat.normal_texture = slots.get("normal_texture", "")
    mat.orm_texture = slots.get("orm_texture", "")
    mat.emissive_texture = slots.get("emissive_texture", "")
    mat.texture_params = {k: v for k, v in slots.items()}
    mat.scalar_params = {"Metallic": mat.metallic, "Roughness": mat.roughness}
    if not mat.base_color_texture:
        # 一张图都没找到时候别给纯白（渲出来像发光），用中性灰的 clay 色。
        mat.base_color = (0.72, 0.72, 0.72, 1.0)
        mat.metallic, mat.roughness = 0.0, 0.55
    return mat


def _name_lookup(name: str) -> Optional[str]:
    """裸贴图名 -> 虚拟路径（材质里存的是资产名，没有目录和扩展名）。"""
    global _NAME_CACHE
    key = name.lower()
    if key in _NAME_CACHE:
        return _NAME_CACHE[key]
    hit = None
    if "/" in name or name.lower().endswith(".uasset"):
        hit = name if name in index() else None
    if hit is None:
        idx = index()
        cand = name if name.lower().endswith(".uasset") else name + ".uasset"
        looks = [k for k in idx if k.endswith("/" + cand)]
        if len(looks) > 1:
            # 有多个同名贴图时优先 HD 版本，并且不要图标/UI 目录里的那张
            looks = [k for k in looks if not _is_ui_asset(k)] or looks
            looks.sort(key=lambda k: ("GenTexDirHD" not in k, "GenTexDirLD" in k))
        hit = looks[0] if looks else None
    _NAME_CACHE[key] = hit
    return hit


_POOL_TEX: Optional[Dict[str, str]] = None


def _pool_tex_lookup(bare: str) -> Optional[str]:
    """按文件名在 `GenTexDirHD/Game/**` 共享图集池里查（hash 名天然唯一）。"""
    global _POOL_TEX
    if _POOL_TEX is None:
        pool: Dict[str, str] = {}
        pre = "../../../DeltaForce/Content/GenTexDirHD/Game/"
        for k in _under(pre):
            low = k.lower()
            if not low.endswith(".uasset") or "/t_" not in low:
                continue
            pool.setdefault(k.rsplit("/", 1)[-1][:-7].lower(), k)
        _POOL_TEX = pool
    return _POOL_TEX.get(str(bare).lower())


def resolve_texture_ref(ref: str, base_dir: str = "") -> Optional[str]:
    """材质里的贴图引用可能是虚拟路径、`/Game/...` 包路径或裸资产名。

    `base_dir` 是**引用方材质自己的包目录**：同一个贴图名在不同部位下都有
    （`M_Helmet_HAAVK_094_C` 只在头盔目录里），先按材质目录找，找不到才全局猜，
    否则会把别的武器/角色的贴图套上来（这就是「材质上得不对」的主因）。
    """
    if not ref:
        return None
    ref = str(ref).strip()
    idx = index()
    if ref.startswith('/Game/'):
        exact = '../../../DeltaForce/Content/' + ref[6:].split('.', 1)[0] + '.uasset'
        return exact if exact in idx else None
    if ref in idx:
        return ref
    bare = ref.rsplit("/", 1)[-1].split(".")[0]
    if base_dir:
        base = base_dir.rstrip("/")
        for cand in (f"{base}/Textures/{bare}.uasset", f"{base}/Texture/{bare}.uasset",
                     f"{base}/{bare}.uasset", f"{base}/Maps/{bare}.uasset",
                     f"{base}/Maps/Textures/{bare}.uasset"):
            if cand in idx:
                return cand
        # 材质和贴图不在同一层时，按「材质目录的上一级」再找一遍
        parent = os.path.dirname(base)
        for cand in (f"{parent}/Textures/{bare}.uasset", f"{parent}/Texture/{bare}.uasset",
                     f"{parent}/{bare}.uasset"):
            if cand in idx:
                return cand
        # Official skins keep their referenced textures one level deeper in
        # Texture/HD. This stays inside the exact material/model directory.
        for root in (base, parent):
            for folder in ("Textures", "Texture"):
                cand = f"{root}/{folder}/HD/{bare}.uasset"
                if cand in idx:
                    return cand
        resolved = resolve_asset(ref, base)
        if resolved:
            return resolved
    # 该游戏的共享贴图池：`GenTexDirHD/Game/MaterialLib/Textures/`
    # 与 `GenTexDirHD/Game/T_*.uasset` 里全是 `T_VMGen_<部位>Map_<32位hash>` 的
    # 打包图集。名字里的 hash 就是唯一标识，按 hash 命中**不是猜**——
    # 道具（Props）大量引用这类共享图集，严格模式若只认模型目录，
    # 整类道具就会“有材质没贴图”或套上与模型无关的图。
    pool = _pool_tex_lookup(bare)
    if pool:
        return pool
    if STRICT_DIRS:
        # FModel 模式：贴图只从「模型/材质的目录」里取，不跨目录按名字猜。
        # 猜出来的图看着像对的，实际上会把别的部位/皮肤的图套上来。
        return None
    guess = _name_lookup(bare)
    return None if (guess and _is_ui_asset(guess)) else guess


_MAT_CATALOG: Optional[Dict[str, str]] = None


def _material_catalog() -> Dict[str, str]:
    """小写资产名（无扩展名） -> 材质虚拟路径，只收材质类资产。

    该游戏的干员皮肤网格（`…/M_Kai_Haavk_049_HD/M_Kai_Haavk_049_Body_3P_HD`）
    自己目录里**只有网格**，真正的材质实例放在基础干员目录的 `Materials/` 里
    （`…/M_Kai_002_HD/Materials/MI_Kai_Haavk_049_Body_3p_HD`）。所以需要一张
    全库材质名索引，按名字片段去认。构建一次约 1~2 秒，之后 O(1) 查。
    """
    global _MAT_CATALOG
    if _MAT_CATALOG is not None:
        return _MAT_CATALOG
    cat: Dict[str, str] = {}
    for k in index():
        low = k.lower()
        if not low.endswith(".uasset"):
            continue
        if "/materials/" not in low and "/material/" not in low:
            continue
        cat[low.rsplit("/", 1)[-1][:-7]] = k
    _MAT_CATALOG = cat
    return cat


def _materials_by_name(model_vpath: str, limit: int = 8) -> List[str]:
    """按名字片段在全库材质里找「这个网格用的那套材质」。"""
    cat = _material_catalog()
    stem = os.path.basename(model_vpath).split(".")[0].lower()
    skip = {"m", "mi", "sk", "skm", "hd", "mesh"}
    toks = [t for t in re.split(r"[_\-]+", stem) if t and t not in skip]
    if len(toks) < 2:
        return []
    want = set(toks)
    head = toks[:2]                 # 前两段通常是「干员代号 + 皮肤套系」，必须是同一个
    scored = []
    for name, path in cat.items():
        mt = [t for t in re.split(r"[_\-]+", name) if t and t not in skip]
        if len(mt) < 2:
            continue
        if len(head) == 2 and not set(head) <= set(mt):
            continue
        common = len(want & set(mt))
        if common < 3 or common < len(want) - 2 or common < len(mt) - 2:
            continue
        scored.append((-common, abs(len(mt) - len(toks)), path))
    scored.sort()
    return [p for _, _, p in scored[:limit]]


_MATERIAL_CACHE: Dict[str, Material] = {}


def _load_material_asset(vpath: str, trail=()):
    """Resolve parent defaults once; callers get independent mutable bindings."""
    from .material import load_material_from_path
    if vpath in trail or len(trail) >= 8:
        return None
    cached = _MATERIAL_CACHE.get(vpath)
    if cached is not None:
        return deepcopy(cached)

    def parent(ref):
        resolved = resolve_asset(ref, os.path.dirname(vpath))
        if not resolved and "/" not in ref:
            # The material reader can expose a bare imported parent name.
            # Only accept a globally unique exact asset, never a fuzzy match.
            suffix = "/" + ref.removesuffix(".uasset") + ".uasset"
            matches = [path for path in index() if path.endswith(suffix)]
            resolved = matches[0] if len(matches) == 1 else None
        return _load_material_asset(resolved, (*trail, vpath)) if resolved else None

    result = load_material_from_path(vpath, read_entry, oodle(), read_parent=parent)
    if result is not None:
        _MATERIAL_CACHE[vpath] = deepcopy(result)
        while len(_MATERIAL_CACHE) > 128:
            _MATERIAL_CACHE.pop(next(iter(_MATERIAL_CACHE)))
    return result


def materials_in(model_vpath: str, limit: int = 8) -> list:
    """模型目录（或其 `Materials/` 子目录）里的材质资产 -> Material 列表。

    该游戏的约定：`Models/X/Y/Z/Materials/Z.uasset` 就是这个模型用的材质实例。
    自己目录里没有材质时（干员皮肤网格就是这样），退回「全库按名字片段匹配」。
    """
    base = model_dir(model_vpath)
    dirs = [base + "/Materials", base + "/Material", base]
    found: List[str] = []
    idx = index()
    for d in dirs:
        for k in idx:
            if not k.lower().endswith(".uasset") or k.rsplit('/', 1)[0] != d:
                continue
            if k == model_vpath:
                continue
            if k.lower().endswith(("_physicsasset.uasset", "_skeleton.uasset")):
                continue
            # Already have the exact local path. Global basename lookup can
            # choose a same-named skin material from another weapon's folder.
            if k not in found:
                found.append(k)
            if len(found) >= limit:
                break
        if found:
            break
    if not found:
        # 干员皮肤网格：网格单独一个目录，材质在基础干员目录里 —— 按名字片段找
        found = _materials_by_name(model_vpath, limit)

    out = []
    # 目录里可能有多个材质（不同部位 / 破坏态 / 玻璃件），按「和模型同名」优先排序，
    # 否则会把特殊材质当成默认材质，渲出来像个镜子。
    model_tokens = {t for t in re.split(r"[_\-]+",
                    os.path.basename(model_vpath).split(".")[0].lower()) if t}

    def _score(vpath: str) -> tuple:
        toks = {t for t in re.split(r"[_\-]+",
                os.path.basename(vpath).split(".")[0].lower()) if t}
        return (-len(toks & model_tokens), len(toks ^ model_tokens))

    def _slot_score(m) -> tuple:
        """有几个槽真的拿到了图 —— 越全越像「这个模型的本体材质」。"""
        filled = sum(1 for slot in ("base_color_texture", "normal_texture", "orm_texture")
                     if getattr(m, slot, ""))
        glass = 1 if _looks_like_glass(m) else 0
        lod_variant = 1 if re.search(r"_lod\d*$", str(getattr(m, "name", "") or "").lower()) else 0
        return (glass, lod_variant, -filled)

    for vpath in sorted(found, key=_score):
        mat = None
        try:
            mat = _load_material_asset(vpath)
        except Exception as exc:                                   # noqa: BLE001
            print(f"[loader] material {vpath}: {exc}", file=sys.stderr)
        if mat is None:
            mat = synthetic_material(model_vpath, os.path.basename(vpath).split(".")[0])
        if mat is not None:
            mat.pak_path = mat.pak_path or vpath
            _apply_material_slots(mat, model_vpath)
            out.append(mat)
    # 一个 section 的模型却有多个候选材质（本体 / HD 本体 / 玻璃 / _lod 变体）：
    # 先按「贴图最全、不是玻璃、不是 lod 变体」重排，第一个就是要用的那个。
    if len(out) > 1:
        out.sort(key=_slot_score)
    return out


def load_materials_for(mesh: Mesh, model_vpath: str = "") -> list:
    base_dir = model_dir(model_vpath) if model_vpath else ""
    out, seen = [], set()
    paths = list(mesh.material_paths) if mesh.material_paths else [
        sec.material_path for lod in mesh.lods[:1] for sec in lod.sections]
    for path in paths:
        mp = resolve_asset(path, base_dir) if path else None
        if mp is None and mesh.material_paths:
            out.append(Material(name='Missing source material', pak_path=path,
                                base_color=(.35, .35, .35, 1)))
            continue
        if mp is None or mp in seen:
            continue
        seen.add(mp)
        mat = None
        try:
            mat = _load_material_asset(mp)
        except Exception as exc:                               # noqa: BLE001
            print(f"[loader] material {mp}: {exc}", file=sys.stderr)
        if mat is None and not mesh.material_paths:
            mat = synthetic_material(model_vpath, os.path.basename(mp))
        if mat is None and mesh.material_paths:
            mat = Material(name=os.path.basename(mp), pak_path=mp,
                           base_color=(.35, .35, .35, 1))
        if mat is not None:
            mat.pak_path = mat.pak_path or mp
            _apply_material_slots(mat, model_vpath, allow_model_fallback=not mesh.material_paths)
            out.append(mat)
    # 骨骼网格的 section 通常不带材质路径（材质是该模型的共享实例），
    # 直接去 `模型目录/Materials/` 找。
    if not out and model_vpath:
        out = materials_in(model_vpath)
        for mat in out:
            _apply_material_slots(mat, model_vpath)
        # 骨骼网格没有 section 材质路径，通常只能靠目录里的候选材质；
        # 多候选时按「槽位填充度」重排一次（`materials_in` 已排过一次）。
        if len(out) > 1:
            out.sort(key=lambda m: (1 if _looks_like_glass(m) else 0,
                                    -sum(1 for sl in ("base_color_texture",
                                                      "normal_texture", "orm_texture")
                                         if getattr(m, sl, ""))))
    if not out and model_vpath:
        mat = synthetic_material(model_vpath)
        if mat is not None:
            out.append(mat)
    return out


def _apply_material_slots(mat, model_vpath: str, *, allow_model_fallback=True) -> None:
    """先信材质自己写的参数，再用目录猜的贴图兜底。

    顺序很重要：`M_Head_..._HD` 自己写了 BaseColorMap/MRAMap/NormalMap，
    玻璃件自己写了 RoughnessMap + Metallic，这些是权威值；目录里那把
    `T_xxx_C/_N/_MRA` 只是「这个模型大概率用这套图」的猜测。
    早先实现是拿猜测覆盖，玻璃件因此被套成头盔本体贴图，渲出来像块镜子。
    """
    mat_dir = os.path.dirname(str(getattr(mat, "pak_path", "") or ""))
    # 材质解析器会把 `texture_params` 的**裸资产名**直接塞进槽位
    #（`T_VMGen_BaseColorMap_6e7b...`，无目录无扩展名），这种名字在严格模式下
    # 必须换成真实虚拟路径，否则渲染时解析不到图 → 整类道具“有材质没贴图”。
    _mirror = tex_dir_for(model_vpath) if model_vpath else None
    for _slot in ("base_color_texture", "normal_texture", "orm_texture",
                  "emissive_texture", "roughness_texture", "metallic_texture"):
        _ref = getattr(mat, _slot, "")
        if not _ref:
            continue
        if _ref in index():
            continue
        _path = resolve_texture_ref(str(_ref), mat_dir) or (
            resolve_texture_ref(str(_ref), _mirror) if _mirror else None)
        setattr(mat, _slot, _path or "")
    _fill_from_params(mat, mat_dir)
    if _looks_like_glass(mat):
        # 玻璃/镜片（`M_..._G`、父材质 `M_Glass_InGame`、Transparent 参数 > 0）：
        # 它自己的参数才是对的，别把头盔/身体的 MRA 猜上去，否则渲染成一块铬。
        # 没有透明混合通道，就先按「低粗糙度、有金属度」的玻璃来画。
        if not getattr(mat, "roughness_texture", ""):
            mat.roughness = min(float(getattr(mat, "roughness", 0.5)), 0.15)
        mat.two_sided = True
        return
    slots = slots_for_model(model_vpath) if model_vpath and allow_model_fallback else {}
    for slot, tp in slots.items():
        if not getattr(mat, slot, ""):
            setattr(mat, slot, tp)
    # 还缺固有色时，按「模型/材质名 + 后缀」在全库找同一套贴图 —— 主要救
    # Characters / Equipments / Weapons 的**非 HD 网格**：它们的贴图只存在于
    # `Models/Characters_HD/Hero_HD/<同名>_HD/Textures/<同名>_C|_N|_MRA.uasset`，
    # 和模型目录不是一一对应（普通目录里一张图都没有）。这条不是乱猜：
    # 前缀必须和模型名（或材质名去掉 _MT）在词元级完全一致。
    if not getattr(mat, "base_color_texture", ""):
        for slot, tp in _stem_texture_slots(model_vpath, getattr(mat, "name", "")).items():
            if not getattr(mat, slot, ""):
                setattr(mat, slot, tp)
    _validate_slots(mat)
    if not getattr(mat, "base_color_texture", "") and not slots:
        # 既没有材质参数、目录里也找不到图：用中性灰 clay，别渲成发光白。
        base = getattr(mat, "base_color", None)
        if base is None or (isinstance(base, (tuple, list)) and tuple(base)[:3] == (1.0, 1.0, 1.0)):
            mat.base_color = (0.72, 0.72, 0.72, 1.0)
            if not getattr(mat, "orm_texture", ""):
                mat.metallic, mat.roughness = 0.0, 0.55


def _looks_like_glass(mat) -> bool:
    name = f"{getattr(mat, 'name', '')}|{getattr(mat, 'parent', '')}".lower()
    if "glass" in name or "透明" in str(getattr(mat, "parent", "")):
        return True
    if re.search(r"_g(\||$)", name):
        return True
    scal = {str(k).replace(" ", "").lower(): v
            for k, v in (getattr(mat, "scalar_params", None) or {}).items()}
    try:
        if float(scal.get("transparent", 0) or 0) > 0.1:
            return True
    except (TypeError, ValueError):
        pass
    return False


def load_textures_for(materials) -> list:
    """把材质引用到的贴图全部解出来（同一张图只解一次，跨模型也复用）。"""
    texs = []
    cache: Dict[str, object] = _GLOBAL_TEX_CACHE

    def _load(resolved: str):
        if resolved in cache:
            tex = cache[resolved]
            if tex is not None:
                texs.append(tex)
            return tex
        tex = None
        try:
            from .texture import load_texture, load_texture_from_path
        except Exception:                                      # noqa: BLE001
            return None
        try:
            tex = load_texture_from_path(resolved, read_entry, oodle())
        except Exception:                                      # noqa: BLE001
            try:
                blobs = load_blobs(resolved)
                tex = load_texture(blobs.get("uasset", b""), blobs.get("uexp"),
                                   blobs.get("ubulk"), resolved, blobs.get("uptnl"))
            except Exception as exc:                           # noqa: BLE001
                print(f"[loader] texture {resolved}: {exc}", file=sys.stderr)
        _remember_texture(resolved, tex)
        cache[resolved] = tex
        if tex is not None:
            texs.append(tex)
        return tex

    for mat in materials:
        mat_dir = os.path.dirname(str(getattr(mat, "pak_path", "") or ""))
        loaded: Dict[str, object] = {}
        for slot in ("base_color_texture", "normal_texture", "orm_texture",
                     "emissive_texture", "roughness_texture", "metallic_texture"):
            ref = getattr(mat, slot, "")
            if not ref:
                continue
            resolved = resolve_texture_ref(str(ref), mat_dir)
            if not resolved:
                continue
            tex = _load(resolved)
            if tex is not None:
                loaded[slot] = tex
        # 该游戏的打包图有两种命名：
        #   * `*_MRA / *Map_<hash>`   -> R=金属度 G=粗糙度 B=AO
        #   * `*_NRMMap`（道具/杂项常用）-> RG=法线XY, B=粗糙度, A=AO
        # 后者没有 ORM 图，必须从法线图的 B 通道现合成一张 ORM，
        # 否则粗糙度永远是默认 0.5、模型发亮。
        if not getattr(mat, "orm_texture", "") and NRM_ROUGHNESS:
            nrm = loaded.get("normal_texture")
            is_packed = "nrm" in str(getattr(mat, "normal_texture", "")).lower()
            if is_packed and nrm is not None and getattr(nrm, "rgba", None) is not None:
                import numpy as np
                from .types import Texture as _Tex
                rgba = np.asarray(nrm.rgba)
                h, w = rgba.shape[:2]
                orm = np.full((h, w, 4), 255, np.uint8)
                orm[..., 1] = rgba[..., 2]                # 粗糙度在 B
                if rgba.shape[-1] > 3:
                    orm[..., 2] = rgba[..., 3]            # AO 在 A
                try:
                    metal = int(max(0.0, min(1.0, float(getattr(mat, "metallic", 0.0)))) * 255)
                except (TypeError, ValueError):
                    metal = 0
                orm[..., 0] = metal
                name = f"ORM_{getattr(mat, 'name', 'mat') or 'mat'}"
                texs.append(_Tex(name=name, pak_path="", width=w, height=h, rgba=orm,
                                 srgb=False, source_format="R8G8B8A8"))
                mat.orm_texture = name
        # 只有单通道 RoughnessMap 的材质（玻璃/镜片）：合成一张 ORM 交给渲染器，
        # R=金属度标量、G=粗糙度贴图、B=1，避免被当成默认 0.5 粗糙度渲成铬。
        if not getattr(mat, "orm_texture", ""):
            rough = loaded.get("roughness_texture")
            if rough is not None and getattr(rough, "rgba", None) is not None:
                import numpy as np
                from .types import Texture as _Tex
                rgba = np.asarray(rough.rgba)
                h, w = rgba.shape[:2]
                orm = np.full((h, w, 4), 255, np.uint8)
                g = rgba[..., 1] if rgba.shape[-1] > 1 else rgba[..., 0]
                try:
                    metal = int(max(0.0, min(1.0, float(getattr(mat, "metallic", 0.0)))) * 255)
                except (TypeError, ValueError):
                    metal = 0
                orm[..., 0] = metal
                orm[..., 1] = g
                name = f"ORM_{getattr(mat, 'name', 'mat') or 'mat'}"
                texs.append(_Tex(name=name, pak_path="", width=w, height=h, rgba=orm,
                                 srgb=False, source_format="R8G8B8A8"))
                mat.orm_texture = name
    return texs


_ANIM_CLASSES = ("AnimSequence", "AnimMontage")
_MESH_CLASSES = ("StaticMesh", "SkeletalMesh")

# 只有「物品类」目录里的动画一律算把玩/检视；武器/载具/角色目录里只认明确写了
# 检视词的那些，否则 1P 开火/换弹/位移动画会被误当成检视动画。
_INSPECT_WORDS = ("view", "inspect", "show", "examine", "turn", "rotate", "open",
                  "close", "display", "play", "pick", "hand")
# 严格检视词：非物品目录里只认这几个，`_Show` 那种角色展示动作不算
_STRICT_WORDS = ("view", "inspect", "examine")
_GAMEPLAY_WORDS = ("fire", "changeclip", "reload", "recoil", "throw", "use", "equip",
                   "holster", "aim", "sprint", "walk", "run", "jump", "prone", "death",
                   "die", "hit", "pose", "montage", "getweapon", "putweapon", "supine",
                   "crouch", "move", "additive", "offset", "idle", "loop", "start",
                   "end", "enter", "exit", "swing", "bash", "stab")

_CATALOG_CLASSES: Optional[Dict[str, str]] = None
_INSPECT_MAP: Optional[Dict[str, List[str]]] = None


def _catalog_classes() -> Dict[str, str]:
    """`work/mesh_catalog.json` 里的 `{vpath: 类名}`（只读一次）。"""
    global _CATALOG_CLASSES
    if _CATALOG_CLASSES is not None:
        return _CATALOG_CLASSES
    out: Dict[str, str] = {}
    try:
        out = catalog()                       # 已经统一到 data_file() 的查找链
    except Exception as exc:                                      # noqa: BLE001
        print(f"[loader] mesh_catalog.json 不可用（{exc}），检视动画退回目录扫描", flush=True)
    _CATALOG_CLASSES = out
    return out


# 「物品」目录：收藏品/道具/医疗/食物/装备。这些目录里的动画就是游戏里拿在手上
# 把玩、拆开、点亮的那套；MilitaryProps/BattlefieldProps 里的是技能道具的**使用**
# 动画（投放/架设），不算检视，别混进来。
_ITEM_DIRS = ("/props/", "/collect/", "/med/", "/food/", "/equipments/")


def _anim_is_inspect(path: str, item_dir: str) -> bool:
    """这件物品的这条动画算不算「检视/把玩」。"""
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    low_dir = item_dir.lower()
    if any(k in low_dir for k in _ITEM_DIRS):
        return True
    if any(w in stem for w in _STRICT_WORDS):
        return True
    return False


def inspect_animations() -> Dict[str, List[str]]:
    """`{物品资产名: [动画虚拟路径, ...]}` —— 有检视/把玩动画的物品。

    该游戏的物品动画没有统一命名：收藏品放在 `ANI/`、`Ani/`、`Anim/`、
    `Animation/`、`Anims/`、`anmi/`（拼错的）、甚至 `Body/`、`Weapon/` 子目录里，
    名字前缀有 `Knife_Prop_View_` / `Prop_Collect_` / `Porps_` / `props_collect_` 等。

    所以这里不再靠文件名猜，而是：
    1. 从 `mesh_catalog.json` 拿所有 `AnimSequence`/`AnimMontage`；
    2. 往上最多 4 层找到「含 StaticMesh/SkeletalMesh 的物品目录」；
    3. 物品类目录（Props/Collect/Med/Food）全收，武器/载具/角色目录只收明确写了
       view/inspect/show… 且不含开火/换弹这类词的；
    4. 用该目录里的网格名当键（`props_collect_Echains_1320_1P` → 键 `props_collect_Echains_1320_1P`）。

    检视功能被关掉（`core.features.INSPECT_ENABLED = False`，用户要求「把检视全部禁用」）
    时直接返回空表，连 `mesh_catalog.json` 都不读，省掉启动时那 691 条的匹配。
    """
    global _INSPECT_MAP
    if _INSPECT_MAP is not None:
        return _INSPECT_MAP
    from .features import INSPECT_ENABLED
    if not INSPECT_ENABLED:
        _INSPECT_MAP = {}
        return _INSPECT_MAP
    classes = _catalog_classes()
    if not classes:
        _INSPECT_MAP = {}
        return _INSPECT_MAP
    mesh_by_dir: Dict[str, List[str]] = {}
    anims: List[str] = []
    for vpath, cls in classes.items():
        if cls in _MESH_CLASSES:
            mesh_by_dir.setdefault(_dir_of(vpath), []).append(vpath)
        elif cls in _ANIM_CLASSES:
            anims.append(vpath)

    item_anims: Dict[str, List[str]] = {}
    for apath in anims:
        folder = _dir_of(apath)
        for _ in range(5):
            if folder in mesh_by_dir:
                if _anim_is_inspect(apath, folder):
                    for mesh in mesh_by_dir[folder]:
                        stem = os.path.splitext(os.path.basename(mesh))[0]
                        item_anims.setdefault(stem, []).append(apath)
                break
            parent = _dir_of(folder)
            if parent == folder:
                break
            folder = parent

    # 同一个物品的动画按「loop / view / inspect」优先，短的在前
    def _rank(p: str) -> tuple:
        s = p.lower()
        return (0 if "loop" in s else 1, 0 if any(w in s for w in _INSPECT_WORDS) else 1, len(s), s)

    for key in item_anims:
        item_anims[key] = sorted(set(item_anims[key]), key=_rank)
    _INSPECT_MAP = item_anims
    print(f"[loader] 检视/把玩动画：{len(item_anims)} 个物品", flush=True)
    return _INSPECT_MAP


def _dir_of(vpath: str) -> str:
    p = vpath.replace("\\", "/")
    return p.rsplit("/", 1)[0] if "/" in p else ""


_INSPECT_CACHE: Optional[Dict[str, str]] = None


def inspect_anim_for(stem: str) -> Optional[str]:
    """这个资产有没有检视动画？有就返回其中一个动画的虚拟路径。

    动画名比模型名短一截（模型是 ``props_collect_Echains_1320_3P``，
    动画是 ``Knife_Prop_View_Echains_1320_1P``），所以拿模型名逐段去掉前缀去试，
    比「互相 contains」快，也不会误配到别的相似物品上。
    """
    global _INSPECT_CACHE
    if _INSPECT_CACHE is None:
        flat: Dict[str, str] = {}
        for key, paths in inspect_animations().items():
            low_key = key.lower()
            flat.setdefault(low_key, paths[0])
            # 同时登记「去掉 1P/3P/UI 后缀」的别名，卡片传进来的可能是任意变体
            for suf in ("_1p_hd", "_3p_hd", "_lay_hd", "_1p", "_3p", "_ui", "_hd",
                        "_lay", "_sk"):
                if low_key.endswith(suf):
                    flat.setdefault(low_key[: -len(suf)], paths[0])
                    break
        _INSPECT_CACHE = flat
    low = str(stem).lower()
    low = os.path.splitext(os.path.basename(low))[0]      # 允许直接传文件名
    hit = _INSPECT_CACHE.get(low)                          # 带变体后缀的先直接查
    if hit:
        return hit
    for suf in ("_1p_hd", "_3p_hd", "_lay_hd", "_1p", "_3p", "_ui", "_hd", "_lay",
                "_lod0", "_lod", "_sk", "_skeleton", "_preview", "_cutscene"):
        if low.endswith(suf):
            low = low[: -len(suf)]
            break
    parts = low.split("_")
    for i in range(len(parts)):
        hit = _INSPECT_CACHE.get("_".join(parts[i:]))
        if hit:
            return hit
    return _INSPECT_CACHE.get(low)


def list_models(prefix: str = "Models/", limit: int = 0, *, commercial: bool = True):
    """Virtual paths of loadable mesh assets, for the asset tree.

    `Models/` 是基础模型（枪/配件/道具/角色），`Commerical/` 是商城皮肤和展柜模型。
    两套目录布局不同，但都能渲染，所以一起收进来；关掉 `commercial` 可以只留
    `Models/`（老的调用方/测试想复现旧行为时用）。
    """
    out = []
    low_prefix = f"/content/{prefix.strip('/').lower()}/"
    for k in index():
        low = k.replace("\\", "/").lower()
        if not low.endswith(".uasset"):
            continue
        under_models = low_prefix in low
        under_commercial = commercial and any(m in low for m in _COMMERCIAL_MARKERS)
        if not (under_models or under_commercial):
            continue
        if under_commercial and not commercial_like_mesh(k):
            continue
        if any(d in low for d in _MESH_SKIP_DIRS):
            continue
        stem = low.rsplit("/", 1)[-1]
        if any(s in stem for s in _MESH_SKIP_SUFFIXES):
            continue
        out.append(k)
        if limit and len(out) >= limit:
            break
    return out


# --------------------------------------------------------------- 资产类名目录 --
# 由 tools/build_mesh_catalog.py 一次性扫描生成（62709 个 Models/ 资产，约 2 分钟）。
# 有了它，「模型库」只显示真正能渲染的 StaticMesh / SkeletalMesh，而不是把
# AnimSequence / PhysicsAsset / 蓝图一起列出来。
_MESH_CLASSES = ("StaticMesh", "SkeletalMesh")
_CATALOG: Optional[Dict[str, str]] = None
_CATALOG_PATH = os.path.join(WORK, "mesh_catalog.json")


def catalog() -> Dict[str, str]:
    """`{vpath: 主导出类名}`；文件不存在时返回空 dict（调用方退回按名字过滤）。"""
    global _CATALOG
    if _CATALOG is None:
        data: Dict[str, str] = {}
        # 打包进 _internal/dfdata 的那份优先，data/ 里放同名文件可以覆盖
        path = data_file("mesh_catalog.json")
        if path:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if path != os.path.join(WORK, "mesh_catalog.json"):
                    print(f"[loader] mesh_catalog fallback -> {path}", file=sys.stderr)
            except Exception as exc:                                 # noqa: BLE001
                print(f"[loader] mesh_catalog 读取失败（{exc}）", file=sys.stderr)
        if not data:
            print("[loader] mesh_catalog.json 不可用，检视动画退回目录扫描",
                  file=sys.stderr)
        _CATALOG = data
    return _CATALOG


def asset_class(vpath: str) -> Optional[str]:
    """主导出类名；目录里没有该资产时返回 None。"""
    return catalog().get(vpath)


def is_mesh(vpath: str) -> Optional[bool]:
    """True/False 表示目录里确定是/不是网格；None 表示目录里没收录（未知）。"""
    cls = catalog().get(vpath)
    if cls is None:
        return None
    return cls in _MESH_CLASSES


@lru_cache(maxsize=16384)
def header_is_mesh(vpath: str) -> bool:
    """目录外资产：读 uasset 头里的 export class 判断到底有没有网格。

    动画序列、图集、蓝图通知也带 `_1P/_3P` 尾巴，光看名字分不出来；这里只
    解析包头（不建网格），单条约 14ms，结果由 `core.meshcheck` 落库缓存。
    """
    try:
        from .uasset import Package
        package = Package(read_entry(vpath), path=vpath)
        return any(package.export_class(e) in _MESH_CLASSES
                   for e in package.exports)
    except Exception:                                            # noqa: BLE001
        return False
