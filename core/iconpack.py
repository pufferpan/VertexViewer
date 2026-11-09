"""随包的 UI 图标库（`icons.db`，见 tools/build_iconpack.py）。

游戏装在别人电脑上时没有 `I:\\Game\\UIIcon` 这一坨导出的图标，
所以构建时把图标缩成 92px 塞进 SQLite 跟着安装包走：卡片缩略图不再靠
「1P / 3P / LAY」占位块，一眼就能认出来是什么东西。

查找顺序：键 = 资产名（去 Icon_ 前缀）或物品 ID，两种都试。
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Optional

from . import loader

_db_path: Optional[str] = None
_conn: Optional[sqlite3.Connection] = None
_ready = False
_cache: dict = {}
_SKIP_CACHE = 4096


def pack_path() -> Optional[str]:
    """图标库文件路径（打包版在 _internal/dfdata/，源码在 work/）。"""
    global _db_path
    if _db_path is not None:
        return _db_path or None
    for cand in (loader.data_file("icons.db"),):
        if cand and os.path.isfile(cand):
            _db_path = cand
            return cand
    _db_path = ""
    return None


def _connect() -> Optional[sqlite3.Connection]:
    global _conn, _ready
    if _ready:
        return _conn
    path = pack_path()
    if not path:
        _ready = True
        return None
    try:
        _conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3.0)
        _conn.execute("SELECT 1 FROM icons LIMIT 1")
    except Exception:                                          # noqa: BLE001
        _conn = None
    _ready = True
    return _conn


def count() -> int:
    conn = _connect()
    if conn is None:
        return 0
    try:
        row = conn.execute("SELECT v FROM meta WHERE k='count'").fetchone()
        return int(row[0]) if row else 0
    except Exception:                                          # noqa: BLE001
        return 0


def keys_for(vpath: str) -> list:
    """资产路径 -> 可能的键（资产名 / 去变体后缀 / 物品 ID）。"""
    base = os.path.basename(vpath or "").split(".")[0]
    out = []
    low = base.lower()
    for suf in ("_1p_hd", "_3p_hd", "_1p", "_3p", "_ui", "_hd", "_lay", "_sk"):
        if low.endswith(suf):
            out.append(low[: -len(suf)])
            break
    out.append(low)
    # 图标库构建时也登记了「下划线前后的 ID」，这里照同样规则补一遍
    try:
        for part in re.split(r"[_\s]+", low):
            if part and part not in out:
                out.append(part)
    except Exception:                                          # noqa: BLE001
        pass
    return [k for k in dict.fromkeys(out) if k]


def icon_bytes(vpath: str) -> Optional[bytes]:
    """返回该资产的 PNG 字节（没有就是 None）。"""
    if not vpath:
        return None
    if vpath in _cache:
        return _cache[vpath]
    conn = _connect()
    blob = None
    if conn is not None:
        for key in keys_for(vpath):
            try:
                row = conn.execute("SELECT png FROM icons WHERE key=?", (key,)).fetchone()
            except Exception:                                  # noqa: BLE001
                break
            if row:
                blob = row[0]
                break
    if len(_cache) > _SKIP_CACHE:
        _cache.clear()
    _cache[vpath] = blob
    return blob
