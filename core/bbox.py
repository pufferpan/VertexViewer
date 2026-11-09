"""网格包围盒缓存（GL 米，LOD0）。

改枪装配要用包围盒做两件事：
1. 没有挂点的件兜底定位；
2. 预设里那些「道具 ID 查不到网格」的默认件，在候选里挑一个尺寸对得上的。

读一次网格要几百毫秒，所以落盘缓存到 `%LOCALAPPDATA%/VertexViewer/bbox_cache.json`。
"""
from __future__ import annotations

import json
import os
from typing import Dict, Optional

import numpy as np

from core import loader
from core import sockets as _sockets

_CACHE: Dict[str, Optional[list]] = {}
_LOADED = False


def cache_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "VertexViewer", "bbox_cache.json")


def _load() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    try:
        with open(cache_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return
    for key, val in data.items():
        if isinstance(val, list) and len(val) == 2:
            _CACHE[key] = [list(map(float, val[0])), list(map(float, val[1]))]
        else:
            _CACHE[key] = None


def save() -> None:
    path = cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_CACHE, fh)


def box(vpath: str) -> Optional[np.ndarray]:
    """返回 `(2,3)` 的 [min, max]，单位 GL 米；解析不出来返回 None。"""
    _load()
    key = _sockets.asset_key(vpath)
    if key in _CACHE:
        got = _CACHE[key]
        return None if got is None else np.asarray(got, np.float32).reshape(2, 3)
    try:
        mesh = loader.load_mesh(vpath, lod=0)
    except Exception:                                  # noqa: BLE001
        mesh = None
    lods = getattr(mesh, "lods", None)
    pos = getattr(lods[0], "positions", None) if lods else None
    if pos is None or not len(pos):
        _CACHE[key] = None
        return None
    arr = np.asarray(pos, np.float32)
    lo = arr.min(axis=0).astype(float).tolist()
    hi = arr.max(axis=0).astype(float).tolist()
    _CACHE[key] = [lo, hi]
    return np.asarray([lo, hi], np.float32)
