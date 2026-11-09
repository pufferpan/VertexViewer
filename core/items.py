"""道具 ID → 部件网格：以游戏里 `CommonItemAssets_Weapon` 为准。

为什么需要这张表：`WeaponPartsMeshSocketNameInfo` 只收录「自己带挂点」的网格，
枪托、小握把这类没有挂点的件查不到，以前只能按名字猜（XM250 的枪托就是这么猜成
`Sto_A_XM250STD_090`，实际预设用的是 `Sto_A_UBR2_036`，整枪短了 8.8cm）。
这张表是游戏自己的道具资产表，`Item1PMeshPath`/`Item3PMeshPath`/`ItemUIMeshPath`
就是权威答案。
"""
from __future__ import annotations

import json
import os
import struct
import threading
from typing import Dict, List

from . import loader
from .sockets import _export_rows, _find, _name, asset_key

VP_ITEMS = ("../../../DeltaForce/Content/DataTables/CommonItemAsset/"
            "CommonItemAssets_Weapon.uasset")
PREFIX = "../../../DeltaForce/Content/"
GAME = "/Game/"

_LOCK = threading.RLock()
_STATE: Dict[str, object] = {"loaded": False, "meshes": {}, "source": ""}

_FIELDS = (("3P", "Item3PMeshPath"), ("1P", "Item1PMeshPath"),
           ("UI", "ItemUIMeshPath"), ("Dropped", "ItemDroppedMeshPath"))


def cache_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "VertexViewer", "item_meshes.json")


def _to_vpath(game_path: str) -> str:
    """`/Game/Models/...` -> `../../../DeltaForce/Content/Models/...`（去包内对象名）。"""
    p = game_path.strip()
    if not p:
        return ""
    low = p.lower()
    if low.startswith(GAME.lower()):
        p = p[len(GAME):]
    if "." in p.rsplit("/", 1)[-1]:
        p = p.rsplit(".", 1)[0]
    return PREFIX + p


def _adopt(blob: dict) -> None:
    _STATE["meshes"] = {int(k): dict(v) for k, v in (blob.get("meshes") or {}).items()}
    _STATE["source"] = "../item_meshes.json"
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
                if blob.get("meshes"):
                    _adopt(blob)
                    return
            except Exception:                       # noqa: BLE001
                pass
        _build(path)


def _build(path: str) -> None:
    rows, data, names = _export_rows(VP_ITEMS)
    meshes: Dict[int, Dict[str, str]] = {}
    for rn, props in rows:
        try:
            item = int(rn)
        except ValueError:
            continue
        slot: Dict[str, str] = {}
        for key, field in _FIELDS:
            typ, vs, _vl = _find(props, field)
            if typ is None:
                continue
            idx, num = struct.unpack_from("<ii", data, vs)
            got = _to_vpath(_name(names, idx, num))
            if got:
                slot[key] = got
        if slot:
            meshes[item] = slot
    _STATE["meshes"] = meshes
    _STATE["source"] = VP_ITEMS
    _STATE["loaded"] = True
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"format": "game-item-mesh", "meshes": {str(k): v for k, v in meshes.items()}},
                      fh)
    except Exception:                               # noqa: BLE001
        pass


def mesh_of(item_id: int, which: str = "3P") -> str:
    """道具 ID 的部件网格 vpath（找不到返回空串）。"""
    load()
    slot = _STATE["meshes"].get(int(item_id or 0))   # type: ignore[union-attr]
    if not slot:
        return ""
    return str(slot.get(which) or slot.get("3P") or "")


def exists(vpath: str) -> bool:
    """该 vpath 是否真在包里（大小写不敏感）。"""
    if not vpath:
        return False
    key = asset_key(vpath)
    for vp in loader.index():
        if asset_key(vp) == key and vp.lower().endswith(".uasset"):
            return True
    return False


def resolve(item_id: int, which: str = "3P") -> str:
    """道具 ID -> 包里真实存在的 vpath（表里的路径大小写可能与包里不同）。"""
    got = mesh_of(item_id, which)
    if not got:
        return ""
    key = asset_key(got)
    for vp in loader.index():
        if vp.lower().endswith(".uasset") and asset_key(vp) == key:
            return vp
    return ""


def clear_cache() -> None:
    with _LOCK:
        _STATE["loaded"] = False
        _STATE["meshes"] = {}
