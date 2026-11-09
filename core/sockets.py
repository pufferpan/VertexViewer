"""该游戏「改枪挂点」数据：WeaponPartsMeshSocketNameInfo + PartSocketsTable。

## 为什么需要它

`core/gunsmith.py` 以前假设「配件资产就在枪的局部坐标里做好，缩放 1 / 位移 0 直接叠」，
所以改枪台拼出来的枪配件全部错位。实际上该游戏的装配规则是**挂点式**的：

* 每个配件网格的原点就是它的挂点（枪托的 0 点在弹匣井后、握把的 0 点在顶部、
  枪管后端起于 0 附近……）；
* 主件（机匣）在自己的骨骼空间里定义了一堆挂点 socket（`Bar_point` / `Han_point` /
  `Sto_point` / `PisG_point` / `Mag_point` / `Sco_point` / `Rea_point` / `Mou_point` …），
  每个 socket 都带一组局部变换；
* 配件按 socket 的位置摆过去；枪口再挂到**枪管**的 `Muzzle_point` 上、前握把挂到
  **护木**的 `For_point` 上——所以这是一条父子链，不是平铺。

数据在 `Content/DataTables/WeaponPart/WeaponPartsMeshSocketNameInfo.uasset`
（20270 行，一行一个网格：`ItemId` + `SocketNames` + `SocketLocation` + `SocketRotation`），
`socket id -> socket 名` 的对照在 `PartSocketsTable.uasset`（80 行）。

## 单位与坐标

* `SocketLocation` 是 UE 厘米（x 右 / y 前 / z 上）；
* `SocketRotation` 是 FRotator(Pitch, Yaw, Roll)，单位度，绝大多数挂点是 0；
* 本模块对外一律返回 **loader 的 GL 米**（映射同 `core.types.ue_to_gl`：GL = (y, z, -x) * 0.01）。

## 缓存

整表解析一次约 3.5 秒，结果落 `%LOCALAPPDATA%/VertexViewer/weapon_sockets.json`，之后毫秒级加载。
"""
from __future__ import annotations

import json
import os
import struct
import threading
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import loader
from .uasset import Package

VP_SOCK = ("../../../DeltaForce/Content/DataTables/WeaponPart/"
           "WeaponPartsMeshSocketNameInfo.uasset")
VP_PSOCK = "../../../DeltaForce/Content/DataTables/WeaponPart/PartSocketsTable.uasset"

PREFIX = "../../../DeltaForce/Content/"
SCALE = 0.01
#: GL = P @ UE（与 core.types.ue_to_gl 的线性部分一致）
P_MAP = np.array([[0.0, 1.0, 0.0],
                  [0.0, 0.0, 1.0],
                  [-1.0, 0.0, 0.0]])

_LOCK = threading.RLock()
_STATE: Dict[str, object] = {"loaded": False, "sockets": {}, "items": {}, "sid": {},
                             "source": ""}

# --------------------------------------------------------------------------- #
# 极简 DataTable 解析（tag 布局实测见 docs/NOTES-23）
# --------------------------------------------------------------------------- #
_STRUCT = "StructProperty"
_BOOL = "BoolProperty"
_ENUMY = ("ByteProperty", "EnumProperty")
_ARRAYY = ("ArrayProperty", "SetProperty")
_MAPY = "MapProperty"


class _Rd:
    __slots__ = ("b", "o")

    def __init__(self, b: bytes, o: int = 0):
        self.b, self.o = b, o

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.b, self.o)[0]
        self.o += 4
        return v

    def u8(self) -> int:
        v = self.b[self.o]
        self.o += 1
        return v

    def skip(self, n: int) -> None:
        self.o += n

    def fname(self):
        i, num = struct.unpack_from("<ii", self.b, self.o)
        self.o += 8
        return i, num


def _name(names, i: int, num: int) -> str:
    s = names[i] if 0 <= i < len(names) else "<%d>" % i
    return s + ("_%d" % (num - 1) if num else "")


def _read_tag(r: _Rd, names) -> Tuple[str, str, int, int, int, int]:
    nm_i, nm_n = r.fname()
    ty_i, ty_n = r.fname()
    name = _name(names, nm_i, nm_n)
    typ = _name(names, ty_i, ty_n)
    size = r.i32()
    aidx = r.i32()
    if size < 0 or size > len(r.b):
        raise ValueError("bad size %r=%d" % (name, size))
    if typ == _STRUCT:
        r.skip(8 + 16)
    elif typ in _ENUMY or typ in _ARRAYY:
        r.skip(8)
    elif typ == _MAPY:
        r.skip(16)
    if typ == _BOOL:
        r.u8()
    if r.u8():
        r.skip(16)
    vstart = r.o
    r.skip(size)
    return name, typ, size, aidx, vstart, size


def _read_props(r: _Rd, names) -> List[tuple]:
    out: List[tuple] = []
    while r.o + 8 <= len(r.b):
        st = r.o
        i, num = r.fname()
        if _name(names, i, num) in ("None",) or _name(names, i, num).startswith("None_"):
            return out
        r.o = st
        out.append(_read_tag(r, names))
    return out


def _walk_rows(data: bytes, names) -> List[Tuple[str, List[tuple]]]:
    """DataTable 导出数据 -> [(行名, [(name,type,size,aidx,vstart,vlen)…])…]"""
    r = _Rd(data, 0)
    try:
        _read_props(r, names)               # 对象自身属性
        r.i32()
        n = r.i32()
    except Exception:                        # noqa: BLE001
        return []
    if not (0 <= n <= 500000):
        return []
    rows: List[Tuple[str, List[tuple]]] = []
    for _ in range(n):
        if r.o + 8 > len(data):
            break
        i, num = r.fname()
        try:
            props = _read_props(r, names)
        except Exception:                    # noqa: BLE001
            break
        rows.append((_name(names, i, num), props))
    return rows


def export_payload(vpath: str):
    """读取一个包唯一 export 的载荷（.uexp 切片）并解析名字表。

    注意 `serial_offset` 是「uasset+uexp 拼起来」的包内偏移，
    要减掉 `total_header_size` 才是 .uexp 里的位置。
    """
    ua = loader.read_entry(vpath)
    ue = loader.read_entry(vpath[:-7] + ".uexp")
    pkg = Package(ua, ue, None, path=vpath)
    exp = pkg.exports[0]
    start = int(exp.serial_offset) - int(pkg.total_header_size)
    if start < 0:                                   # monolithic：载荷还在 uasset 里
        start = int(exp.serial_offset)
        buf = ua
    else:
        buf = ue
    data = buf[start: start + int(exp.serial_size)]
    return data, pkg.names


def _export_rows(vpath: str):
    data, names = export_payload(vpath)
    return _walk_rows(data, names), data, names


def _find(props, key):
    for name, typ, size, aidx, vs, vl in props:
        if name == key:
            return typ, vs, vl
    return None, 0, 0


def _vec3_list(data: bytes, props, key) -> List[List[float]]:
    typ, vs, vl = _find(props, key)
    if typ is None:
        return []
    cnt = struct.unpack_from("<i", data, vs)[0]
    if vl != 53 + 12 * cnt:                  # 唯一的已知布局
        return []
    off = vs + 53
    return [[float(x) for x in struct.unpack_from("<3f", data, off + 12 * k)]
            for k in range(cnt)]


def _fname_list(data: bytes, props, key, names) -> List[str]:
    typ, vs, vl = _find(props, key)
    if typ is None:
        return []
    cnt = struct.unpack_from("<i", data, vs)[0]
    out = []
    for k in range(cnt):
        i, num = struct.unpack_from("<ii", data, vs + 4 + 8 * k)
        out.append(_name(names, i, num))
    return out


# --------------------------------------------------------------------------- #
# key 归一化
# --------------------------------------------------------------------------- #
def asset_key(vpath: str) -> str:
    """pak vpath -> 表里的包路径键（去 /Game/ 或 Content 前缀、去扩展名、小写）。"""
    p = vpath.replace("\\", "/")
    low = p.lower()
    if low.startswith(PREFIX.lower()):
        p = p[len(PREFIX):]
    elif low.startswith("/game/"):
        p = p[len("/game/"):]
    if "." in p.rsplit("/", 1)[-1]:
        p = p.rsplit(".", 1)[0]
    return p.strip("/").lower()


def cache_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "VertexViewer", "weapon_sockets.json")


# --------------------------------------------------------------------------- #
# 加载
# --------------------------------------------------------------------------- #
def load(force: bool = False) -> None:
    with _LOCK:
        if _STATE["loaded"] and not force:
            return
        path = cache_path()
        if os.path.isfile(path) and not force:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    blob = json.load(f)
                if blob.get("sockets"):
                    _adopt(blob)
                    return
            except Exception:                # noqa: BLE001
                pass
        _build(path)


def _adopt(blob: dict) -> None:
    _STATE["sockets"] = {k: (list(v[0]),
                             [np.asarray(x, dtype=np.float64) for x in v[1]],
                             [np.asarray(x, dtype=np.float64) for x in v[2]])
                         for k, v in (blob.get("sockets") or {}).items()}
    _STATE["items"] = {int(k): list(v) for k, v in (blob.get("items") or {}).items()}
    _STATE["sid"] = {int(k): v for k, v in (blob.get("sid") or {}).items()}
    _STATE["source"] = "cache"
    _STATE["loaded"] = True


def _build(path: str) -> None:
    rows, data, names = _export_rows(VP_SOCK)
    sockets: Dict[str, list] = {}
    items: Dict[int, List[str]] = {}
    for rn, props in rows:
        key = asset_key(rn.split(".")[0])
        typ, vs, _vl = _find(props, "ItemId")
        item = struct.unpack_from("<Q", data, vs)[0] if typ else 0
        sockets[key] = [_fname_list(data, props, "SocketNames", names),
                        _vec3_list(data, props, "SocketLocation"),
                        _vec3_list(data, props, "SocketRotation")]
        if item:
            items.setdefault(int(item), []).append(key)

    rows2, data2, names2 = _export_rows(VP_PSOCK)
    sid: Dict[int, str] = {}
    for rn, props in rows2:
        typ, vs, _vl = _find(props, "SocketId")
        if typ is None:
            continue
        sid_i = struct.unpack_from("<I", data2, vs)[0]
        typ2, vs2, _v2 = _find(props, "SocketName")
        if typ2 is None:
            continue
        nm = _name(names2, *struct.unpack_from("<ii", data2, vs2))
        sid[int(sid_i)] = nm

    _adopt({"sockets": sockets, "items": items, "sid": sid})
    _STATE["source"] = "pak"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"format": "cm + FRotator(Pitch,Yaw,Roll)deg",
                       "sockets": sockets,
                       "items": {str(k): v for k, v in items.items()},
                       "sid": {str(k): v for k, v in sid.items()}}, f)
    except Exception:                        # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
# 查询
# --------------------------------------------------------------------------- #
def sockets_of(vpath: str) -> Tuple[List[str], List[np.ndarray], List[np.ndarray]]:
    """该网格的 (socket 名, 位置 GL 米, FRotator 角度)。没有数据返回三个空表。"""
    load()
    got = _STATE["sockets"].get(asset_key(vpath))     # type: ignore[union-attr]
    if got is None:
        return [], [], []
    return got


def socket_names(vpath: str) -> List[str]:
    return sockets_of(vpath)[0]


def has_socket(vpath: str, name: str) -> bool:
    low = name.lower()
    return any(n.lower() == low for n in sockets_of(vpath)[0])


def socket_id_name(sid: int) -> str:
    load()
    return _STATE["sid"].get(int(sid), "")            # type: ignore[union-attr]


def item_meshes(item_id: int) -> List[str]:
    load()
    return list(_STATE["items"].get(int(item_id), []))  # type: ignore[union-attr]


def item_of_mesh(vpath: str) -> int:
    """反查：这个网格属于哪个 ItemId（找不到返回 0）。"""
    load()
    key = asset_key(vpath)
    items: Dict[int, List[str]] = _STATE["items"]       # type: ignore[assignment]
    if key in _MESH_ITEM:
        return int(_MESH_ITEM[key])
    for item, keys in items.items():
        if key in keys:
            _MESH_ITEM[key] = item
            return int(item)
    _MESH_ITEM[key] = 0
    return 0


_MESH_ITEM: Dict[str, int] = {}


def table_size() -> Tuple[int, int, int]:
    load()
    return (len(_STATE["sockets"]), len(_STATE["items"]),  # type: ignore[arg-type]
            len(_STATE["sid"]))


def socket_matrix(vpath: str, name: str) -> Optional[np.ndarray]:
    """某网格上挂点的 4x4 GL 变换；没有返回 None。"""
    names, locs, rots = sockets_of(vpath)
    low = [n.lower() for n in names]
    key = name.lower()
    if key not in low:
        return None
    k = low.index(key)
    if k >= len(locs) or k >= len(rots):
        return None
    return ue_matrix(locs[k], rots[k])


# --------------------------------------------------------------------------- #
# 变换
# --------------------------------------------------------------------------- #
def fr_matrix(rot_deg) -> np.ndarray:
    """FRotator(Pitch,Yaw,Roll) 角度 -> UE 3x3。"""
    p, y, r = np.radians(np.asarray(rot_deg, dtype=np.float64))
    cp, sp = np.cos(p), np.sin(p)
    cy, sy = np.cos(y), np.sin(y)
    cr, sr = np.cos(r), np.sin(r)
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cr, -sr], [0.0, sr, cr]])
    ry = np.array([[cp, 0.0, sp], [0.0, 1.0, 0.0], [-sp, 0.0, cp]])
    rz = np.array([[cy, -sy, 0.0], [sy, cy, 0.0], [0.0, 0.0, 1.0]])
    return rz @ ry @ rx


def ue_vec_to_gl(v) -> np.ndarray:
    """UE 厘米向量 -> GL 米（不含平移）。"""
    return P_MAP @ np.asarray(v, dtype=np.float64) * SCALE


def ue_matrix(loc_cm, rot_deg) -> np.ndarray:
    """socket 局部变换（UE cm + FRotator）-> 4x4 GL 米。"""
    m = np.eye(4)
    m[:3, :3] = P_MAP @ fr_matrix(rot_deg) @ P_MAP.T
    m[:3, 3] = ue_vec_to_gl(loc_cm)
    return m
