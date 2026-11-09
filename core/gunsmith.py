"""改枪台（gunsmith）：把武器主件和配件拼成一把枪。

**挂点数据是有的**，就在游戏包里，链路如下（全部由 `core.sockets` 解出来）：

1. `DataTables/WeaponPart/WeaponPartsMeshSocketNameInfo` —— 每个武器网格
   （20270 个）挂了哪些 socket、每个 socket 的**局部位置**（UE 厘米）和旋转
   （FRotator 角度）。机匣上就是 `Bar_point` / `Han_point` / `Sto_point` /
   `PisG_point` / `Mag_point` / `Sco_point` / `Muzzle_point` … 那套。
2. `DataTables/WeaponPart/PartSocketsTable` —— socket 名字 ↔ 配件类型的对照表
   （SocketId → SocketName → EAdapterItemType）。
3. `DataTables/WeaponPart/GunDescTable` —— 游戏自己的装配树：每个节点写清
   「这件装在父件的哪个 socket 上」。

所以装配就是 UE 的 socket 挂接：**父件世界变换 × 挂点变换**。整套数学用
`GunPresetBoundsTable`（4053 个官方预设的包围盒）验证过：40 个预设里 26 个
误差 < 1cm，其余偏差全部集中在「伸缩托」这类需要额外伸展的件上（见
`core/part_offsets.json`，用同一张包围盒表标定出来的）。

坐标是渲染器的 GL 约定（见 core.types）：x = 长度（UE +Y 向前）, y = 上
（UE +Z）, z = -UE X。挂点表的单位是厘米，网格是米，所以挂点要 ×0.01。
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from dataclasses import dataclass, field, replace
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from core import items as _items
from core import sockets as _sockets
from core.types import (Material, Mesh, MeshLOD, ModelBundle, Section, Texture)

# --------------------------------------------------------------------------- #
# 槽位定义
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Slot:
    key: str
    label: str
    words: Tuple[str, ...] = ()
    size: float = 0.15          # 目标尺寸占主件长度的比例
    anchor: str = "center"      # front / back / top / bottom / center


SLOTS: Tuple[Slot, ...] = (
    Slot("receiver", "机匣", ("/rec_", "/rec", "receiver", "机匣", "机框"), 0.55, "center"),
    Slot("handguard", "护木", ("/han_", "_han_", "handguard", "护木", "护盖"), 0.38, "center_front"),
    Slot("barrel", "枪管", ("/bar_", "_bar_", "barrel", "枪管"), 0.40, "center_front"),
    Slot("muzzle", "枪口", ("/muz_", "_muz_", "muzzle", "suppress", "silenc",
                            "brake", "消焰", "消音", "补偿", "枪口"), 0.12, "front"),
    Slot("optic", "瞄具", ("/acl_", "_acl_", "/sco_", "_sco_", "optic", "scope", "sight", "reddot",
                           "holo", "瞄准", "瞄具", "倍镜", "红点", "全息"), 0.16, "top"),
    Slot("grip", "握把", ("/pisg_", "_pisg_", "/frog_", "grip", "foregrip",
                          "握把", "把手"), 0.16, "bottom_back"),
    Slot("mag", "弹匣", ("/mag_", "_mag_", "magazine", "弹匣", "弹夹", "弹鼓"), 0.20, "bottom_mid"),
    Slot("stock", "枪托", ("/sto_", "_sto_", "stock", "butt", "brace", "枪托", "托腮"), 0.26, "back"),
    Slot("tactical", "战术设备", ("/dev_", "_dev_", "/att_", "tactical", "laser", "flashlight", "战术", "激光", "镭指", "雷指", "手电"), 0.09, "bottom_front"),
    Slot("other", "其他", (), 0.15, "center"),
)

SLOT_BY_KEY: Dict[str, Slot] = {s.key: s for s in SLOTS}


# --------------------------------------------------------------------------- #
# 挂点（socket）——数值来自游戏的 WeaponPartsMeshSocketNameInfo / PartSocketsTable
# --------------------------------------------------------------------------- #
# 资产名前缀 → 挂接族（族决定「装在父件的哪个 socket 上」）
FAMILY_OF_PREFIX: Dict[str, str] = {
    "Rec": "receiver", "Bar": "barrel", "Han": "handguard", "Muz": "muzzle",
    "Mag": "mag", "Sto": "stock", "PisG": "grip", "FroG": "foregrip",
    "Acl": "optic", "Sco": "optic", "Bip": "bipod", "Att": "tactical", "Dev": "tactical",
}

# 每个挂接族的候选 socket 名（按优先级排，取父件上第一个存在的）。
# 名字全部来自 PartSocketsTable：Bar_point/Han_point/Sto_point/PisG_point/Mag_point/
# Muzzle_point/For_point/FSig_point/Rea_point/Sco_point/Mou_point/Common*_point …
SOCKET_CANDIDATES: Dict[str, Tuple[str, ...]] = {
    "barrel": ("Bar_point", "Bar2_point", "BarKit_point"),
    "handguard": ("Han_point", "Han2_point", "Han_point_alt", "HanKit_point", "HanU_point"),
    "muzzle": ("Muzzle_point", "Muzzle2_point"),
    "stock": ("Sto_point", "Sto2_point", "StoKit_point", "StockP_point", "StockC_point",
              "StoCaseFixed_point", "StoCase_point", "M16Sto_point"),
    "grip": ("PisG_point", "PisG2_point", "GripBass_point"),
    "foregrip": ("For_point", "FSig_point"),
    "mag": ("Mag_point", "Mag1_point", "Mag2_point", "MagBass_point"),
    "optic": ("Sco_point", "Rea_point", "sco_secondary_point", "Sco2_point", "ScoU_point",
              "Mou_point", "ScoB_point", "Sco1P29_point", "ScoS1_point", "ScoS2_point",
              "ScoS3_point", "Riser_point"),
    "bipod": ("Bip_point", "BarBip_point"),
    "tactical": ("Common_point", "CommonU_point", "CommonD_point", "CommonL_point",
                 "CommonR_point", "CommonF_point", "CommonB_point", "RailCU_point",
                 "RailCD_point", "RailCL_point", "RailCR_point", "Upgrade_point"),
    "receiver": (),
}

# 这些族不挂在机匣上，而是挂在别的配件上（枪口挂枪管、前握把挂护木）。
PARENT_FAMILY: Dict[str, Tuple[str, ...]] = {
    "muzzle": ("barrel",),
    "foregrip": ("handguard", "barrel"),
    "bipod": ("barrel", "handguard"),
    "tactical": ("handguard", "barrel"),
}


def asset_prefix(vpath: str) -> str:
    """资产名第一段前缀：`Bar_S-370_M4A1-Std_001_3P` → `Bar`。"""
    stem = os.path.splitext(os.path.basename(vpath or ""))[0]
    return stem.split("_", 1)[0]


def mount_family(vpath: str, slot: str = "") -> str:
    """配件挂在哪个族上：先看资产名前缀，退回槽位。"""
    fam = FAMILY_OF_PREFIX.get(asset_prefix(vpath))
    if fam:
        return fam
    if slot in SOCKET_CANDIDATES:
        return slot
    return "other"


def socket_candidates(family: str) -> Tuple[str, ...]:
    return SOCKET_CANDIDATES.get(family, ("Common_point", "Upgrade_point"))


SOCKET_FAMILY: Dict[str, str] = {}
for _fam, _names in SOCKET_CANDIDATES.items():
    for _nm in _names:
        SOCKET_FAMILY.setdefault(_nm.lower(), _fam)
# 挂点表里还散着一堆没列进候选表的名字，按前缀归类，用于「凭道具 ID 找不到网格」时兜底
for _extra, _fam in (("416cpart_point", "stock"), ("stockp_point", "stock"),
                     ("hanguard_point", "handguard"), ("bip_point", "bipod"),
                     ("drop_point", "other"), ("ammo_point", "mag"),
                     ("s_root", "receiver"), ("handik", "other")):
    SOCKET_FAMILY.setdefault(_extra, _fam)


def find_socket(vpath: str, names: Sequence[str],
                prefer: str = "") -> Optional[Tuple[str, str, np.ndarray]]:
    """在 `vpath` 这个网格上找一个挂点，返回 (socket 名, 网格键, 4x4 GL 矩阵)。

    `prefer` 是用户/方案里显式指定的 socket 名，优先用它。
    """
    if not vpath:
        return None
    try:
        have = _sockets.socket_names(vpath)
    except Exception:                                        # noqa: BLE001
        return None
    if not have:
        return None
    order = list(names or ())
    if prefer:
        order = [prefer] + [n for n in order if n != prefer]
    for name in order:
        if not name:
            continue
        if name in have:
            mat = _sockets.socket_matrix(vpath, name)
            if mat is not None:
                return name, _sockets.asset_key(vpath), mat
        # 带序号的变体：`416cPart_point` / `416cPart_point_2` / `StockC_point_50`
        hits = [h for h in have if h.lower().startswith(name.lower() + "_")]
        if hits:
            mat = _sockets.socket_matrix(vpath, hits[0])
            if mat is not None:
                return hits[0], _sockets.asset_key(vpath), mat
    return None


_PART_OFFSETS: Dict[str, object] = {"rows": None}


def part_offsets() -> Dict[str, np.ndarray]:
    """伸缩托之类的「默认伸展量」（GL 米），用官方预设包围盒标定出来的。

    标定脚本：`tools/calibrate_parts.py` → `core/part_offsets.json`。
    50 个枪托里 42 个恒为 0（直接用 socket 就对），只有少数伸缩托需要额外后移。
    """
    if _PART_OFFSETS.get("rows") is not None:
        return _PART_OFFSETS["rows"]                    # type: ignore[return-value]
    rows: Dict[str, np.ndarray] = {}
    # 打包成 exe 后 __file__ 指向 _MEIPASS 里的 core/，数据文件由 spec 一起放进
    # `_internal/core/`；开发态就是源码目录，两条路径都能命中。
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(here, "part_offsets.json")]
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        cands.append(os.path.join(meipass, "core", "part_offsets.json"))
    for path in cands:
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            continue
        for key, vec in (raw.get("offsets") or {}).items():
            arr = np.asarray(vec, np.float32)
            if arr.shape == (3,):
                rows[str(key).lower()] = arr
        break
    _PART_OFFSETS["rows"] = rows
    return rows


def part_offset(vpath: str) -> np.ndarray:
    """某个网格的默认额外位移（GL 米）。"""
    try:
        key = _sockets.asset_key(vpath)
    except Exception:                                        # noqa: BLE001
        return np.zeros(3, np.float32)
    offsets = part_offsets()
    exact = offsets.get(key)
    if exact is not None:
        return exact
    # Skin meshes keep the complete official component number, but have a
    # different directory/suffix. Reuse its original extension calibration;
    # never infer one from a shared gun family or slot alone.
    stem = os.path.basename(key)
    identity = re.match(r"^(.+?_\d{3})(?:_|$)", stem)
    if identity:
        original = identity.group(1)
        matches = [vec for path, vec in offsets.items()
                   if re.sub(r"_(?:1p|3p)$", "", os.path.basename(path)) == original]
        if matches and all(np.array_equal(matches[0], vec) for vec in matches[1:]):
            return matches[0]
    return np.zeros(3, np.float32)



def guess_slot(name: str) -> str:
    """按资产名猜槽位；猜不出来归到 other。"""
    low = (name or "").lower()
    for slot in SLOTS:
        for word in slot.words:
            if word in low:
                return slot.key
    return "other"


# --------------------------------------------------------------------------- #
# 一个配件的摆法
# --------------------------------------------------------------------------- #
@dataclass
class PartSpec:
    vpath: str = ""
    slot: str = "other"
    name: str = ""
    offset: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])   # 米，挂点之上
    rot: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])      # 度，yaw/pitch/roll
    scale: float = 1.0                                                     # 缩放倍率（默认 1 = 原尺寸对齐）
    socket: str = ""                                                       # 父件上的挂点名（空=自动挑）
    auto_scale: Optional[float] = None                                     # 自动缩放算出的 k
    anchored: bool = False                                                 # 点过「自动对齐」才按锚点摆
    slot_fit: bool = False                                                 # 官方装配（保留兼容）
    skin_source: str = ""                                                  # 换肤前部件；无对应皮肤件时原样保留
    #: 官方预设里这件挂在**哪一件**上（父节点道具 ID）。同名的 Common_point 在护木
    #: 和机匣上都有，光靠族名猜父件会把导轨附件挂到另一条导轨上。
    parent_item: int = 0
    #: 官方预设里的挂点 ID（PartSocketsTable），仅供排查/兼容，实际用 socket 名。
    parent_socket_id: int = 0

    def to_dict(self) -> dict:
        return {
            "vpath": self.vpath, "slot": self.slot, "name": self.name,
            "offset": [round(float(v), 5) for v in self.offset],
            "rot": [round(float(v), 3) for v in self.rot],
            "scale": round(float(self.scale), 4),
            "socket": self.socket,
            "auto_scale": None if self.auto_scale is None else round(float(self.auto_scale), 6),
            "anchored": bool(self.anchored),
            "slot_fit": bool(self.slot_fit),
            "skin_source": self.skin_source,
            "parent_item": int(self.parent_item),
            "parent_socket_id": int(self.parent_socket_id),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PartSpec":
        spec = cls(
            vpath=str(data.get("vpath") or ""),
            slot=str(data.get("slot") or "other"),
            name=str(data.get("name") or ""),
            offset=[float(v) for v in (data.get("offset") or [0, 0, 0])][:3],
            rot=[float(v) for v in (data.get("rot") or [0, 0, 0])][:3],
            scale=float(data.get("scale") or 1.0),
            socket=str(data.get("socket") or ""),
            skin_source=str(data.get("skin_source") or ""),
        )
        if data.get("auto_scale") is not None:
            spec.auto_scale = float(data["auto_scale"])
        spec.anchored = bool(data.get("anchored", False))
        spec.slot_fit = bool(data.get("slot_fit", False))
        try:
            spec.parent_item = int(data.get("parent_item") or 0)
            spec.parent_socket_id = int(data.get("parent_socket_id") or 0)
        except (TypeError, ValueError):
            spec.parent_item = spec.parent_socket_id = 0
        while len(spec.offset) < 3:
            spec.offset.append(0.0)
        while len(spec.rot) < 3:
            spec.rot.append(0.0)
        return spec


@dataclass
class Recipe:
    """一套改枪方案。"""
    base: str = ""
    base_name: str = ""
    parts: List[PartSpec] = field(default_factory=list)
    skin_id: str = ""                         # 皮肤机匣的完整资产路径（旧方案可省略）
    skin_base: str = ""                       # 同枪原版机匣，供还原/官方配件使用

    def to_dict(self) -> dict:
        return {"base": self.base, "base_name": self.base_name,
                "parts": [p.to_dict() for p in self.parts],
                "skin_id": self.skin_id, "skin_base": self.skin_base}

    @classmethod
    def from_dict(cls, data: dict) -> "Recipe":
        return cls(
            base=str(data.get("base") or ""),
            base_name=str(data.get("base_name") or ""),
            parts=[PartSpec.from_dict(p) for p in (data.get("parts") or [])],
            skin_id=str(data.get("skin_id") or ""),
            skin_base=str(data.get("skin_base") or ""),
        )


# --------------------------------------------------------------------------- #
# 方案存取
# --------------------------------------------------------------------------- #
def recipe_dir() -> str:
    localapp = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(localapp, "VertexViewer", "gunsmith")
    os.makedirs(path, exist_ok=True)
    return path


def save_recipe(recipe: Recipe, name: str) -> str:
    safe = "".join(c for c in (name or "方案") if c not in '\\/:*?"<>|').strip() or "方案"
    path = os.path.join(recipe_dir(), safe + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(recipe.to_dict(), fh, ensure_ascii=False, indent=2)
    return path


def list_recipes() -> List[str]:
    try:
        return sorted(f[:-5] for f in os.listdir(recipe_dir()) if f.endswith(".json"))
    except OSError:
        return []


def load_recipe(name: str) -> Optional[Recipe]:
    path = os.path.join(recipe_dir(), name + ".json")
    try:
        with open(path, encoding="utf-8") as fh:
            return Recipe.from_dict(json.load(fh))
    except Exception:                                       # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# 几何工具
# --------------------------------------------------------------------------- #
def _lod0(bundle: Optional[ModelBundle]) -> Optional[MeshLOD]:
    mesh = getattr(bundle, "mesh", None)
    if mesh is None or not getattr(mesh, "lods", None):
        return None
    return mesh.lods[0]


def bounds(lod: Optional[MeshLOD]) -> Tuple[np.ndarray, np.ndarray]:
    if lod is None or lod.positions is None or len(lod.positions) == 0:
        return np.zeros(3, np.float32), np.zeros(3, np.float32)
    pos = np.asarray(lod.positions, np.float32)
    return pos.min(axis=0), pos.max(axis=0)


def _rotation(yaw: float, pitch: float, roll: float) -> np.ndarray:
    y, p, r = (math.radians(float(v)) for v in (yaw, pitch, roll))
    cy, sy = math.cos(y), math.sin(y)
    cp, sp = math.cos(p), math.sin(p)
    cr, sr = math.cos(r), math.sin(r)
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]], np.float32)
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]], np.float32)
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]], np.float32)
    return rz @ ry @ rx


def anchor_point(kind: str, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """主件包围盒上某个槽位的默认锚点（GL：x 右 / y 上 / z 后退）。"""
    center = (lo + hi) * 0.5
    size = np.maximum(hi - lo, 1e-4)
    if kind == "front":          # 枪口：最前面 = z 最小
        return np.array([center[0], center[1], lo[2]], np.float32)
    if kind == "back":           # 枪托：最后面 = z 最大
        return np.array([center[0], center[1], hi[2]], np.float32)
    if kind == "center_front":   # 枪管/护木：中心偏前
        return np.array([center[0], center[1], center[2] - size[2] * 0.25], np.float32)
    if kind == "top":            # 瞄具：顶部，稍偏前
        return np.array([center[0], hi[1], center[2] - size[2] * 0.10], np.float32)
    if kind == "bottom_front":   # 握把 / 战术：底部靠前
        return np.array([center[0], lo[1], center[2] - size[2] * 0.12], np.float32)
    if kind == "bottom_back":    # 握把：底部靠后
        return np.array([center[0], lo[1], center[2] + size[2] * 0.18], np.float32)
    if kind == "bottom_mid":     # 弹匣：底部中间
        return np.array([center[0], lo[1], center[2] + size[2] * 0.05], np.float32)
    return np.array([center[0], center[1], center[2]], np.float32)


def auto_scale(slot: str, base_lo: np.ndarray, base_hi: np.ndarray,
               part_lo: np.ndarray, part_hi: np.ndarray) -> float:
    """按槽位目标尺寸算一个统一缩放，让配件和主件比例不违和。"""
    want = SLOT_BY_KEY.get(slot, SLOT_BY_KEY["other"]).size
    base_len = float(np.linalg.norm(base_hi - base_lo)) or 1.0
    part_len = float(np.linalg.norm(part_hi - part_lo)) or 1.0
    return float(np.clip(want * base_len / part_len, 0.02, 40.0))


def place(spec: PartSpec, base_lod: MeshLOD, part_lod: MeshLOD) -> "PartSpec":
    """把 spec 的「自动缩放 + 锚点位移」算好写回（不动用户的手调量）。"""
    base_lo, base_hi = bounds(base_lod)
    part_lo, part_hi = bounds(part_lod)
    slot = SLOT_BY_KEY.get(spec.slot, SLOT_BY_KEY["other"])
    spec.auto_scale = auto_scale(spec.slot, base_lo, base_hi, part_lo, part_hi)
    return spec


# --------------------------------------------------------------------------- #
# 合并
# --------------------------------------------------------------------------- #
def _trs(rot_ypr: Sequence[float] = (0.0, 0.0, 0.0),
         translate: Sequence[float] = (0.0, 0.0, 0.0)) -> np.ndarray:
    """4x4 变换：先绕原点旋转（度，yaw/pitch/roll），再平移。"""
    mat = np.eye(4, dtype=np.float32)
    if any(abs(float(v)) > 1e-9 for v in rot_ypr):
        mat[:3, :3] = _rotation(*rot_ypr)
    mat[:3, 3] = np.asarray(translate, np.float32)
    return mat


def _apply_matrix(lod: MeshLOD, matrix: np.ndarray, scale: float = 1.0) -> MeshLOD:
    """按 4x4 矩阵搬一个网格（顶点先乘缩放，再旋转平移）。"""
    rot = np.asarray(matrix, np.float32)[:3, :3]
    move = np.asarray(matrix, np.float32)[:3, 3]
    pos = np.asarray(lod.positions, np.float32) * float(scale)
    out_pos = pos @ rot.T + move
    nrm = lod.normals
    if nrm is not None:
        out_nrm = np.asarray(nrm, np.float32) @ rot.T
        lens = np.linalg.norm(out_nrm, axis=1, keepdims=True)
        out_nrm = out_nrm / np.maximum(lens, 1e-6)
    else:
        out_nrm = None
    tan = lod.tangents
    if tan is not None:
        tan = np.asarray(tan, np.float32)
        xyz = tan[:, :3] @ rot.T
        out_tan = np.concatenate([xyz, tan[:, 3:4]], axis=1)
    else:
        out_tan = None
    return MeshLOD(
        positions=out_pos.astype(np.float32),
        normals=None if out_nrm is None else out_nrm.astype(np.float32),
        uvs=None if lod.uvs is None else np.array(lod.uvs, np.float32, copy=True),
        tangents=None if out_tan is None else out_tan.astype(np.float32),
        indices=np.array(lod.indices, np.uint32, copy=True) if lod.indices is not None else None,
        sections=[Section(material_path=s.material_path,
                          first_index=s.first_index, num_triangles=s.num_triangles,
                          first_vertex=s.first_vertex, num_vertices=s.num_vertices)
                  for s in (lod.sections or [])],
        uv_sets=None if lod.uv_sets is None else np.array(lod.uv_sets, np.float32, copy=True),
        bone_weights=None, bone_indices=None, bones=list(lod.bones or []),
    )


def _transform_lod(lod: MeshLOD, matrix: np.ndarray, scale: float,
                   translate: np.ndarray) -> MeshLOD:
    """按 (旋转矩阵, 缩放, 平移) 搬一个网格 —— 老接口，内部走 `_apply_matrix`。"""
    mat = np.eye(4, dtype=np.float32)
    mat[:3, :3] = np.asarray(matrix, np.float32)
    mat[:3, 3] = np.asarray(translate, np.float32)
    return _apply_matrix(lod, mat, scale)


def _section_ranges(lod: MeshLOD) -> List[Tuple[str, int, int, int, int]]:
    """(material_path, first_vertex, num_vertices, first_index, num_indices)"""
    total_v = int(0 if lod.positions is None else len(lod.positions))
    total_i = int(0 if lod.indices is None else len(lod.indices))
    secs = [s for s in (lod.sections or []) if s.num_triangles > 0]
    if not secs:
        return [("", 0, total_v, 0, total_i)]
    out: List[Tuple[str, int, int, int, int]] = []
    for sec in secs:
        first_i = max(0, int(sec.first_index))
        count_i = int(sec.num_triangles) * 3
        if count_i <= 0:
            continue
        out.append((sec.material_path or "", int(sec.first_vertex), int(sec.num_vertices),
                    first_i, count_i))
    return out or [("", 0, total_v, 0, total_i)]


def merge(items: Sequence[Tuple[MeshLOD, List[Material]]]) -> Tuple[MeshLOD, List[Material]]:
    """把若干 (lod, 材质表) 拼成一个 lod。

    材质表**按段序号对齐**：渲染器找不到 `material_path` 会退回 `materials[段号]`，
    所以这里每段都往列表里塞一个材质（允许重复），段号才对得上。
    """
    out_pos: List[np.ndarray] = []
    out_nrm: List[np.ndarray] = []
    out_uv: List[np.ndarray] = []
    out_uv_sets: List[np.ndarray] = []
    out_tan: List[np.ndarray] = []
    out_idx: List[np.ndarray] = []
    sections: List[Section] = []
    materials: List[Material] = []

    items = list(items)
    uv_channels = max((lod.uv_channel_count for lod, _ in items if lod is not None),
                      default=1)
    uv_channels = max(1, uv_channels)
    v_off = 0
    i_off = 0
    for lod, mats in items:
        if lod is None or lod.positions is None or lod.indices is None:
            continue
        n = int(len(lod.positions))
        if n == 0:
            continue
        mats_list = [m for m in (mats or []) if isinstance(m, Material)]
        by_path = {str(m.pak_path): m for m in mats_list if m.pak_path}
        out_pos.append(np.asarray(lod.positions, np.float32))
        out_nrm.append(np.asarray(lod.normals, np.float32)
                       if lod.normals is not None else np.zeros((n, 3), np.float32))
        uv0 = lod.uv(0)
        out_uv.append(np.asarray(uv0, np.float32)
                      if uv0 is not None else np.zeros((n, 2), np.float32))
        channels = []
        for channel in range(uv_channels):
            uv = lod.uv(channel)
            channels.append(np.asarray(uv, np.float32) if uv is not None
                            else np.zeros((n, 2), np.float32))
        out_uv_sets.append(np.stack(channels, axis=1))
        if lod.tangents is not None:
            t = np.asarray(lod.tangents, np.float32)
            if t.shape[1] == 3:
                t = np.column_stack((t, np.ones(n, np.float32)))
            out_tan.append(t)
        else:
            t = np.zeros((n, 4), np.float32)
            t[:, 3] = 1.0
            out_tan.append(t)
        # 先在每件自己的顶点范围内校验。坏索引偏移后可能恰好指向下一件，
        # 变成跨配件的长三角；不能等合并后才检查，更不能钳到最后一个顶点。
        raw_idx = np.asarray(lod.indices).reshape(-1)
        tri = raw_idx[:raw_idx.size // 3 * 3].reshape(-1, 3)
        valid = np.all(np.isfinite(tri) & (tri >= 0) & (tri < n)
                       & (tri == np.floor(tri)), axis=1)
        prefix = np.concatenate(([0], np.cumsum(valid))) * 3
        clean_idx = tri[valid].astype(np.uint32).reshape(-1)
        out_idx.append(clean_idx + v_off)

        for sec_index, (mat_path, first_v, num_v, first_i, num_i) in enumerate(_section_ranges(lod)):
            mat = by_path.get(mat_path)
            if mat is None and mats_list:
                mat = mats_list[sec_index] if sec_index < len(mats_list) else mats_list[0]
            start = min(len(tri), first_i // 3)
            end = min(len(tri), (first_i + num_i) // 3)
            count = int(prefix[end] - prefix[start])
            if count <= 0:
                continue
            # 每段持有独立绑定；同名/同路径的合成材质不能串到另一件上。
            mat = replace(mat) if mat is not None else Material(name="Default")
            mat.pak_path = f"vertexviewer://gunsmith/{len(sections)}/{mat.name}"
            sections.append(Section(material_path=mat.pak_path,
                                    first_index=i_off + int(prefix[start]),
                                    num_triangles=count // 3,
                                    first_vertex=v_off + first_v,
                                    num_vertices=num_v))
            materials.append(mat)
        v_off += n
        i_off += int(clean_idx.size)

    if not out_pos:
        return MeshLOD(), []
    merged = MeshLOD(
        positions=np.concatenate(out_pos, axis=0),
        normals=np.concatenate(out_nrm, axis=0),
        uvs=np.concatenate(out_uv, axis=0),
        tangents=np.concatenate(out_tan, axis=0),
        indices=np.concatenate(out_idx, axis=0).astype(np.uint32),
        sections=sections,
        uv_sets=np.concatenate(out_uv_sets, axis=0),
    )
    return merged, materials


def _place_by_socket(spec: PartSpec, parent_vpath: str,
                     parent_mat: np.ndarray) -> Optional[np.ndarray]:
    """把配件挂到父件的挂点上，返回世界矩阵（找不到挂点返回 None）。"""
    family = mount_family(spec.vpath, spec.slot)
    cands = socket_candidates(family)
    hit = find_socket(parent_vpath, cands, prefer=spec.socket)
    if hit is None:
        return None
    name, _key, local = hit
    if not spec.socket:
        spec.socket = name            # 记住自动挑中的挂点，界面里能看见
    return parent_mat @ local


def _bbox_fallback(spec: PartSpec, base_lod: Optional[MeshLOD], lod: MeshLOD,
                   base_mat: np.ndarray) -> np.ndarray:
    """没有挂点时的兜底：按包围盒把配件拉到主件该去的位置（老逻辑）。"""
    if base_lod is None:
        return base_mat.copy()
    base_lo, base_hi = bounds(base_lod)
    part_lo, part_hi = bounds(lod)
    size = np.maximum(base_hi - base_lo, 1e-4)
    center = (part_lo + part_hi) * 0.5
    family = mount_family(spec.vpath, spec.slot)
    ax = int(np.argmax(size))
    up = 1 if ax != 1 else 2
    t = np.zeros(3, np.float32)
    for i in range(3):
        if i != ax:
            t[i] = (base_lo[i] + base_hi[i]) * 0.5 - center[i]
    if family in ("barrel", "muzzle", "handguard"):
        t[ax] = base_hi[ax] - part_lo[ax]
    elif family == "stock":
        t[ax] = base_lo[ax] - part_hi[ax]
    elif family in ("mag", "grip", "foregrip"):
        t[up] = base_lo[up] - part_hi[up]
        t[ax] = (base_lo[ax] + base_hi[ax]) * 0.5 - center[ax] \
            + size[ax] * (0.08 if family == "mag" else 0.02)
    elif family == "optic":
        t[up] = base_hi[up] - part_lo[up]
        t[ax] = (base_lo[ax] + base_hi[ax]) * 0.5 - center[ax] - size[ax] * 0.06
    else:
        t[ax] = (base_lo[ax] + base_hi[ax]) * 0.5 - center[ax]
    return _trs((0.0, 0.0, 0.0), t) @ base_mat


def _lod_bounds_after(lod: MeshLOD, mat: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """网格经过 4x4 变换后的包围盒（GL 米）。"""
    pos = lod.positions @ mat[:3, :3].T + mat[:3, 3]
    return pos.min(axis=0), pos.max(axis=0)


def _surface_top_at(lod: MeshLOD, mat: np.ndarray, x: float, band: float = 0.04,
                    z: float = 0.0, zband: float = 0.03) -> Optional[float]:
    """父件在某个纵向位置上的「顶面高度」。

    `Sco_point` 这类挂点给的是插入点，但**导轨面**本身是网格几何：同一把枪上
    后导轨比前导轨高一截，拿整把枪的包围盒顶面去贴，瞄具就会悬空一厘米。
    这里直接采样父件顶点：取 |x-中心| 与 |z-中心| 都在窗口内的那一撮顶点，
    返回它们的最高点。采不到就返回 None。
    """
    try:
        pos = lod.positions @ mat[:3, :3].T + mat[:3, 3]
    except Exception:                                        # noqa: BLE001
        return None
    if not len(pos):
        return None
    near = pos[(np.abs(pos[:, 0] - x) <= band) & (np.abs(pos[:, 2] - z) <= zband)]
    if len(near) < 8:
        near = pos[np.abs(pos[:, 0] - x) <= band * 2.0]
    if len(near) < 8:
        return None
    return float(near[:, 1].max())


def _seat_on_surface(spec: PartSpec, lod: MeshLOD, mat: np.ndarray,
                     parent_lod: Optional[MeshLOD],
                     parent_mat: np.ndarray) -> np.ndarray:
    """把瞄具「坐到导轨面」上：底面比导轨面低就抬起来，别的不管。"""
    if parent_lod is None or mount_family(spec.vpath, spec.slot) != "optic":
        return mat
    try:
        lo, hi = _lod_bounds_after(lod, mat)
    except Exception:                                        # noqa: BLE001
        return mat
    center_x = float((lo[0] + hi[0]) * 0.5)
    center_z = float((lo[2] + hi[2]) * 0.5)
    top = _surface_top_at(parent_lod, parent_mat, center_x, z=center_z)
    if top is None:
        return mat
    delta = top - float(lo[1])
    if delta <= 0.002 or delta > 0.40:            # 已经坐上去了 / 差得太离谱
        return mat
    out = mat.copy()
    out[1, 3] += float(delta)
    return out


#: 挂接面规则：(世界轴, 部件在父件的哪一侧)。挂点只给出「插入点」，
#: 网格本身未必正好贴到父件上（枪托伸出量、弹匣插入深度、握把上沿都各说各话），
#: 差几厘米在侧视里就是「悬空 / 错位」。这里按族把「该贴的面」贴上去。
_MOUNT_FACE = {
    "stock": (0, -1),          # 枪托前端贴机匣后端（-x 侧）
    "barrel": (0, +1),         # 枪管后端贴机匣前端
    "muzzle": (0, +1),         # 枪口后端贴枪管前端
    "handguard": (0, +1),      # 护木后端贴机匣前端
    "grip": (1, -1),           # 握把上沿贴机匣下沿
    "mag": (1, -1),            # 弹匣上沿贴机匣下沿
    "foregrip": (1, -1),       # 前握把上沿贴护木下沿
    "bipod": (1, -1),
    "tactical": (1, -1),       # 激光/电筒贴导轨下沿
}


def _snap_mount_face(spec: PartSpec, lod: MeshLOD, mat: np.ndarray,
                     parent_lod: Optional[MeshLOD],
                     parent_mat: np.ndarray) -> np.ndarray:
    """把配件该贴的那一面贴到父件上（只平移，不动旋转）。"""
    if parent_lod is None:
        return mat
    rule = _MOUNT_FACE.get(mount_family(spec.vpath, spec.slot))
    if rule is None:
        return mat
    axis, side = rule
    try:
        plo, phi = _lod_bounds_after(parent_lod, parent_mat)
        lo, hi = _lod_bounds_after(lod, mat)
    except Exception:                                        # noqa: BLE001
        return mat
    # 另外两根轴上，配件得确实落在父件附近，才允许贴面（防止把旁边的件拽过来）
    for other in (0, 1, 2):
        if other == axis:
            continue
        if hi[other] < plo[other] - 0.06 or lo[other] > phi[other] + 0.06:
            return mat
    delta = (plo[axis] - hi[axis]) if side < 0 else (phi[axis] - lo[axis])
    if side < 0:
        if delta <= 0.001 or delta > 0.30:      # 已经插进去 / 差得太离谱就不动
            return mat
    else:
        if delta >= -0.001 or delta < -0.30:
            return mat
    out = mat.copy()
    out[axis, 3] += float(delta)
    return out


def _snap_optic_to_rail(spec: PartSpec, lod: MeshLOD, mat: np.ndarray,
                        parent_lod: Optional[MeshLOD],
                        parent_mat: np.ndarray) -> np.ndarray:
    """把瞄具按导轨顶面吸一下。

    挂点给的是「导轨上的某个点」，瞄具网格自己的底面未必正好贴在那条线上，
    差个一两厘米在侧视里就是「瞄具悬空」或者「陷进导轨」。这里只在偏差
    超过 1.5cm 时才动，其它情况保持游戏原样（导轨槽本来就有高低）。
    """
    if parent_lod is None or mount_family(spec.vpath, spec.slot) != "optic":
        return mat
    try:
        plo, phi = _lod_bounds_after(parent_lod, parent_mat)
        lo, _hi = _lod_bounds_after(lod, mat)
    except Exception:                                        # noqa: BLE001
        return mat
    # 只在瞄具确实落在导轨上方时用导轨顶面；跑到旁边去的不动
    rail_top = float(phi[1])
    gap = float(lo[1]) - rail_top
    if abs(gap) <= 0.015:
        return mat
    if float(lo[0]) > float(phi[0]) or float(_hi[0]) < float(plo[0]):
        return mat
    out = mat.copy()
    out[1, 3] -= gap
    return out


_FIT_FAMILIES = {"stock", "barrel", "muzzle", "handguard", "bipod"}
_FIT_OVERLAP_MIN = 0.70
_FIT_ENABLED = os.environ.get("VERTEXVIEWER_NO_FIT", "") != "1"
_FIT_GUARD = os.environ.get("VERTEXVIEWER_NO_FIT_GUARD", "") != "1"


def _preset_matches(parts: Sequence[Tuple[PartSpec, MeshLOD]],
                    desid: int) -> float:
    """这套预设和「我们实际装的件」有多少比例是同一批道具。

    预设表里同一把枪有几十套（不同枪管/枪托/瞄具的组合）。以前按「包围盒最接近」
    挑一套来当标定标准，挑错一套就会把对好的件拽歪 —— 必须先比对道具 ID。
    """
    from core import presets as _presets
    nodes = _presets.dedup(_presets.nodes_of(desid))
    want = {int(n[2]) for n in nodes if int(n[2] or 0)}
    if not want:
        return 0.0
    got = set()
    for spec, _lod in parts:
        try:
            item = int(_sockets.item_of_mesh(spec.vpath) or 0)
        except Exception:                                    # noqa: BLE001
            item = 0
        if item:
            got.add(item)
    if not got:
        return 0.0
    return len(want & got) / float(len(want))



def _fit_to_official(base_vpath: str, base_lod: Optional[MeshLOD],
                     parts: Sequence[Tuple[PartSpec, MeshLOD]],
                     plan: Dict[int, np.ndarray], *, limit: float = 0.30
                     ) -> Dict[int, np.ndarray]:
    """用游戏自己的预设包围盒把「伸出量」补齐。

    `GunPresetBoundsTable` 里记着每个官方预设拼好后的整体包围盒。挂点给的是
    「插入点」，伸缩托拉出多少、两脚架放下来多少、消音器拧多深，这些都不在挂点里，
    所以拼出来常常在某一头短一截。这里把残差归给顶在那头上的那一件（只平移），
    和 `tools/calibrate_parts.py` 的标定同一个思路，只是改成每次装配现算。
    """
    try:
        from core import presets as _presets          # 延迟导入：没装游戏也能跑界面
        item = _sockets.item_of_mesh(base_vpath)
        if not _FIT_ENABLED or not item or base_lod is None:
            return plan
        desids = _presets.presets_of_item(item)
    except Exception:                                        # noqa: BLE001
        return plan
    if not desids:
        return plan
    boxes: Dict[int, Tuple[np.ndarray, np.ndarray]] = {}
    lo, hi = bounds(base_lod)
    b_lo, b_hi = lo.copy(), hi.copy()
    lo, hi = lo.copy(), hi.copy()
    for spec, lod in parts:
        mat = plan.get(id(spec))
        if mat is None:
            continue
        try:
            plo, phi = _lod_bounds_after(lod, mat)
        except Exception:                                    # noqa: BLE001
            continue
        boxes[id(spec)] = (plo, phi)
        lo = np.minimum(lo, plo)
        hi = np.maximum(hi, phi)
    ours_items = parts
    best = None
    for desid in desids:
        got = _presets.bounds_of(desid)
        if got is None:
            continue
        overlap = _preset_matches(ours_items, desid)
        org, ext = got
        off_lo = np.array([org[1] - ext[1], org[2] - ext[2], org[0] - ext[0]]) * 0.01
        off_hi = np.array([org[1] + ext[1], org[2] + ext[2], org[0] + ext[0]]) * 0.01
        ours = np.concatenate([lo, hi]) * 100.0
        theirs = np.concatenate([off_lo, off_hi]) * 100.0
        err = float(np.max(np.abs(ours - theirs)))
        # 先要求「装的是同一批件」，再在这个前提下挑包围盒最接近的那套
        key = (-round(overlap, 3), err)
        if best is None or key < best[0]:
            best = (key, err, overlap, off_lo, off_hi, desid)
    if best is None:
        return plan
    _key, _err, overlap, off_lo, off_hi, desid = best
    if overlap < _FIT_OVERLAP_MIN:
        return plan                    # 没有一套预设和我们装的件对得上，就别拿它当标尺
    # 已经对得很准的预设不动（差 1cm 以内就是挂点本身的精度）
    if _err <= 1.0:
        return plan
    # 只沿「枪长」这一个轴补伸出量：竖直/横向的差多是瞄具高矮、两脚架张开角度，
    # 硬拽会把贴好的件从挂点上拉下来（XM250 的瞄具就是这么被压进机匣的）。
    long_axis = int(np.argmax(b_hi - b_lo))
    moves: Dict[int, np.ndarray] = {}
    for axis in (long_axis,):
        for want_lo, cur, other, edge in ((True, lo, hi, off_lo), (False, hi, lo, off_hi)):
            delta = float(edge[axis] - cur[axis])
            if abs(delta) <= 0.01 or abs(delta) > limit:
                continue
            pick = None
            for spec, _lod in parts:
                box = boxes.get(id(spec))
                if box is None:
                    continue
                if mount_family(spec.vpath, spec.slot) not in _FIT_FAMILIES:
                    continue
                face = box[0] if want_lo else box[1]
                if abs(float(face[axis]) - float(cur[axis])) > 0.01:
                    continue
                if pick is not None:                 # 有歧义就放手
                    pick = None
                    break
                pick = spec
            if pick is None:
                continue
            shift = moves.setdefault(id(pick), np.zeros(3, np.float32))
            shift[axis] += delta
    def _nearest(box, skip_id: int) -> float:
        best_gap = 1e9
        for other_id, other_box in boxes.items():
            if other_id == skip_id:
                continue
            olo, ohi = other_box
            d = np.maximum(np.maximum(box[0] - ohi, olo - box[1]), 0.0)
            best_gap = min(best_gap, float(np.linalg.norm(d)))
        d = np.maximum(np.maximum(box[0] - b_hi, b_lo - box[1]), 0.0)
        return min(best_gap, float(np.linalg.norm(d)))

    for spec, lod in parts:
        shift = moves.get(id(spec))
        mat = plan.get(id(spec))
        box = boxes.get(id(spec))
        if shift is None or mat is None or box is None:
            continue
        before = _nearest(box, id(spec))
        after_box = (box[0] + shift, box[1] + shift)
        if _FIT_GUARD and _nearest(after_box, id(spec)) > max(before + 0.005, 0.01):
            continue                 # 这一挪会把它从父件上拽开，宁可短一截
        out = mat.copy()
        out[:3, 3] += shift
        plan[id(spec)] = out
        try:                                     # 移完顺手把那件的盒子更新掉
            boxes[id(spec)] = _lod_bounds_after(lod, out)
        except Exception:                                    # noqa: BLE001
            pass
    return plan


_CLOSE_FAMILIES = {"stock", "barrel", "handguard", "muzzle", "grip", "mag",
                   "bipod", "foregrip", "tactical"}


def _close_mount_gaps(base_lod: MeshLOD, parts: Sequence[Tuple[PartSpec, MeshLOD]],
                      plan: Dict[int, np.ndarray], *, max_gap: float = 0.08,
                      keep: Optional[set] = None,
                      ) -> Dict[int, np.ndarray]:
    """把「没摆到位的件」推回去。

    只处理**没有挂点**的件：它们的摆放本来就是按包围盒猜的。走挂点的件保持
    游戏坐标不动 —— 挂点已经给了插入点，再按包围盒贴一次只会把它从挂点上拽开
    （XM250 的瞄具就是被这么压进机匣、弹匣被推得偏到一边的）。
    """
    boxes: Dict[int, Tuple[np.ndarray, np.ndarray]] = {}
    b_lo, b_hi = bounds(base_lod)
    for spec, lod in parts:
        mat = plan.get(id(spec))
        if mat is None:
            continue
        try:
            boxes[id(spec)] = _lod_bounds_after(lod, mat)
        except Exception:                                    # noqa: BLE001
            continue
    for spec, lod in parts:
        if keep and id(spec) in keep:
            continue                                   # 挂点摆的，原样
        if mount_family(spec.vpath, spec.slot) not in _CLOSE_FAMILIES:
            continue
        mat = plan.get(id(spec))
        box = boxes.get(id(spec))
        if mat is None or box is None:
            continue
        lo, hi = box
        best = None
        for other_id, (olo, ohi) in boxes.items():
            if other_id == id(spec):
                continue
            d = np.maximum(np.maximum(lo - ohi, olo - hi), 0.0)
            dist = float(np.linalg.norm(d))
            if best is None or dist < best[0]:
                best = (dist, d, olo, ohi)
        d = np.maximum(np.maximum(lo - b_hi, b_lo - hi), 0.0)
        dist = float(np.linalg.norm(d))
        if best is None or dist < best[0]:
            best = (dist, d, b_lo, b_hi)
        if best is None:
            continue
        dist, sep, olo, ohi = best
        if dist <= 0.005 or dist > max_gap:
            continue
        axes = [i for i in range(3) if sep[i] > 0.0]
        if len(axes) != 1:
            continue                       # 斜着差一截的，判不清该往哪推
        axis = axes[0]
        sign = 1.0 if lo[axis] > ohi[axis] else -1.0
        shift = np.zeros(3, np.float32)
        shift[axis] = -sign * float(sep[axis])
        out = mat.copy()
        out[:3, 3] += shift
        plan[id(spec)] = out
        try:
            boxes[id(spec)] = _lod_bounds_after(lod, out)
        except Exception:                                    # noqa: BLE001
            pass
    return plan


def _push_barrel_out(base_lod: MeshLOD,
                     parts: Sequence[Tuple[PartSpec, MeshLOD]],
                     plan: Dict[int, np.ndarray], *, protrude: float = 0.02,
                     min_len: float = 0.25) -> Dict[int, np.ndarray]:
    """枪管整根藏在机匣里时，沿枪长把它推到露出 `protrude` 米，子件跟着走。

    为什么需要：XM250 这种短机匣/无托布局，游戏里的 `Bar_point` 在机匣中部，
    照挂点摆出来的枪管（0.012..0.367）完全被机匣（..0.647）包住，肉眼看就是
    「没有枪管、枪口陷进护木」；官方包围盒比我们长 7~14cm 也印证枪管该露在外面。
    判定只在「整根都在机匣盒内」时触发，正常枪（枪管本来就伸在外面）不受影响。
    """
    if not parts:
        return plan
    try:
        b_lo, b_hi = _lod_bounds_after(base_lod, np.eye(4, dtype=np.float32))
    except Exception:                                        # noqa: BLE001
        return plan
    axis = int(np.argmax(np.asarray(b_hi) - np.asarray(b_lo)))
    item_of = {}
    for spec, _lod in parts:
        try:
            item_of[id(spec)] = int(_sockets.item_of_mesh(spec.vpath) or 0)
        except Exception:                                    # noqa: BLE001
            item_of[id(spec)] = 0
    for spec, lod in parts:
        if mount_family(spec.vpath, spec.slot) != "barrel":
            continue
        mat = plan.get(id(spec))
        if mat is None:
            continue
        try:
            lo, hi = _lod_bounds_after(lod, mat)
        except Exception:                                    # noqa: BLE001
            continue
        if hi[axis] - lo[axis] < min_len:
            continue                                         # 太短，不像枪管
        if lo[axis] < b_lo[axis] - 0.001 or hi[axis] > b_hi[axis] + 0.001:
            continue                                         # 已经露在外面
        shift = float(b_hi[axis] + protrude - hi[axis])
        if shift <= 0.02:
            continue
        move = np.zeros(3, np.float32)
        move[axis] = shift
        movers = {id(spec)}
        changed = True
        while changed:                                       # 把孙子件也带上
            changed = False
            for other, _l in parts:
                if id(other) in movers:
                    continue
                if int(other.parent_item or 0) in {item_of.get(m) for m in movers}:
                    movers.add(id(other))
                    changed = True
        for other, _l in parts:
            if id(other) not in movers:
                continue
            src = plan.get(id(other))
            if src is None:
                continue
            out = src.copy()
            out[:3, 3] += move
            plan[id(other)] = out
    return plan


def resolve_placements(base_vpath: str, base_lod: Optional[MeshLOD],
                       parts: Sequence[Tuple[PartSpec, MeshLOD]]
                       ) -> Dict[int, np.ndarray]:
    """算出每个配件的世界矩阵（GL 米）—— 就是游戏自己的 socket 挂接。

    规则（全部来自 GunDescTable 与 PartSocketsTable）：
      * 枪管 / 护木 / 枪托 / 握把 / 弹匣 / 瞄具 / 战术 → 挂在机匣的对应 socket；
      * 枪口 → 挂在**枪管**的 `Muzzle_point`（没枪管就退回机匣）；
      * 前握把 → 挂在**护木**的 `For_point`（没护木就退回枪管 / 机匣）。
      * 显式挂点不在上述父件上时，只在实际已选配件中找唯一拥有者，
        等父件放置完成后相乘；缺失/重复/歧义不自动猜父件。

    父件找不到挂点时退回包围盒兜底，保证不会飞出屏幕。
    """
    ident = np.eye(4, dtype=np.float32)
    placed: Dict[str, Tuple[str, np.ndarray, MeshLOD]] = {}
    placed_specs: Dict[int, Tuple[str, np.ndarray, MeshLOD]] = {}
    out: Dict[int, np.ndarray] = {}
    #: 走挂点摆出来的件（游戏坐标），收尾的「贴缝」不许再动它们。
    socket_placed: set = set()

    all_parts = list(parts)
    pending = list(all_parts)

    #: 官方预设里写死了「谁挂在谁身上」；把道具 ID 映射成选中的部件。
    spec_of_item: Dict[int, PartSpec] = {}
    for part_spec, _part_lod in all_parts:
        try:
            own = int(_sockets.item_of_mesh(part_spec.vpath))
        except Exception:                                  # noqa: BLE001
            own = 0
        if own:
            spec_of_item.setdefault(own, part_spec)

    def named_socket(path: str, name: str):
        """An exact socket on this selected mesh; no prefix/global guessing."""
        try:
            names = [n for n in _sockets.socket_names(path)
                     if n.casefold() == name.casefold()]
            if len(names) != 1:
                return None
            matrix = _sockets.socket_matrix(path, names[0])
            return (names[0], matrix) if matrix is not None else None
        except Exception:                                  # noqa: BLE001
            return None

    for _round in range(max(3, len(all_parts) + 1)):
        if not pending:
            break
        rest: List[Tuple[PartSpec, MeshLOD]] = []
        for spec, lod in pending:
            family = mount_family(spec.vpath, spec.slot)
            mat = None
            explicit_parent_lod = None
            parent_vpath, parent_mat = base_vpath, ident
            parent_lod: Optional[MeshLOD] = base_lod
            # 1) 预设写死了父件（导轨附件这类「同名挂点在两件上都有」的情形）
            forced = spec_of_item.get(int(spec.parent_item or 0))
            if forced is not None and forced is not spec:
                got = placed_specs.get(id(forced))
                if got is None:                     # 父件还没摆好，等下一轮
                    rest.append((spec, lod))
                    continue
                parent_vpath, parent_mat, explicit_parent_lod = got
                parent_lod = explicit_parent_lod
                hit = named_socket(parent_vpath, spec.socket) if spec.socket else None
                if hit is None:
                    found = find_socket(parent_vpath, socket_candidates(family),
                                        prefer=spec.socket)
                    if found is not None:
                        hit = (found[0], found[2])
                if hit is not None:
                    spec.socket = hit[0]
                    mat = parent_mat @ hit[1]
            else:
                # 2) 没写父件的，按族推（枪口挂枪管、前握把挂护木……）
                parents = PARENT_FAMILY.get(family, ())
                if parents:
                    for want in parents:
                        got = placed.get(want)
                        if got is not None:
                            parent_vpath, parent_mat, parent_lod = got
                            break
                    else:                   # 父件还没摆好（或根本没装），等下一轮
                        if any(mount_family(s.vpath, s.slot) in parents for s, _l in pending):
                            rest.append((spec, lod))
                            continue
                exact = named_socket(parent_vpath, spec.socket) if spec.socket else None
                if spec.socket:
                    # 同一个挂点名常常在好几件上都有：MagBass_point / GripBass_Point
                    # 在机匣和弹匣/握把上都存在，RailC*_point 在机匣和护木上都存在。
                    # 光看名字分不出零件该挂谁，就把每个「可能的父件」都试一遍，
                    # 谁摆上去之后真正贴住了就用谁 —— 这就是游戏里那套父子关系。
                    owners = []
                    deferred = False
                    if named_socket(base_vpath, spec.socket) is not None:
                        owners.append((base_vpath, base_lod, ident))
                    for candidate, candidate_lod in all_parts:
                        if candidate is spec:
                            continue
                        if named_socket(candidate.vpath, spec.socket) is None:
                            continue
                        placed_parent = placed_specs.get(id(candidate))
                        if placed_parent is None:
                            deferred = True              # 还没摆好，下一轮再说
                            continue
                        owners.append((candidate.vpath, candidate_lod, placed_parent[1]))
                    best = None
                    for owner_vpath, owner_lod, owner_mat in owners:
                        hit = named_socket(owner_vpath, spec.socket)
                        if hit is None:
                            continue
                        trial = owner_mat @ hit[1]
                        try:
                            lo, hi = _lod_bounds_after(lod, trial)
                            olo, ohi = _lod_bounds_after(owner_lod, owner_mat)
                        except Exception:                # noqa: BLE001
                            continue
                        d = np.maximum(np.maximum(lo - ohi, olo - hi), 0.0)
                        gap = float(np.linalg.norm(d))
                        if best is None or gap < best[0]:
                            best = (gap, owner_vpath, owner_lod, owner_mat, hit, trial)
                    if best is not None and best[0] <= 0.02:
                        _gap, parent_vpath, parent_lod, parent_mat, hit, mat = best
                        spec.socket = hit[0]
                    elif deferred:
                        rest.append((spec, lod))         # 等父件摆好再判断
                        continue
                    elif exact is not None:
                        spec.socket = exact[0]
                        mat = parent_mat @ exact[1]
                    else:
                        mat = _place_by_socket(spec, parent_vpath, parent_mat)
                else:
                    mat = _place_by_socket(spec, parent_vpath, parent_mat)
            snapped = mat is not None
            if mat is None:
                # 没有挂点的件只能靠包围盒估位置，这时候才用「贴面 / 吸导轨」修正。
                # 走挂点的件保持挂点算出来的原始位置 —— 那才是游戏里的位置。
                mat = _bbox_fallback(spec, base_lod, lod, parent_mat)
                p_lod = base_lod if parent_vpath == base_vpath else (explicit_parent_lod or parent_lod)
                mat = _snap_mount_face(spec, lod, mat, p_lod, parent_mat)
                mat = _snap_optic_to_rail(spec, lod, mat, p_lod, parent_mat)
            else:
                socket_placed.add(id(spec))
                # 瞄具：挂点只给插入点，导轨面得按父件几何采样，否则会陷进机匣
                p_lod = base_lod if parent_vpath == base_vpath else (explicit_parent_lod or parent_lod)
                mat = _seat_on_surface(spec, lod, mat, p_lod, parent_mat)
            out[id(spec)] = mat
            placed.setdefault(family, (spec.vpath, mat, lod))
            placed_specs[id(spec)] = (spec.vpath, mat, lod)
        if len(rest) == len(pending):
            pending = rest
            break
        pending = rest
    for spec, lod in pending:               # 兜底的兜底
        out.setdefault(id(spec), _bbox_fallback(spec, base_lod, lod, ident))
    # 伸缩托拉出量、两脚架角度这些不在挂点里：用官方预设包围盒把残差补齐。
    plan = _fit_to_official(base_vpath, base_lod, [(s, l) for s, l in parts], out)
    # 无托/短机匣的枪（XM250）挂点把枪管放在机匣里面，整根枪管被机体包住看不见，
    # 官方包围盒却比我们长一截——把枪管（连同挂在它上面的枪口）推到露出为止。
    plan = _push_barrel_out(base_lod, [(s, l) for s, l in parts], plan)
    return _close_mount_gaps(base_lod, [(s, l) for s, l in parts], plan,
                             keep=socket_placed)


def assemble(base: Optional[ModelBundle],
             parts: Iterable[Tuple[PartSpec, Optional[ModelBundle]]],
             base_vpath: str = "") -> ModelBundle:
    """主件 + 配件 → 一个新的 ModelBundle（按游戏挂点拼出来的）。

    流程：`resolve_placements` 用 socket 链算出每件的世界矩阵 → 叠上
    「自动伸展量」（`part_offsets`，伸缩托用）和用户手调的
    平移 / 旋转 / 缩放 → 把所有网格烘焙成一个 MeshLOD。
    """
    base_lod = _lod0(base)
    if base_lod is None:
        return ModelBundle()
    base_vpath = base_vpath or getattr(base, "vpath", "") or ""
    items: List[Tuple[MeshLOD, List[Material]]] = [(base_lod, list(base.materials or []))]
    textures: List[Texture] = list(getattr(base, "textures", []) or [])

    part_list = [(spec, _lod0(bundle), bundle) for spec, bundle in parts]
    part_list = [(spec, lod, bundle) for spec, lod, bundle in part_list if lod is not None]

    plan = resolve_placements(base_vpath, base_lod, [(s, l) for s, l, _b in part_list])

    for spec, lod, bundle in part_list:
        k = float(spec.scale or 1.0)
        world = plan.get(id(spec))
        if world is None:
            world = np.eye(4, dtype=np.float32)
        # 自动伸展量：伸缩托在游戏里默认拉出一段，socket 本身不含这段。
        stretch = part_offset(spec.vpath)
        if float(np.abs(stretch).max()) > 1e-6:
            world = world @ _trs((0.0, 0.0, 0.0), stretch)
        if any(abs(float(v)) > 1e-9 for v in spec.offset):
            world = world @ _trs((0.0, 0.0, 0.0), spec.offset)
        if any(abs(float(v)) > 1e-9 for v in spec.rot):
            world = world @ _trs(tuple(spec.rot))
        moved = _apply_matrix(lod, world, k)
        items.append((moved, list(getattr(bundle, "materials", []) or [])))
        textures.extend(getattr(bundle, "textures", []) or [])

    merged, materials = merge(items)
    bundle = ModelBundle()
    bundle.mesh = Mesh(name="gunsmith", lods=[merged])
    bundle.materials = materials
    bundle.textures = textures
    bundle.display_name = "改枪方案"
    bundle.display_name_cn = "改枪方案"
    return bundle


def part_summary(spec: PartSpec) -> str:
    label = SLOT_BY_KEY.get(spec.slot, SLOT_BY_KEY["other"]).label
    name = spec.name or os.path.splitext(os.path.basename(spec.vpath))[0]
    return "%s · %s" % (label, name)


# --------------------------------------------------------------------------- #
# 官方建议配件
# --------------------------------------------------------------------------- #
_CODE_RE = re.compile(r"([A-Za-z0-9]{2,6}-(?:[A-Za-z]+_)?\d{2,3})")
_SLOT_PREFIXES = ("Bar", "Han", "Muz", "Mag", "Sto", "PisG", "FroG", "Acl", "Sco", "Dev", "Att")
_PREFIX_SLOT = {"Bar": "barrel", "Han": "handguard", "Muz": "muzzle", "Mag": "mag",
                "Sto": "stock", "PisG": "grip", "FroG": "grip", "Acl": "optic", "Sco": "optic", "Dev": "tactical", "Att": "tactical"}


def gun_code(vpath: str) -> str:
    """从资产名里抠出「枪族+型号」码，例如 M4A1-Std_001。"""
    stem = os.path.splitext(os.path.basename(vpath or ""))[0]
    m = _CODE_RE.search(stem)
    if m:
        return m.group(1)
    parts = stem.split("_")
    return "_".join(parts[1:4]) if len(parts) > 3 else stem


def _model_dir(vpath: str) -> str:
    return vpath.rsplit("/", 1)[0] if "/" in vpath else ""


def _skin_kit_dir(vpath: str) -> str:
    """外观皮肤件所在的那一层目录（`.../WeaponAppear/<皮肤>/<枪>/Model/`）。

    这套皮肤自己的整套配件都在这一层下面，摆位也是成套做好的；
    名字对不上时用它兜底，比空手强。
    """
    low = vpath.lower()
    if "/weaponappear/" not in low:
        return ""
    idx = low.rfind("/model/")
    if idx <= 0:
        return ""
    return vpath[:idx + len("/Model/")]


def _gun_tokens(vpath: str) -> List[str]:
    """从主件名里抠出「像枪型号」的片段，用于认同枪族的配件。

    该游戏的配件是按**部件自己的型号**命名的，不跟整枪型号走：
    M4A1 的护木叫 `Han_AR15_lvoa_044`、G3 的护木叫 `Han_G3_mlok_111`、
    弹匣叫 `Mag_76251-30_g3Large_097`。所以只能拿主件名里的片段去碰：
    `Rec_AR_G3_054_...` -> ["AR", "G3"] / `Rec_AR_M4A1-Std_001_...` -> ["AR", "M4A1-Std"]
    """
    stem = os.path.splitext(os.path.basename(vpath))[0]
    parts = stem.split("_")
    tokens: List[str] = []
    for tok in parts[1:]:
        low = tok.lower()
        if not low or low.isdigit() or low in _GENERIC_TOKENS:
            continue
        if len(low) < 2:
            continue
        tokens.append(low)
        if len(tokens) >= 3:
            break
    return tokens


def _segment_hits(tokens: List[str], stem: str) -> List[str]:
    """按片段比对：只认「某个下划线片段以该 token 开头」。

    直接 `token in stem` 会认错（`G3` 的弹匣 `Muz_S-B_Break_..._DarKnight` 里
    的 "ar" 也算命中）；改成片段前缀匹配后，`AR15_lvoa` 能认 `AR`，
    `S-370_M4A1-Std` 能认 `M4A1-Std`，而 `ScarH`/`DarkKnight` 不会误认。
    """
    segs = [x for x in stem.lower().replace("-", "_").split("_") if x]
    hits: List[str] = []
    for tok in tokens:
        t = tok.replace("-", "")
        for seg in segs:
            if seg.replace("-", "").startswith(t):
                hits.append(tok)
                break
    return hits


_GENERIC_TOKENS = frozenset({
    "rec", "bar", "han", "muz", "mag", "sto", "pisg", "frog", "acl", "sco",
    "std", "3p", "1p", "ui", "hd", "p9", "4f", "jx", "nk", "da", "rg", "c3",
})


_FAMILY_SLOT = {
    "receiver": "receiver", "barrel": "barrel", "handguard": "handguard",
    "muzzle": "muzzle", "stock": "stock", "grip": "grip", "foregrip": "tactical",
    "mag": "mag", "optic": "optic", "bipod": "tactical", "tactical": "tactical",
    "other": "other",
}


_PREFIX_FAMILY = {v: k for k, v in FAMILY_OF_PREFIX.items()}

_CACHE_GUESS: Dict[str, str] = {}

# 每把枪「预设里点名要挂、但包里没有网格」的槽位（给界面提示用）
_MISSING: Dict[str, List[str]] = {}

# 只有这些「大件」才值得为了族不一致去换网格；战术/其他小件按预设原样就好
_MAJOR_FAMILIES = {"barrel", "handguard", "stock", "grip", "mag", "muzzle",
                   "optic", "bipod"}

_SLOT_LABEL = {"barrel": "枪管", "handguard": "护木", "muzzle": "枪口",
               "optic": "瞄具", "grip": "握把", "mag": "弹匣", "stock": "枪托",
               "tactical": "战术", "other": "其他", "bipod": "两脚架"}


def missing_parts(base_vpath: str) -> List[str]:
    """上一轮 `preset_loadout()` 里哪些**大件**槽位没找到网格（中文名，去重保序）。

    战术/两脚架这类小件缺了不影响整枪观感，界面提示里不列。
    """
    return [x for x in _MISSING.get(base_vpath or "", []) if x in _MAJOR_LABELS]


_MAJOR_LABELS = {"枪管", "护木", "枪托", "握把", "弹匣", "枪口", "瞄具", "两脚架"}

_CLASS_TOKENS = {"ar", "smg", "lmg", "dmr", "snr", "sg", "hg", "mg", "rifle", "gun",
                 "std", "standard"}


_SHORT_CODE_RE = re.compile(r"^[a-z]{1,2}\d$|^[a-z]\d[a-z]?$")


def _match_tokens(base_vpath: str) -> List[str]:
    """从枪名里拆出「能拿去比部件名」的片段（去掉 AR/SMG/Std 这类通用词）。

    G3 这种两字符型号（`AR_G3_054`）也得留下来，否则一个候选都匹配不到。
    """
    out: List[str] = []
    for tok in _gun_tokens(base_vpath):
        for piece in str(tok).replace("-", "_").split("_"):
            low = piece.strip().lower()
            if not low or low in _CLASS_TOKENS or low in out:
                continue
            if len(low) >= 3 or (len(low) == 2 and _SHORT_CODE_RE.match(low)):
                out.append(low)
    return out


def guess_part_vpath(base_vpath: str, family: str) -> str:
    """挂点表里查不到某件的网格时，按「枪名 + 部件族」在模型目录里捞一个。

    为什么需要：`GunDescTable` 的预设节点给的是**道具 ID**，而挂点表
    （`WeaponPartsMeshSocketNameInfo`）只收录「自己有挂点」的网格，
    M4A1 的默认枪托（道具 13040000114）就不在里面，对应网格叫
    `Sto_A_M4A1-Std_001`。这类件只能按名字对上：同族前缀 + 同枪型号片段。
    """
    if not base_vpath or not family:
        return ""
    key = "%s|%s" % (base_vpath, family)
    if key in _CACHE_GUESS:
        return _CACHE_GUESS[key]
    stem_base = os.path.splitext(os.path.basename(base_vpath))[0].lower()
    code = gun_code(base_vpath).lower().replace("-", "").replace("_", "")
    tokens = set(_gun_tokens(base_vpath))
    prefix = ""
    for pre, fam in FAMILY_OF_PREFIX.items():
        if fam == family:
            prefix = pre
            break
    if not prefix:
        _CACHE_GUESS[key] = ""
        return ""
    got = _guess_candidates(base_vpath, family, limit=1)
    out = got[0] if got else ""
    _CACHE_GUESS[key] = out
    return out


def _guess_candidates(base_vpath: str, family: str, limit: int = 6) -> List[str]:
    """`guess_part_vpath` 的多候选版本：按「同型号 → 同枪名片段」排序返回前 N 个。"""
    if not base_vpath or not family:
        return []
    code = gun_code(base_vpath).lower().replace("-", "").replace("_", "")
    want = set(_match_tokens(base_vpath))
    prefix = ""
    for pre, fam in FAMILY_OF_PREFIX.items():
        if fam == family:
            prefix = pre
            break
    if not prefix:
        return []
    scored: List[Tuple[int, int, str]] = []
    for vpath, _cn, _slot, _gun, _kind in catalog():
        low = vpath.lower()
        if not low.endswith("_3p.uasset"):
            continue
        if "/weaponappear/" in low or low.startswith("../../../deltaforce/content/commerical/"):
            continue                                 # 皮肤件不要，只认基础模型
        base_name = os.path.basename(low)
        if not base_name.startswith(prefix.lower() + "_"):
            continue
        compact = base_name.replace("-", "").replace("_", "")
        score = 0
        if code and code in compact:
            score += 40                             # 同枪型号码：最强证据
        elif want and any(t.replace("-", "").replace("_", "") in compact for t in want):
            score += 20                             # 至少同一把枪（型号片段 ≥3 字符）
        if score <= 0:
            continue
        scored.append((score, len(base_name), vpath))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in scored[:limit]]


def _bounds_cm(base_vpath: str, picks: Sequence[PartSpec]
               ) -> Optional[Tuple[List[float], List[float]]]:
    """把一组配件按 socket 拼起来，只算包围盒（GL×100 = cm，不建网格）。"""
    from core import bbox as _bbox

    base_box = _bbox.box(base_vpath)
    if base_box is None:
        return None
    parts: List[Tuple[PartSpec, MeshLOD]] = []
    for spec in picks:
        box = _bbox.box(spec.vpath)
        if box is None:
            continue
        parts.append((spec, _fake_lod(box)))
    plan = resolve_placements(base_vpath, _fake_lod(base_box), parts)
    lo = np.array([1e9, 1e9, 1e9], np.float64)
    hi = -lo.copy()
    for spec, lod, in parts:
        mat = plan.get(id(spec))
        if mat is None:
            continue
        pos = np.asarray(lod.positions, np.float64) @ mat[:3, :3].T + mat[:3, 3]
        lo = np.minimum(lo, pos.min(axis=0))
        hi = np.maximum(hi, pos.max(axis=0))
    if not np.isfinite(lo).all():
        return None
    return lo.tolist(), hi.tolist()


def _fake_lod(box: np.ndarray) -> MeshLOD:
    """把包围盒包成 8 个角点的 MeshLOD，给 `resolve_placements` 用。"""
    corners = np.array([[x, y, z] for x in (0.0, 1.0) for y in (0.0, 1.0)
                        for z in (0.0, 1.0)], np.float32)
    lo = np.asarray(box[0], np.float32)
    hi = np.asarray(box[1], np.float32)
    return MeshLOD(positions=lo[None, :] + corners * (hi - lo)[None, :])


def _bounds_error_cm(pred, official) -> float:
    """预测包围盒与官方包围盒的最大偏差（cm）。"""
    lo, hi = pred
    origin, extent = official
    pairs = (
        (lo[0] * 100.0, origin[1] - extent[1]),      # 枪尾
        (hi[0] * 100.0, origin[1] + extent[1]),      # 枪口
        (lo[1] * 100.0, origin[2] - extent[2]),      # 下沿
        (hi[1] * 100.0, origin[2] + extent[2]),      # 上沿
        (lo[2] * 100.0, origin[0] - extent[0]),      # 左侧
        (hi[2] * 100.0, origin[0] + extent[0]),      # 右侧
    )
    return max(abs(a - b) for a, b in pairs)


def _arrange_void_parts(base_vpath: str, picks: List[PartSpec],
                        official) -> List[PartSpec]:
    """官方预设里「有挂点却没网格」的默认件：在候选里挑尺寸最吻合的组合。

    只用**同一把枪**的候选（`_guess_candidates`），所以不会出现拿别的枪的
    枪托凑数；挑选标准是官方包围盒表，属于纯数据拟合。
    """
    if official is None or not picks:
        return picks
    work = list(picks)
    first = _bounds_cm(base_vpath, work)
    if first is None:
        return picks
    best_err = _bounds_error_cm(first, official)
    for _pass in range(2):
        improved = False
        for index, spec in enumerate(work):
            family = mount_family(spec.vpath, spec.slot)
            for cand in _guess_candidates(base_vpath, family, limit=8):
                if cand == spec.vpath:
                    continue
                trial = list(work)
                trial[index] = PartSpec(vpath=cand, slot=spec.slot,
                                        name=os.path.basename(cand),
                                        socket=spec.socket, slot_fit=True)
                got = _bounds_cm(base_vpath, trial)
                if got is None:
                    continue
                err = _bounds_error_cm(got, official)
                if err < best_err - 0.05:
                    best_err, work, improved = err, trial, True
                    break
        if not improved:
            break
    return work


def preset_loadout(base_vpath: str) -> List[PartSpec]:
    """**直接从游戏预设表里抄**：这把枪在官方装配树里默认装哪几件。

    `GunDescTable` 里以这把枪的机匣为根节点的 DesId 就是官方预设；
    每个节点的 `ParentSocketId` 说明了它插在哪个挂点上。
    道具 ID 查不到网格的（见 `guess_part_vpath`）按名字兜一个。
    """
    from core import presets as _presets            # 延迟导入：没装游戏也能跑界面

    if not base_vpath:
        return []
    item = _sockets.item_of_mesh(base_vpath)
    if not item:
        return []
    desids = _presets.presets_of_item(item)
    if not desids:
        return []
    best: Optional[Tuple[int, int, List[PartSpec], object]] = None
    misses: List[str] = []
    for desid in desids:
        picks: List[PartSpec] = []
        filled = 0
        mismatched = 0
        local_misses: List[str] = []
        nodes = _presets.dedup(_presets.nodes_of(desid))
        # 节点索引 → 该节点的道具 ID：记住「这件挂在谁身上」，避免靠族名乱猜父件。
        node_item_of = {int(n[0]): int(n[2]) for n in nodes}
        for idx, pidx, node_item, psock in nodes:
            if pidx in (0, None):
                continue                                 # 根节点就是主件
            sock_name = _sockets.socket_id_name(psock)
            family0 = SOCKET_FAMILY.get((sock_name or "").lower(), "")
            # 先问游戏的道具资产表（`CommonItemAssets_Weapon`）——这是权威答案，
            # 连没有挂点、因此不在挂点表里的枪托/小握把也能查到。
            vpath = _items.resolve(node_item)
            meshes = []
            if not vpath:
                meshes = [m for m in _sockets.item_meshes(node_item) if "_ui" not in m]
                meshes.sort(key=lambda m: (not m.endswith("_3p"), len(m)))
                vpath = _presets.vpath_of(meshes[0]) if meshes else ""
            # 预设节点给的道具，挂点表里偶尔把它映射到**别的族**的网格
            # （例：ScarH 默认枪托的道具 13040000193 指向 Other_minimi-1913adapter），
            # 这种一律换成「同族 + 同枪」的候选，否则枪上会多出个不相干的小件。
            if (vpath and family0 in _MAJOR_FAMILIES
                    and mount_family(vpath, "") in _MAJOR_FAMILIES
                    and mount_family(vpath, "") != family0):
                # 只有「两边都是大件」才算挂错东西。预设里的握把底座
                # （other_psgbass1）、弹匣底板（other_quickdraw）本来是"other"，
                # 换成一个真握把/真弹匣会多出第二把，看着就像浮在半空。
                swapped = guess_part_vpath(base_vpath, family0)
                if swapped:
                    vpath = swapped
                else:
                    mismatched += 1
            if not vpath:
                vpath = guess_part_vpath(base_vpath, family0)
            if not vpath:
                label = _SLOT_LABEL.get(_FAMILY_SLOT.get(family0, family0), family0)
                if label and label not in local_misses:
                    local_misses.append(label)
                continue
            family = mount_family(vpath, "")
            slot = _FAMILY_SLOT.get(family, "other")
            if any(p.slot == slot and p.socket == sock_name for p in picks):
                continue
            picks.append(PartSpec(vpath=vpath, slot=slot,
                                  name=os.path.basename(vpath),
                                  socket=sock_name,
                                  slot_fit=True,
                                  parent_item=int(node_item_of.get(int(pidx), 0) or 0),
                                  parent_socket_id=int(psock or 0)))
            filled += 1
        # 先比「装上的件数」，再比「族对不上的次数」——都不对时才退回件数多的那个
        major_misses = len([x for x in local_misses if x in _MAJOR_LABELS])
        # 候选分两档：大件齐全且件数像样的优先；否则按「件数 - 缺口惩罚」挑
        if filled >= 4 and major_misses == 0:
            rank = (2, filled, -mismatched)
        elif filled:
            rank = (1, filled - 4 * major_misses, -mismatched)
        else:
            continue
        if best is None or rank > best[0]:
            best = (rank, picks, _presets.bounds_of(desid))
            misses = list(local_misses)
    if best is None:
        _MISSING.pop(base_vpath, None)
        return []
    picks = best[1]
    picks = _dedupe_major(picks)
    _MISSING[base_vpath] = misses
    try:
        from core import bbox as _bbox
        _bbox.save()
    except Exception:                              # noqa: BLE001
        pass
    for spec in picks:
        spec.slot_fit = True
        spec.auto_scale = None
    return picks


_DUP_FORBIDDEN = {"stock", "barrel", "handguard", "muzzle", "grip", "foregrip", "bipod"}


def _dedupe_major(picks: Sequence[PartSpec]) -> List[PartSpec]:
    """同一套方案里，枪托 / 枪管 / 护木 / 枪口 / 握把 / 前握把 / 两脚架只留第一件。

    预设表偶尔把同一件东西拆成两个节点（Sto_C_DTMDR + Sto_S_DTMDR 这种前后两段），
    两段都装就会互相插进去。弹匣和瞄具不在此列：加长弹匣 + 底板、主镜 + 红点
    都是游戏里的正常搭配。
    """
    out: List[PartSpec] = []
    seen: set = set()
    for spec in picks:
        fam = mount_family(spec.vpath, spec.slot)
        if fam in _DUP_FORBIDDEN:
            if fam in seen:
                continue
            seen.add(fam)
        out.append(spec)
    return out


def official_loadout(base_vpath: str, *, same_dir_first: bool = True,
                     limit_per_slot: int = 1) -> List[PartSpec]:
    """给主件配一套「官方」配件。

    优先走**游戏自己的预设表**（`preset_loadout`，来自 `GunDescTable`，
    每件连挂在哪个 socket 上都写好了）。表里没有（皮肤枪 / 新枪）才退回
    按命名规则猜：主件名片段命中 + 槽位前缀打分。
    """
    if not base_vpath:
        return []
    try:
        picks = preset_loadout(base_vpath)
        if len(picks) >= 2:
            return picks
    except Exception:                                # noqa: BLE001
        picks = []
    code = gun_code(base_vpath)
    base_dir = _model_dir(base_vpath)
    tokens = _gun_tokens(base_vpath)
    if not tokens:
        return []
    skin = ""
    tail = os.path.splitext(os.path.basename(base_vpath))[0]
    if "_" in tail:
        skin = tail.rsplit("_3P", 1)[0].rsplit("_1P", 1)[0].split("_")[-1]

    compact_code = code.lower().replace("-", "").replace("_", "")
    found: Dict[str, List[Tuple[int, str]]] = {}
    for vpath, _cn, _slot, _gun, _kind in catalog():
        if not vpath.lower().endswith("_3p.uasset"):
            continue
        stem = os.path.basename(vpath)
        hits = _segment_hits(tokens, stem)
        if not hits:
            continue
        prefix = stem.split("_", 1)[0]
        if prefix not in _SLOT_PREFIXES:
            continue
        slot = _PREFIX_SLOT[prefix]
        if slot == "receiver":
            continue                      # 主件自己不算配件
        # 命中的片段越长越可信；同目录 / 同皮肤再加分。
        score = sum(10 + len(t) for t in hits)
        # 完整型号码（M4A1-Std_001）命中是最强信号：原厂件优先。
        compact_stem = stem.lower().replace("-", "").replace("_", "")
        if compact_code and compact_code in compact_stem:
            score += 30
        if same_dir_first and _model_dir(vpath) == base_dir:
            score += 6
        if skin and skin in stem:
            score += 4
        found.setdefault(slot, []).append((score, vpath))

    out: List[PartSpec] = []
    for slot in ("barrel", "handguard", "muzzle", "optic", "grip", "mag", "stock"):
        cands = sorted(found.get(slot, []), key=lambda it: (-it[0], len(it[1]), it[1]))
        for _score, vpath in cands[:limit_per_slot]:
            out.append(PartSpec(vpath=vpath, slot=slot,
                                name=os.path.basename(vpath), slot_fit=True))

    if len(out) < 2:
        # 名对上太少：退一步用「同一个皮肤目录里的整套件」——游戏的外观皮肤
        # 每个都带自己的全套模型，摆位也是成套做好的。
        skin_dir = _skin_kit_dir(base_vpath)
        if skin_dir:
            for vpath, _cn, slot, _gun, kind in catalog():
                if kind != "part" or not vpath.lower().startswith(skin_dir.lower()):
                    continue
                if not vpath.lower().endswith("_3p.uasset"):
                    continue
                if any(p.slot == slot for p in out):
                    continue
                out.append(PartSpec(vpath=vpath, slot=slot,
                                    name=os.path.basename(vpath), slot_fit=True))
    return out


def snap_socket(spec: PartSpec, parent_vpath: str = "") -> str:
    """给配件挑一个挂点并写回 `spec.socket`（返回挂点名，找不到返回空串）。

    只是「填名字」，真正的位置在 `assemble` 里按 socket 链算。
    """
    if not parent_vpath:
        return ""
    family = mount_family(spec.vpath, spec.slot)
    hit = find_socket(parent_vpath, socket_candidates(family), prefer=spec.socket)
    if hit is None:
        return ""
    spec.socket = hit[0]
    return hit[0]


def auto_fit(spec: PartSpec, base_lod: MeshLOD, part_lod: MeshLOD,
             base_vpath: str = "") -> PartSpec:
    """配件落位（已改成挂点式）。

    * 主件上有对应挂点 → 只填 `spec.socket`，位置交给 `assemble`；
    * 没有挂点（自定义模型 / 皮肤件）→ 退回包围盒兜底，写进 `spec.offset`。

    旧版本这里是「按包围盒把配件拉到主件旁边」，结果每个件都偏几厘米到几十厘米，
    正是「配件全部位置错误」的根源。
    """
    if base_vpath and snap_socket(spec, base_vpath):
        spec.offset = [0.0, 0.0, 0.0]
        spec.anchored = False
        return spec
    base_lo, base_hi = bounds(base_lod)
    part_lo, part_hi = bounds(part_lod)
    fallback = _bbox_fallback(spec, base_lod, part_lod, np.eye(4, dtype=np.float32))
    _ = (base_lo, base_hi, part_lo, part_hi)
    spec.offset = [float(fallback[0, 3]), float(fallback[1, 3]), float(fallback[2, 3])]
    spec.anchored = False
    return spec


def fit_to_slot(spec: PartSpec, base_lod: MeshLOD, part_lod: MeshLOD,
                base_vpath: str = "") -> PartSpec:
    """「自动对齐」：清掉手调，按官方挂点重新吸回去（等比 = 1）。"""
    spec.offset = [0.0, 0.0, 0.0]
    spec.rot = [0.0, 0.0, 0.0]
    spec.scale = 1.0
    spec.auto_scale = None
    spec.anchored = True
    spec.socket = ""
    if base_vpath:
        snap_socket(spec, base_vpath)
    _ = (base_lod, part_lod)
    return spec


# --------------------------------------------------------------------------- #
# 规则化摆位（让「官方配件」一装上去就像游戏里的样子）
# --------------------------------------------------------------------------- #
_LAYOUT_ORDER = ("barrel", "handguard", "muzzle", "stock", "mag", "grip",
                 "optic", "tactical", "other")


def _axis_of(size: np.ndarray) -> int:
    """枪的长轴：取 x/y/z 里跨度最大的那个（该游戏的枪基本都沿 x）。"""
    return int(np.argmax(size))



def snap_extremes(base_lod: MeshLOD,
                  parts: Sequence[Tuple[PartSpec, MeshLOD]]
                  ) -> Dict[str, np.ndarray]:
    """只把「明显需要贴到端头」的件挪过去（枪口 → 最前端、瞄具 → 最上方）。

    该游戏的配件绝大多数是在**同一套局部坐标**里做好的（枪管、护木、枪托、
    弹匣、握把直接叠就对），但枪口/瞄具这类是各自独立的几何，原点是自己的：
    比如 M4A1 的枪管伸到 x≈0.469，而补偿器本体只占 x[-0.003,0.057]，
    不挪就会缩在机匣中间。所以这里只对这两个槽位做端头吸附，其余一律恒等，
    避免像 `plan_layout` 那样把所有件都推一遍、把枪拉成 1.6 米。
    """
    base_lo, base_hi = bounds(base_lod)
    size = np.maximum(base_hi - base_lo, 1e-4)
    ax = _axis_of(size)
    up = 1 if ax != 1 else 2
    gun_lo, gun_hi = base_lo.copy(), base_hi.copy()
    out: Dict[str, np.ndarray] = {}
    # 枪口要接在「枪管/护木」的轴线上，而不是机匣中心线上（枪管一般偏上）
    axis_lo: Optional[np.ndarray] = None
    axis_hi: Optional[np.ndarray] = None

    order = {"barrel": 0, "handguard": 1, "stock": 2, "mag": 3,
             "grip": 4, "tactical": 5, "muzzle": 6, "optic": 7}
    for spec, lod in sorted(parts, key=lambda it: order.get(it[0].slot, 9)):
        plo, phi = bounds(lod)
        k = float(spec.auto_scale or 1.0) * float(spec.scale or 1.0)
        plo_k, phi_k = plo * k, phi * k
        c = (plo_k + phi_k) * 0.5
        t = np.zeros(3, np.float32)
        if spec.slot == "muzzle":
            t[ax] = gun_hi[ax] - plo_k[ax]
            ref_lo = axis_lo if axis_lo is not None else base_lo
            ref_hi = axis_hi if axis_hi is not None else base_hi
            for i in range(3):
                if i != ax:
                    t[i] = (ref_lo[i] + ref_hi[i]) * 0.5 - c[i]
        elif spec.slot == "optic":
            t[up] = gun_hi[up] - plo_k[up]
            t[ax] = (base_lo[ax] + base_hi[ax]) * 0.5 - c[ax]
        out[id(spec)] = t
        if spec.slot in ("barrel", "handguard"):
            axis_lo = plo_k + t
            axis_hi = phi_k + t
        if spec.slot in ("barrel", "handguard", "muzzle"):
            gun_hi[ax] = max(gun_hi[ax], phi_k[ax] + t[ax])
            gun_lo[ax] = min(gun_lo[ax], plo_k[ax] + t[ax])
        elif spec.slot == "stock":
            gun_lo[ax] = min(gun_lo[ax], plo_k[ax] + t[ax])
        elif spec.slot == "optic":
            gun_hi[up] = max(gun_hi[up], phi_k[up] + t[up])
    return out


def plan_layout(base_lod: MeshLOD,
                parts: Sequence[Tuple[PartSpec, MeshLOD]]
                ) -> Dict[str, np.ndarray]:
    """按「边缘对接」的规则算每个配件的位移（不需要任何挂点数据）。

    游戏里一把枪就是若干块拼起来的，块与块的接缝很固定：
    枪管接机匣前端、枪口接枪管前端、枪托接机匣后端、弹匣插机匣下方、
    握把在机匣前下方、瞄具骑在机匣上方。这里就用包围盒把这些接缝对齐，
    比「包围盒中心对准锚点」稳定得多，也顺手解决跨枪族比例问题。

    返回 `{id(spec): translate}`（用 id 当键，避免 PartSpec 不可哈希）。
    """
    base_lo, base_hi = bounds(base_lod)
    size = np.maximum(base_hi - base_lo, 1e-4)
    ax = _axis_of(size)
    cross = [i for i in range(3) if i != ax]
    up = 1 if ax != 1 else 2          # 竖直方向：x 为长轴时是 y
    out: Dict[int, np.ndarray] = {}
    gun_lo, gun_hi = base_lo.copy(), base_hi.copy()

    for spec, lod in sorted(parts, key=lambda it: _LAYOUT_ORDER.index(
            it[0].slot if it[0].slot in _LAYOUT_ORDER else "other")):
        plo, phi = bounds(lod)
        k = float(spec.auto_scale or 1.0) * float(spec.scale or 1.0)
        c = (plo + phi) * 0.5 * k
        plo_k, phi_k = plo * k, phi * k
        t = np.zeros(3, np.float32)
        for i in cross:
            t[i] = (base_lo[i] + base_hi[i]) * 0.5 - c[i]
        slot = spec.slot
        if slot == "barrel":
            t[ax] = gun_hi[ax] - plo_k[ax]
        elif slot == "handguard":
            t[ax] = gun_hi[ax] - plo_k[ax] - size[ax] * 0.02
        elif slot == "muzzle":
            t[ax] = gun_hi[ax] - plo_k[ax]
        elif slot == "stock":
            t[ax] = gun_lo[ax] - phi_k[ax]
        elif slot == "mag":
            t[up] = base_lo[up] - phi_k[up]
            t[ax] = base_lo[ax] + size[ax] * 0.32 - c[ax]
        elif slot == "grip":
            t[up] = base_lo[up] - phi_k[up] + size[up] * 0.06
            t[ax] = base_lo[ax] + size[ax] * 0.18 - c[ax]
        elif slot == "optic":
            t[up] = base_hi[up] - plo_k[up]
            t[ax] = base_lo[ax] + size[ax] * 0.42 - c[ax]
        elif slot == "tactical":
            t[up] = base_lo[up] - phi_k[up]
            t[ax] = base_hi[ax] - size[ax] * 0.25 - c[ax]
        else:
            t[ax] = (base_lo[ax] + base_hi[ax]) * 0.5 - c[ax]
        out[id(spec)] = t
        # 往前伸的件（枪管/枪口/护木）会把「当前最长处」往外推，枪口就能接在枪管前面
        if slot in ("barrel", "handguard", "muzzle"):
            gun_hi[ax] = max(gun_hi[ax], phi_k[ax] + t[ax])
            gun_lo[ax] = min(gun_lo[ax], plo_k[ax] + t[ax])
        elif slot == "stock":
            gun_lo[ax] = min(gun_lo[ax], plo_k[ax] + t[ax])
    return out


# --------------------------------------------------------------------------- #
# 「模型目录」：建索引时算好，界面直接查（避免每次开弹窗都翻 90 万条路径）
# --------------------------------------------------------------------------- #
MODEL_SUFFIXES = ("_3p.uasset", "_1p.uasset", "_ui.uasset", "_lay.uasset", "_hd.uasset")
_PART_PREFIXES = ("Rec", "Bar", "Han", "Muz", "Mag", "Sto", "PisG", "FroG", "Acl",
                  "Sco", "SM", "SKM", "Pis", "Att", "Dev", "Other", "Bip")


def catalog_rows(paths: Iterable[str]) -> Iterable[Tuple[str, str, str, str, str]]:
    """-> [(vpath, 游戏内中文名, 槽位, 枪族码, kind), …]

    只收「像枪械部件/主件」的路径（前缀命中 + 3P/1P/UI 变体），
    名字用 `cnnames.resolve_cn` 解析；没名字的也照存（cn 空串），
    界面里再决定是否显示。
    """
    from core import cnnames as _cn
    meshes = _mesh_vpaths()
    for vpath in paths:
        low = vpath.lower()
        if not low.endswith('.uasset'):
            continue
        stem = os.path.basename(vpath)
        # 贴图（_C_HD/_N_HD/_MRA_HD）和 UI 图标跟模型同目录、同前缀，
        # 只靠前缀会把它们当成「部件」塞进目录，选主件时就会挑到一张贴图。
        bare = stem[:-len(".uasset")] if stem.lower().endswith(".uasset") else stem
        tail = bare.rsplit("_", 1)[-1].lower()
        if tail not in ("3p", "1p") and not (meshes and (vpath in meshes or vpath.lstrip('./') in meshes)):
            continue
        # 「只装有网格的」：mesh_catalog.json 里没有的资产基本是空壳/占位，
        # 装到枪上只会得到一个空节点，直接从目录里剔掉。
        if meshes and vpath.lstrip("./") not in meshes and vpath not in meshes:
            continue
        prefix = stem.split("_", 1)[0]
        if prefix not in _PART_PREFIXES:
            continue
        if prefix in ("SM", "SKM") and not any(p in low for p in ("/models/weapons/", "/weaponappear/")):
            continue
        slot = guess_slot(vpath)
        try:
            cn = _cn.resolve_cn(vpath) or ""
        except Exception:                                        # noqa: BLE001
            cn = ""
        kind = "base" if slot == "receiver" else "part"
        yield (vpath, cn, slot, gun_code(vpath), kind)


_MESH_SET: Dict[str, object] = {"rows": None}


def _mesh_vpaths() -> set:
    """mesh_catalog.json 里的模型路径集合（只读一次）。"""
    if _MESH_SET.get("rows") is not None:
        return _MESH_SET["rows"]                    # type: ignore[return-value]
    rows: set = set()
    try:
        from core import loader as _ld
        cat = _ld.catalog()
        for vpath, cls in cat.items():
            if "Mesh" in (cls or ""):
                rows.add(vpath)
                rows.add(vpath.lstrip("./"))
    except Exception:                                        # noqa: BLE001
        rows = set()
    _MESH_SET["rows"] = rows
    return rows


_CATALOG_CACHE: Dict[str, object] = {"key": None, "rows": None}


def catalog() -> List[Tuple[str, str, str, str, str]]:
    """读索引库里的模型目录；老库没有就现场补一份（几秒）。"""
    from core import indexdb as _db
    key = _db.db_path()
    if _CATALOG_CACHE.get("key") == key and _CATALOG_CACHE.get("rows") is not None:
        return _CATALOG_CACHE["rows"]                   # type: ignore[return-value]
    _db.ensure_models()
    try:
        if _db.models_rev() != _db.MODELS_REV or _db.models_look_stale():
            # 老库里把 _C_HD/_N_HD/_UI 也当成了模型，重刷一遍（1~2 秒）
            _db.refresh_models()
    except Exception:                                        # noqa: BLE001
        pass
    rows = _db.load_models()
    if not rows:
        from core import loader as _ld
        rows = list(catalog_rows(_ld.index().keys()))
    _CATALOG_CACHE["key"] = key
    _CATALOG_CACHE["rows"] = rows
    return rows


def display_name(vpath: str, rows: Optional[List[Tuple[str, str, str, str, str]]] = None) -> str:
    """给界面用的名字：优先游戏内中文名，其次文件名。"""
    rows = rows if rows is not None else catalog()
    for r in rows:
        if r[0] == vpath:
            return r[1] or os.path.splitext(os.path.basename(vpath))[0]
    return os.path.splitext(os.path.basename(vpath))[0]


def bases(query: str = "", limit: int = 400) -> List[Tuple[str, str, str, str, str]]:
    """主件（机匣/整枪）列表，按中文名或路径过滤；有中文名的排前面。"""
    q = (query or "").strip().lower()
    rows = [r for r in catalog()
            if r[4] == "base" and r[0].lower().endswith("_3p.uasset")
            and (not q or q in r[1].lower() or q in r[0].lower())]
    rows.sort(key=lambda r: (0 if r[1] else 1, 0 if "_3P" in r[0] else 1, len(r[0])))
    return rows[:limit]


def parts(slot: str = "", query: str = "", limit: Optional[int] = None
          ) -> List[Tuple[str, str, str, str, str]]:
    """配件列表（可按槽位/关键字过滤），有中文名的排前面。"""
    q = (query or "").strip().lower()
    rows = [r for r in catalog()
            if r[4] == "part"
            and (not slot or r[2] == slot)
            and (not q or q in r[1].lower() or q in r[0].lower() or q in r[3].lower())]
    rows.sort(key=lambda r: (0 if r[1] else 1, 0 if "_3P" in r[0] else 1, len(r[0])))
    return rows[:limit] if limit is not None else rows
