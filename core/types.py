"""Shared data contract between the pak reader, uasset parser, texture loader,
renderer and the FluentPy UI.

Nothing in here touches PySide6 -- keep it importable from plain python so the
parsers can be unit-tested head-less.

Coordinate conventions
----------------------
* UE stores mesh data in centimetres, +X forward, +Y right, +Z up, left handed.
* The renderer wants metres and OpenGL axes: x = ue.y, y = ue.z, z = ue.x.
  Use `ue_to_gl()` on positions/normals once, at load time.
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# --------------------------------------------------------------------------- #
# mesh
# --------------------------------------------------------------------------- #
@dataclass
class Section:
    """One draw call of a mesh LOD, bound to one material slot."""
    material_path: str = ""          # virtual pak path of the UMaterialInstance
    first_index: int = 0
    num_triangles: int = 0
    first_vertex: int = 0
    num_vertices: int = 0
    # legacy UE4 fields, filled when the mesh uses FixedFunction sections
    index_base: int = 0
    triangle_sort: int = 0


@dataclass
class MeshLOD:
    """One LOD of a static/skeletal mesh, already in GL space."""
    positions: np.ndarray = None      # (N, 3) float32, metres
    normals: np.ndarray = None        # (N, 3) float32
    uvs: np.ndarray = None            # (N, 2) float32  (UV channel 0)
    tangents: np.ndarray = None       # (N, 4) float32, w = sign
    indices: np.ndarray = None        # (M,) uint32 (triangles)
    sections: List[Section] = field(default_factory=list)
    # 顶点缓冲里所有 UV 通道（N, tc, 2）。该游戏的资产普遍有 2~3 套 UV，
    # 通道 0 往往是光照图/AO 用的，材质真正采样的是通道 1 或 2；
    # 只留通道 0 就会出现「贴图在，但位置全错」。
    uv_sets: np.ndarray = None
    # skeletal meshes only
    bone_weights: np.ndarray = None   # (N, 4) float32
    bone_indices: np.ndarray = None   # (N, 4) uint8/uint16
    bones: List[str] = field(default_factory=list)

    @property
    def uv_channel_count(self) -> int:
        sets = getattr(self, "uv_sets", None)
        if sets is not None and getattr(sets, "ndim", 0) == 3:
            return int(sets.shape[1])
        return 1 if self.uvs is not None else 0

    def uv(self, channel: int = 0) -> Optional[np.ndarray]:
        """UV channel ``channel`` (falls back to channel 0 / zeros)."""
        sets = getattr(self, "uv_sets", None)
        if sets is not None and getattr(sets, "ndim", 0) == 3:
            if 0 <= channel < sets.shape[1]:
                return sets[:, channel, :]
            return sets[:, 0, :]
        return self.uvs

    @property
    def triangle_count(self) -> int:
        return 0 if self.indices is None else len(self.indices) // 3

    @property
    def vertex_count(self) -> int:
        return 0 if self.positions is None else len(self.positions)


@dataclass
class Mesh:
    """A whole mesh asset (.uasset) with every LOD we could decode."""
    name: str = ""                    # asset name, e.g. SM_Mag_AK74_..._3P
    pak_path: str = ""                # virtual path inside the pak mount
    lods: List[MeshLOD] = field(default_factory=list)
    bounds_center: Optional[Tuple[float, float, float]] = None
    bounds_extent: Optional[Tuple[float, float, float]] = None
    source_format: str = ""           # "StaticMesh" | "SkeletalMesh"
    material_paths: List[str] = field(default_factory=list)  # native slots, including later LODs
    bone_parents: List[int] = field(default_factory=list)
    reference_pose: Optional[np.ndarray] = None  # UE local Qxyzw / Txyz cm / Sxyz

    def lod(self, i: int = 0) -> Optional[MeshLOD]:
        return self.lods[i] if 0 <= i < len(self.lods) else None

    @property
    def max_lod(self) -> Optional[MeshLOD]:
        return self.lods[-1] if self.lods else None


# --------------------------------------------------------------------------- #
# materials & textures
# --------------------------------------------------------------------------- #
@dataclass
class Texture:
    name: str = ""                    # T_..._BaseColorMap
    pak_path: str = ""
    width: int = 0
    height: int = 0
    rgba: np.ndarray = None           # (H, W, 4) uint8, already decoded
    srgb: bool = True
    source_format: str = ""           # "BC7" | "BC1" | "R8G8B8A8" | ...

    def thumbnail(self, size: int = 64) -> np.ndarray:
        """Nearest-neighbour downscale used by the asset browser."""
        if self.rgba is None:
            return np.zeros((size, size, 4), np.uint8)
        step = max(1, max(self.width, self.height) // size)
        return np.ascontiguousarray(self.rgba[::step, ::step][:size, :size])


@dataclass
class Material:
    """Resolved material: static defaults + scalar/vector parameter overrides."""
    name: str = ""
    pak_path: str = ""                # UMaterialInstanceConstant asset
    parent: str = ""                  # UMaterialInterface it inherits from
    base_color_texture: str = ""      # pak path of the albedo T_ asset
    normal_texture: str = ""
    orm_texture: str = ""             # packed occlusion/roughness/metallic
    emissive_texture: str = ""
    metallic: float = 0.0             # scalar override (0..1)
    roughness: float = 0.5
    base_color: Tuple[float, float, float, float] = (1, 1, 1, 1)
    emissive: Tuple[float, float, float] = (0, 0, 0)
    scalar_params: Dict[str, float] = field(default_factory=dict)
    vector_params: Dict[str, Tuple[float, ...]] = field(default_factory=dict)
    texture_params: Dict[str, str] = field(default_factory=dict)
    two_sided: bool = False
    blend_mode: str = "Opaque"        # Opaque | Masked | Translucent | Additive
    # Names present in the resolved parent shader, when that asset is readable.
    # Instances can retain unused effect parameters after changing parents.
    parent_parameter_names: Optional[Tuple[str, ...]] = None
    # final uniforms consumed by the renderer, already merged with UI overrides
    def uniforms(self) -> Dict[str, object]:
        return dict(metallic=self.metallic, roughness=self.roughness,
                    base_color=self.base_color, emissive=self.emissive)

    @property
    def is_untextured_overlay(self) -> bool:
        """UE 里那块「白色的一大坨」：半透明/Masked 而且一张贴图都没有的面。

        这类材质在游戏里是贴屏面（手机屏、手表序列帧、UI 卡片），靠 Canvas 或者
        渲染目标出图；我们手上只有静态贴图，画出来就是一整片纯白盖住模型本体。
        默认隐藏，检查器里可以临时打开看几何 —— 见 render/viewer.py 的
        `show_untextured`。判定只看「一张贴图都没有」，避免把正常半透明件误伤。
        """
        if (self.base_color_texture or self.emissive_texture
                or self.orm_texture or self.normal_texture):
            return False
        blend = (self.blend_mode or "").lower()
        if blend in ("masked", "translucent", "additive", "modulate", "alpha"):
            return True
        name = (self.name or "").lower()
        return any(tok in name for tok in ("screen", "sequence", "ui_", "_ui"))


@dataclass
class ModelBundle:
    """Everything the viewer needs for one asset in the browser."""
    mesh: Optional[Mesh] = None
    materials: List[Material] = field(default_factory=list)
    textures: List[Texture] = field(default_factory=list)
    display_name: str = ""            # English display / asset name
    display_name_cn: str = ""         # Chinese name resolved from DataTables
    icon_path: str = ""               # optional UI icon asset
    material_note: str = ""           # 材质从哪个变体借来的（3P 缺图时借 UI 的）


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def ue_to_gl(arr: np.ndarray) -> np.ndarray:
    """UE (x fwd, y right, z up, cm, 左手) -> GL (x right, y up, z back, m, 右手).

    注意第三行是 `-a[:, 0]` 而不是 `a[:, 0]`：UE 是左手系，GL 是右手系，
    必须**翻一个轴**（手性保持）才能让模型不是镜像的。早先写成
    `(y, z, x)` 这种循环置换，矩阵行列式虽然是 +1，但左手系的基映到右手系后
    整只模型看起来就是「镜像」的：贴图左右反着长、贴花上的字是反的。
    """
    if arr is None:
        return arr
    a = np.asarray(arr, dtype=np.float32).reshape(-1, 3)
    out = np.empty_like(a)
    out[:, 0] = a[:, 1] * 0.01
    out[:, 1] = a[:, 2] * 0.01
    out[:, 2] = -a[:, 0] * 0.01
    return out


def ue_dir_to_gl(arr: np.ndarray) -> np.ndarray:
    """Same axis swap without the centimetre -> metre scale."""
    if arr is None:
        return arr
    a = np.asarray(arr, dtype=np.float32).reshape(-1, 3)
    out = np.empty_like(a)
    out[:, 0] = a[:, 1]
    out[:, 1] = a[:, 2]
    out[:, 2] = -a[:, 0]
    return out
