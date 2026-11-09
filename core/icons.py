"""物品小图标（游戏客户端里导出的 UIIcon 目录）。

目录形如 ``I:\\Game\\UIIcon``，里面两种命名：

* ``Icon_M_Head_Head_Helmet_HAAVK_094.png``  —— 直接就是资产名（去掉 ``Icon_`` 前缀、去掉扩展名）
* ``Icon_11010001003.png`` / ``Icon21020200001.png`` —— 物品数值 ID

所以这里索引两份字典：``by_asset``（``m_head_head_helmet_haavk_094`` → 路径）和
``by_id``（``11010001003`` → 路径）。解析模型时先按资产名查，再按去后缀的变体查。
"""

from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional, Tuple

ICON_ENV = "VERTEXVIEWER_ICONS"
DEFAULT_DIRS: Tuple[str, ...] = (
    r"I:\Game\UIIcon",
    r"G:\Game\UIIcon",
    r"D:\Game\UIIcon",
    r"E:\Game\UIIcon",
)
_SUFFIXES = ("_1p_hd", "_3p_hd", "_1p", "_3p", "_ui", "_hd", "_sk", "_lod0", "_lod", "_skeleton")

_by_asset: Dict[str, str] = {}
_by_id: Dict[str, str] = {}
_dir: Optional[str] = None
_loaded = False


def icon_dir() -> Optional[str]:
    """返回实际使用的图标目录（找不到就是 None）。"""
    global _dir
    if _dir is not None:
        return _dir or None
    env = os.environ.get(ICON_ENV, "").strip()
    candidates: List[str] = ([env] if env else []) + list(DEFAULT_DIRS)
    for path in candidates:
        if path and os.path.isdir(path):
            _dir = path
            return path
    _dir = ""
    return None


def _strip_icon(stem: str) -> str:
    low = stem.lower()
    if low.startswith("icon_"):
        low = low[5:]
    elif low.startswith("icon"):
        low = low[4:]
    return low


def load(force: bool = False) -> int:
    """扫目录建索引，返回条目数；重复调用走缓存。"""
    global _loaded
    if _loaded and not force:
        return len(_by_asset) + len(_by_id)
    _by_asset.clear()
    _by_id.clear()
    root = icon_dir()
    _loaded = True
    if not root:
        return 0
    for base, _dirs, files in os.walk(root):
        for name in files:
            if not name.lower().endswith(".png"):
                continue
            stem = name[:-4]
            key = _strip_icon(stem)
            full = os.path.join(base, name)
            if key.isdigit():
                _by_id.setdefault(key, full)
            else:
                _by_asset.setdefault(key, full)
                _by_asset.setdefault(key.lstrip("icon_"), full)
    return len(_by_asset) + len(_by_id)


def _variants(stem: str) -> Iterable[str]:
    low = stem.lower()
    yield low
    for suf in _SUFFIXES:
        if low.endswith(suf):
            low = low[: -len(suf)]
            yield low
    if low.startswith("m_") or low.startswith("sm_"):
        yield low.split("_", 1)[-1]


def icon_for(vpath: str) -> Optional[str]:
    """按资产路径找图标文件，找不到返回 None。"""
    if not vpath:
        return None
    load()
    stem = os.path.splitext(os.path.basename(str(vpath).replace("\\", "/")))[0]
    for cand in _variants(stem):
        hit = _by_asset.get(cand)
        if hit:
            return hit
    return None


def icon_for_id(item_id) -> Optional[str]:
    load()
    return _by_id.get(str(item_id).strip())


def stats() -> Dict[str, object]:
    load()
    return {"dir": icon_dir(), "assets": len(_by_asset), "ids": len(_by_id)}
