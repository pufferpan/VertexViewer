"""该游戏的官方装配预设：`GunDescTable` + `GunPresetBoundsTable`。

## 这两张表是什么

* `DataTables/WeaponPart/GunDescTable.uasset` —— **游戏自己的装配树**，46694 行，
  3991 个 `DesId`。每行一个节点：
  `DesKey | DesId | Index | ItemId | GUID | ParentIndex | ParentSocketId | SocketId |
   Child | NodeType | …`。`ParentIndex` 指向父节点的 `Index`，
  `ParentSocketId` 是「这件插在父件的哪个 socket 上（SocketId 对应
  PartSocketsTable）」。
* `DataTables/WeaponPart/GunPresetBoundsTable.uasset` —— 4053 个官方预设的
  `FBoxSphereBounds`（UE 厘米），用来给界面做取景。**它可以拿来当标定的标准答案**：
  用挂点拼出来的包围盒必须和它一致。

## 用途

`gunsmith.official_loadout()` 靠它给出「这把枪在游戏里默认装哪几件」，
`tools/calibrate_parts.py` 靠它标定伸缩托的默认伸展量。

## 缓存

冷解析约 10 秒，结果落 `%LOCALAPPDATA%/VertexViewer/weapon_presets.json`。
"""
from __future__ import annotations

import json
import os
import struct
import threading
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import loader
from .sockets import _Rd, _export_rows, _find, _name, _read_tag, asset_key

DT = "../../../DeltaForce/Content/DataTables/WeaponPart/"
VP_DESC = DT + "GunDescTable.uasset"
VP_BOUNDS = DT + "GunPresetBoundsTable.uasset"

_LOCK = threading.RLock()
_STATE: Dict[str, object] = {"loaded": False, "nodes": {}, "bounds": {}, "vpaths": {},
                             "roots": {}, "source": ""}


def cache_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "VertexViewer", "weapon_presets.json")


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def _u64(data: bytes, props, key) -> int:
    typ, vs, _vl = _find(props, key)
    return struct.unpack_from("<Q", data, vs)[0] if typ else 0


def _i16(data: bytes, props, key) -> int:
    typ, vs, _vl = _find(props, key)
    return struct.unpack_from("<h", data, vs)[0] if typ else 0


def _u32(data: bytes, props, key) -> int:
    typ, vs, _vl = _find(props, key)
    return struct.unpack_from("<I", data, vs)[0] if typ else 0


def _box(data: bytes, names, props, key) -> Optional[Tuple[List[float], List[float]]]:
    """`Bounds: FBoxSphereBounds` → (Origin, BoxExtent)，UE 厘米。"""
    typ, vs, _vl = _find(props, key)
    if typ is None:
        return None
    r = _Rd(data, vs)
    got = []
    try:
        for _ in range(2):                       # Origin / BoxExtent
            _nm, _t, _s, _a, vstart, _vlen = _read_tag(r, names)
            got.append([float(v) for v in struct.unpack_from("<3f", data, vstart)])
    except Exception:                            # noqa: BLE001
        return None
    if len(got) != 2:
        return None
    return got[0], got[1]


def _build_vpaths() -> Dict[str, str]:
    """小写模型键 → 真实 vpath（挂点表里的键是全小写的）。"""
    out: Dict[str, str] = {}
    for vp in loader.index():
        low = vp.lower()
        if "models/weapons/" in low and low.endswith(".uasset"):
            out[asset_key(vp)] = vp
    return out


def _build(path: str) -> None:
    rows, data, names = _export_rows(VP_DESC)
    nodes: Dict[int, List[list]] = {}
    for _rn, props in rows:
        des = _u64(data, props, "DesId")
        if not des:
            continue
        nodes.setdefault(int(des), []).append([
            _i16(data, props, "Index"),
            _i16(data, props, "ParentIndex"),
            _u64(data, props, "ItemId"),
            _u32(data, props, "ParentSocketId"),
        ])
    rows2, data2, names2 = _export_rows(VP_BOUNDS)
    bounds: Dict[int, List[float]] = {}
    for rn, props in rows2:
        try:
            des = int(rn)
        except ValueError:
            continue
        box = _box(data2, names2, props, "Bounds")
        if box is None:
            continue
        bounds[des] = box[0] + box[1]
    vpaths = _build_vpaths()
    roots: Dict[int, List[int]] = {}
    for des, items in nodes.items():
        root_items = [it for idx, pidx, it, _s in items if pidx in (0, None) and it]
        for it in set(root_items):
            roots.setdefault(int(it), []).append(int(des))
    _adopt({"nodes": {str(k): v for k, v in nodes.items()},
           "bounds": {str(k): v for k, v in bounds.items()},
           "vpaths": vpaths, "roots": roots})
    _STATE["source"] = "pak"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"format": "ue-cm",
                       "nodes": _STATE["nodes"], "bounds": _STATE["bounds"],
                       "roots": _STATE["roots"], "vpaths": vpaths}, fh)
    except Exception:                            # noqa: BLE001
        pass


def _adopt(blob: dict) -> None:
    _STATE["nodes"] = {int(k): [list(map(int, n)) for n in v]
                       for k, v in (blob.get("nodes") or {}).items()}
    _STATE["bounds"] = {int(k): list(map(float, v))
                        for k, v in (blob.get("bounds") or {}).items()}
    _STATE["vpaths"] = dict(blob.get("vpaths") or {})
    _STATE["roots"] = {int(k): list(map(int, v))
                       for k, v in (blob.get("roots") or {}).items()}
    _STATE["loaded"] = True


def load(force: bool = False) -> None:
    with _LOCK:
        if _STATE["loaded"] and not force:
            return
        path = cache_path()
        if os.path.isfile(path) and not force:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    blob = json.load(fh)
                if blob.get("nodes"):
                    _adopt(blob)
                    return
            except Exception:                    # noqa: BLE001
                pass
        _build(path)


# --------------------------------------------------------------------------- #
# 查询
# --------------------------------------------------------------------------- #
def vpath_of(mesh_key: str) -> str:
    """挂点表里的模型键 → 真实 pak vpath（找不到返回空串）。"""
    load()
    key = asset_key(mesh_key)
    table: Dict[str, str] = _STATE["vpaths"]           # type: ignore[assignment]
    got = table.get(key)
    if got:
        return got
    got = table.get(key + "_3p") or table.get(key + "_1p")
    if got:
        return got
    for k, vp in table.items():                        # 慢路径：前缀补全
        if k.rstrip("_3p").startswith(key):
            return vp
    return ""


def nodes_of(desid: int) -> List[list]:
    load()
    return [list(n) for n in _STATE["nodes"].get(int(desid), [])]   # type: ignore[union-attr]


def bounds_of(desid: int) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """官方包围盒 (中心, 半长)，UE 厘米。"""
    load()
    raw = _STATE["bounds"].get(int(desid))             # type: ignore[union-attr]
    if not raw:
        return None
    arr = np.asarray(raw, np.float64)
    return arr[:3], arr[3:6]


def presets_of_item(item_id: int) -> List[int]:
    load()
    return list(_STATE["roots"].get(int(item_id), []))  # type: ignore[union-attr]


def all_desids() -> List[int]:
    load()
    return sorted(_STATE["nodes"].keys())               # type: ignore[union-attr]


def dedup(nodes: Sequence[Sequence[int]]) -> List[list]:
    """同一棵树里机匣会按「父件声明了几个 socket」重复出现，按 Index 去重。

    保留那条带 ParentIndex（非 0）的记录 —— 它才说明这件挂在谁身上。
    """
    uniq: Dict[int, list] = {}
    for idx, pidx, item, psock in nodes:
        cur = uniq.get(idx)
        if cur is None:
            uniq[idx] = [idx, pidx, item, psock]
        elif cur[1] in (0, None) and pidx not in (0, None):
            uniq[idx] = [idx, pidx, item, psock]
    return list(uniq.values())


def size() -> Tuple[int, int]:
    load()
    return (len(_STATE["nodes"]), len(_STATE["bounds"]))  # type: ignore[arg-type]
