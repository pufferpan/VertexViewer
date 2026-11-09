# -*- coding: utf-8 -*-
"""条目到底有没有网格：读 uasset 头里的 export class，结果落 SQLite 缓存。

`mesh_catalog.json` 只覆盖 Models/ 的一小撮资产，Commerical/ 的皮肤、新版本
加的资产都不在里面；只靠目录判断会把「没有网格的空壳」（动画序列、图集、
蓝图通知）也列进模型库。这里按 asset 头里的类名确认一遍，并按 pak 集合缓存，
换游戏目录/装新包时自动失效。
"""
from __future__ import annotations

import os
import sqlite3
import threading
from functools import lru_cache
from typing import Callable, Dict, Iterable, List, Optional

_MESH_CLASSES = ("StaticMesh", "SkeletalMesh")
_TABLE = "CREATE TABLE IF NOT EXISTS meshcheck (vpath TEXT PRIMARY KEY, ok INTEGER NOT NULL)"
_LOCK = threading.Lock()
_CACHE: Dict[str, bool] = {}
_LOADED = False
_STAMP = ""


def _db_path() -> str:
    from core import indexdb
    return indexdb.db_path()


def _stamp() -> str:
    """跟着游戏目录走：pak 集合变了，旧的网格判定就不可信。"""
    try:
        from core import loader
        return loader._index_stamp() or ""
    except Exception:                                            # noqa: BLE001
        return ""


def _connect() -> Optional[sqlite3.Connection]:
    path = _db_path()
    if not path or not os.path.isfile(path):
        return None
    try:
        conn = sqlite3.connect(path, timeout=15)
        conn.execute(_TABLE)
        conn.execute("CREATE TABLE IF NOT EXISTS meshcheck_meta (key TEXT PRIMARY KEY, value TEXT)")
        return conn
    except Exception:                                            # noqa: BLE001
        return None


def _load() -> None:
    global _LOADED
    if _LOADED:
        return
    with _LOCK:
        if _LOADED:
            return
        _LOADED = True
        conn = _connect()
        if conn is None:
            return
        try:
            row = conn.execute("SELECT value FROM meshcheck_meta WHERE key='stamp'").fetchone()
            saved = row[0] if row else ""
            if saved != _stamp():
                conn.execute("DELETE FROM meshcheck")
                conn.execute("INSERT OR REPLACE INTO meshcheck_meta VALUES ('stamp', ?)",
                             (_stamp(),))
                conn.commit()
                return
            for vpath, ok in conn.execute("SELECT vpath, ok FROM meshcheck"):
                _CACHE[vpath] = bool(ok)
        except Exception:                                        # noqa: BLE001
            pass
        finally:
            conn.close()


def status(vpath: str) -> Optional[bool]:
    """True=确定有网格，False=确定没有，None=还没判过。"""
    _load()
    return _CACHE.get(vpath)


def header_is_mesh(vpath: str) -> bool:
    from core import loader
    return loader.header_is_mesh(vpath)


def verify_many(paths: Iterable[str], *, workers: int = 10,
                progress: Optional[Callable[[int, int], None]] = None,
                cancel: Optional[Callable[[], bool]] = None) -> int:
    """批量判定，结果写进内存 + SQLite；返回这次真正去读包的数量。"""
    _load()
    todo = [p for p in dict.fromkeys(paths) if p not in _CACHE]
    if not todo:
        return 0
    from concurrent.futures import ThreadPoolExecutor
    done = 0
    batch: List[tuple] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for path, ok in zip(todo, pool.map(header_is_mesh, todo)):
            _CACHE[path] = bool(ok)
            batch.append((path, 1 if ok else 0))
            done += 1
            if progress and (done % 64 == 0 or done == len(todo)):
                progress(done, len(todo))
            if cancel and cancel():
                break
    if batch:
        conn = _connect()
        if conn is not None:
            try:
                conn.executemany("INSERT OR REPLACE INTO meshcheck VALUES (?, ?)", batch)
                conn.commit()
            except Exception:                                    # noqa: BLE001
                pass
            finally:
                conn.close()
    return done


def clear() -> None:
    global _CACHE, _LOADED
    _CACHE = {}
    _LOADED = False
    lru_cache = getattr(header_is_mesh, "cache_clear", None)
    if lru_cache:
        lru_cache()
