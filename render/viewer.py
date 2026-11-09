"""VertexViewer OpenGL renderer: PBR + stylised looks + lighting, PySide6 widget.

Public entry points
-------------------
``MeshViewer``
    A ``QOpenGLWidget`` with the API the FluentPy shell drives.  It never
    assumes it is visible: :meth:`MeshViewer.capture` renders through a private
    offscreen context, so unattended verification works on a headless box.

``OffscreenViewer``
    Pure offscreen renderer (QOffscreenSurface + FBO).  Same state object as
    the widget, no window required.

The renderer keeps every piece of state in a plain :class:`SceneState`
dataclass, so a GL object never outlives the context that made it.

Pipeline
--------
1. optional shadow map for the key light (depth-only, PCF 3x3 at sample time)
2. scene into a 4x MSAA RGBA16F FBO: procedural background, meshes
   (one draw per mesh section), optional inverted-hull outline pass
3. resolve MSAA -> RGBA16F texture
4. post pass: exposure -> bloom -> ACES -> sRGB -> vignette -> grain
"""
from __future__ import annotations

import ctypes
import math
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.types import Material, Mesh, MeshLOD, Section, Texture  # noqa: E402

from . import lighting as L  # noqa: E402
from .postfx import (  # noqa: E402
    BACKGROUND_IDS, STYLE_IDS, STYLE_NAMES, STYLE_PARAMS,
    normalize_style, style_id, style_params,
)

try:  # PyOpenGL is the only non-Qt dependency of this package
    from OpenGL import GL
except Exception as _exc:  # pragma: no cover - only on broken installs
    GL = None
    _GL_IMPORT_ERROR = _exc
else:
    _GL_IMPORT_ERROR = None

from PySide6.QtCore import QPointF, QSize, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QGuiApplication, QOffscreenSurface, QOpenGLContext, QSurfaceFormat,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget  # noqa: E402

SHADER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shaders")

MESH_VERTEX_LAYOUT = 12          # pos3 nrm3 uv2 tan4
SHADOW_SIZE = 4096
DEFAULT_CAPTURE_SIZE = (1280, 720)
DEFAULT_BACKGROUND = "studio"


# --------------------------------------------------------------------------- #
# GL / Qt bootstrap helpers
# --------------------------------------------------------------------------- #
def make_surface_format(samples: int = 0) -> QSurfaceFormat:
    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setSamples(samples)
    fmt.setSwapInterval(0)
    return fmt


def configure_surface_format(samples: int = 0) -> QSurfaceFormat:
    """Call before creating QApplication/QOpenGLWidgets (safe to call again)."""
    fmt = make_surface_format(samples)
    if QGuiApplication.instance() is None:
        QSurfaceFormat.setDefaultFormat(fmt)
    return fmt


def _shader_source(name: str) -> str:
    path = os.path.join(SHADER_DIR, name)
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _require_gl() -> None:
    if GL is None:
        raise RuntimeError(
            f"PyOpenGL is not available ({_GL_IMPORT_ERROR}). "
            "Install it with: python -m pip install PyOpenGL "
            "-i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com"
        )


def _as_texture_array(rgba: Any) -> Optional[np.ndarray]:
    """Coerce a Texture / (H,W,3|4) array into a contiguous uint8 RGBA array."""
    if rgba is None:
        return None
    if isinstance(rgba, Texture):
        rgba = rgba.rgba
    elif hasattr(rgba, "rgba"):        # 例如 _OverrideTexture 这类轻量包装
        rgba = getattr(rgba, "rgba")
    if rgba is None:
        return None
    arr = np.asarray(rgba)
    if arr.size == 0 or arr.dtype.kind not in "buif":
        return None
    if arr.dtype.kind == "f":
        arr = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=0.0)
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0.0, 1.0 if arr.dtype.kind == "f" else 255.0)
        arr = (arr * (255.0 if arr.dtype.kind == "f" else 1.0) + 0.5).astype(np.uint8) \
            if arr.dtype.kind == "f" else arr.astype(np.uint8)
    if arr.ndim == 2:
        arr = np.repeat(arr[:, :, None], 3, axis=2)
    if arr.ndim != 3:
        return None
    if arr.shape[2] == 1:
        arr = np.repeat(arr, 4, axis=2)
    elif arr.shape[2] == 3:
        alpha = np.full(arr.shape[:2] + (1,), 255, np.uint8)
        arr = np.concatenate([arr, alpha], axis=2)
    elif arr.shape[2] > 4:
        arr = arr[:, :, :4]
    elif arr.shape[2] != 4:
        return None
    return np.ascontiguousarray(arr, dtype=np.uint8)


def _basename_key(path: str) -> str:
    if not path:
        return ""
    p = str(path).replace("\\", "/").rstrip("/")
    p = p.rsplit("/", 1)[-1]
    if "." in p:
        p = p.rsplit(".", 1)[0]
    return p.lower()


# --------------------------------------------------------------------------- #
# mesh preparation (numpy only)
# --------------------------------------------------------------------------- #
def _as_positions(arr: Any) -> np.ndarray:
    if arr is None:
        return np.zeros((0, 3), np.float32)
    a = np.asarray(arr, np.float32)
    if a.size == 0:
        return np.zeros((0, 3), np.float32)
    return a.reshape(-1, 3)


def _accumulate_by_index(n: int, sel: np.ndarray, values: np.ndarray) -> np.ndarray:
    """out[i] += sum of values[j] for sel[j] == i, via bincount (much faster than np.add.at)."""
    out = np.empty((n, values.shape[1]), np.float64)
    for k in range(values.shape[1]):
        out[:, k] = np.bincount(sel, weights=values[:, k], minlength=n)[:n]
    return out


def compute_normals(positions: np.ndarray, indices: np.ndarray) -> np.ndarray:
    n = positions.shape[0]
    if n == 0:
        return np.zeros((0, 3), np.float32)
    out = np.zeros((n, 3), np.float64)
    if indices.size >= 3:
        tri = indices.reshape(-1, 3)
        p0 = positions[tri[:, 0]].astype(np.float64)
        p1 = positions[tri[:, 1]].astype(np.float64)
        p2 = positions[tri[:, 2]].astype(np.float64)
        face = np.cross(p1 - p0, p2 - p0)
        out = _accumulate_by_index(n, tri.ravel(), np.repeat(face, 3, axis=0))
    lens = np.linalg.norm(out, axis=1)
    bad = lens < 1e-12
    out = np.where(lens[:, None] > 1e-12, out / np.maximum(lens, 1e-12)[:, None], 0.0)
    out[bad] = (0.0, 1.0, 0.0)
    return out.astype(np.float32)


def compute_tangents(positions: np.ndarray, normals: np.ndarray,
                     uvs: np.ndarray, indices: np.ndarray) -> np.ndarray:
    n = positions.shape[0]
    tan = np.zeros((n, 3), np.float64)
    bit = np.zeros((n, 3), np.float64)
    if n and indices.size >= 3:
        tri = indices.reshape(-1, 3)
        p0, p1, p2 = (positions[tri[:, i]].astype(np.float64) for i in range(3))
        uv0, uv1, uv2 = (uvs[tri[:, i]].astype(np.float64) for i in range(3))
        e1, e2 = p1 - p0, p2 - p0
        d1, d2 = uv1 - uv0, uv2 - uv0
        r = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
        r = np.where(np.abs(r) < 1e-12, 1.0, r)
        f = 1.0 / r
        t = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) * f[:, None]
        b = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) * f[:, None]
        flat = tri.ravel()
        tan = _accumulate_by_index(n, flat, np.repeat(t, 3, axis=0))
        bit = _accumulate_by_index(n, flat, np.repeat(b, 3, axis=0))
    # Gram-Schmidt against the normal; fall back to any perpendicular vector
    nd = np.einsum("ij,ij->i", tan, normals.astype(np.float64))
    tan = tan - normals.astype(np.float64) * nd[:, None]
    lens = np.linalg.norm(tan, axis=1)
    ok = lens > 1e-8
    tan[ok] /= lens[ok, None]
    if (~ok).any():
        ref = np.where(np.abs(normals[~ok, 1:2]) < 0.9, 0.0, 1.0)
        alt = np.stack([ref.ravel(), 1.0 - ref.ravel(), np.zeros_like(ref.ravel())], 1)
        fallback = np.cross(normals[~ok].astype(np.float64), alt)
        fl = np.linalg.norm(fallback, axis=1)
        fallback[fl > 1e-9] /= fl[fl > 1e-9, None]
        tan[~ok] = fallback
    sign = np.einsum("ij,ij->i", np.cross(normals.astype(np.float64), tan), bit)
    w = np.where(sign < 0.0, -1.0, 1.0)
    return np.concatenate([tan.astype(np.float32), w[:, None].astype(np.float32)], axis=1)


@dataclass
class PreparedLOD:
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    tangents: np.ndarray
    indices: np.ndarray
    interleaved: np.ndarray
    center: Tuple[float, float, float]
    radius: float
    ranges: List[Tuple[int, int, str]] = field(default_factory=list)

    @property
    def vertex_count(self) -> int:
        return int(self.positions.shape[0])

    @property
    def index_count(self) -> int:
        return int(self.indices.size)


def prepare_lod(lod: Optional[MeshLOD], uv_channel: int = 0) -> PreparedLOD:
    """Normalise a MeshLOD into tightly packed GL-ready arrays (never raises).

    ``uv_channel`` 选择顶点缓冲里的第几套 UV（0 起）。该游戏的资产普遍有 2~3 套，
    材质真正采样的一般是通道 1/2，拿错通道就是「贴图在、位置全错」。
    """
    empty = PreparedLOD(np.zeros((0, 3), np.float32), np.zeros((0, 3), np.float32),
                        np.zeros((0, 2), np.float32), np.zeros((0, 4), np.float32),
                        np.zeros((0,), np.uint32), np.zeros((0, MESH_VERTEX_LAYOUT), np.float32),
                        (0.0, 0.0, 0.0), 1.0, [])
    if lod is None:
        return empty
    pos = _as_positions(getattr(lod, "positions", None))
    n = pos.shape[0]
    if n == 0:
        return empty

    idx = getattr(lod, "indices", None)
    if idx is None:
        idx = np.arange(n, dtype=np.uint32)
    idx = np.asarray(idx).reshape(-1)
    triangles = idx[:idx.size // 3 * 3].reshape(-1, 3)
    valid = np.all(np.isfinite(triangles) & (triangles >= 0) & (triangles < n)
                   & (triangles == np.floor(triangles)), axis=1)
    kept_prefix = np.concatenate(([0], np.cumsum(valid))) * 3
    idx = triangles[valid].astype(np.uint32).reshape(-1)

    nrm = getattr(lod, "normals", None)
    if nrm is None or np.asarray(nrm).size == 0:
        nrm = compute_normals(pos, idx)
    else:
        nrm = np.asarray(nrm, np.float32).reshape(-1, 3)
        if nrm.shape[0] != n:
            nrm = compute_normals(pos, idx)
    lens = np.linalg.norm(nrm, axis=1)
    nrm = np.where(lens[:, None] > 1e-8, nrm / np.maximum(lens, 1e-8)[:, None], 0.0)
    bad = np.linalg.norm(nrm, axis=1) < 0.5
    if bad.any():
        nrm = nrm.copy()
        nrm[bad] = compute_normals(pos, idx)[bad]
    nrm = nrm.astype(np.float32)

    uv = None
    pick = getattr(lod, "uv", None)
    if callable(pick):
        try:
            uv = pick(int(uv_channel))
        except Exception:                                      # noqa: BLE001
            uv = None
    if uv is None:
        uv = getattr(lod, "uvs", None)
    if uv is None or np.asarray(uv).size == 0:
        uv = np.zeros((n, 2), np.float32)
    else:
        uv = np.asarray(uv, np.float32)
        uv = uv.reshape(n, -1)[:, :2]
        if uv.shape[1] < 2:
            uv = np.zeros((n, 2), np.float32)
    # UE 的 UV 原点在左上、V 向下；我们的贴图解码出来是自上而下存的行，
    # 采样时 v=0 取到的是图像顶部 —— 两边约定相反，所以这里统一把 V 翻过来
    # （导出器写出去的是原始 V，只有渲染需要翻；见 exporters/obj.py 的 flip_uv）。
    #
    # 注意：必须**复制**再翻。lod.uv_sets 的切片是原数组的视图，原地翻会把
    # 源数据改掉；而 prepare_lod 会被 mesh_bounds()/取景、以及每一帧的
    # _sync_mesh 反复调用 —— 原地翻就等于「每调一次翻一次」，贴图会时不时
    # 上下颠倒，看起来就是「贴图错位」。
    uv = np.array(uv, dtype=np.float32, copy=True)
    import os as _os
    if _os.environ.get("VERTEXVIEWER_UFLIP") == "1":
        uv[:, 0] = 1.0 - uv[:, 0]
    if _os.environ.get("VERTEXVIEWER_NO_VFLIP") != "1":
        uv[:, 1] = 1.0 - uv[:, 1]

    tan = getattr(lod, "tangents", None)
    if tan is None or np.asarray(tan).size == 0:
        tan = compute_tangents(pos, nrm, uv, idx)
    else:
        tan = np.asarray(tan, np.float32)
        if tan.ndim == 1:
            tan = tan.reshape(n, -1)
        if tan.shape[0] != n or tan.shape[1] < 3:
            tan = compute_tangents(pos, nrm, uv, idx)
        else:
            t = tan[:, :3].copy()
            w = tan[:, 3] if tan.shape[1] > 3 else np.ones(n, np.float32)
            lens = np.linalg.norm(t, axis=1)
            t = np.where(lens[:, None] > 1e-8, t / np.maximum(lens, 1e-8)[:, None], 0.0)
            bad = np.linalg.norm(t, axis=1) < 0.5
            if bad.any():
                t[bad] = compute_tangents(pos, nrm, uv, idx)[bad, :3]
            tan = np.concatenate([t, w[:, None].astype(np.float32)], axis=1)

    inter = np.empty((n, MESH_VERTEX_LAYOUT), np.float32)
    inter[:, 0:3] = pos
    inter[:, 3:6] = nrm
    inter[:, 6:8] = uv
    inter[:, 8:12] = tan

    lo = pos.min(axis=0)
    hi = pos.max(axis=0)
    center = ((lo + hi) * 0.5).astype(np.float32)
    radius = float(np.linalg.norm(hi - lo) * 0.5) or 1.0

    ranges: List[Tuple[int, int, str]] = []
    sections = getattr(lod, "sections", None) or []
    for sec in sections:
        first = max(0, int(getattr(sec, "first_index", 0) or 0))
        tris = int(getattr(sec, "num_triangles", 0) or 0)
        count = tris * 3
        if count <= 0 or first >= triangles.size:
            continue
        start = min(len(triangles), first // 3)
        end = min(len(triangles), (first + count) // 3)
        first = int(kept_prefix[start])
        count = int(kept_prefix[end] - kept_prefix[start])
        if count >= 3:
            ranges.append((first, count, str(getattr(sec, "material_path", "") or "")))
    if not ranges and idx.size >= 3:
        ranges = [(0, int(idx.size), "")]

    return PreparedLOD(pos, nrm, uv, tan, idx, inter,
                       (float(center[0]), float(center[1]), float(center[2])),
                       radius, ranges)


def mesh_bounds(mesh: Optional[Mesh], lod_index: int = 0) -> Tuple[Tuple[float, float, float], float]:
    """Bounding sphere of a LOD without touching OpenGL (for camera framing)."""
    if mesh is None or not getattr(mesh, "lods", None):
        return (0.0, 0.0, 0.0), 1.0
    lod = mesh.lods[lod_index] if 0 <= lod_index < len(mesh.lods) else mesh.lods[0]
    prepared = prepare_lod(lod)
    return prepared.center, prepared.radius


# --------------------------------------------------------------------------- #
# camera
# --------------------------------------------------------------------------- #
@dataclass
class Camera:
    yaw: float = 35.0        # degrees around +Y
    pitch: float = 18.0      # degrees above the horizon
    distance: float = 3.4
    target: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    fov: float = 42.0
    min_distance: float = 1e-3
    max_distance: float = 1e5
    first_person_pose: object = None
    horizontal_fov: float = 90.0

    def set_first_person(self, pose):
        self.first_person_pose=pose

    def projection_fov(self, aspect):
        if self.first_person_pose is None:return self.fov
        return math.degrees(2*math.atan(math.tan(math.radians(self.horizontal_fov)*.5)/max(aspect,.01)))

    def eye(self) -> np.ndarray:
        if self.first_person_pose is not None:return np.asarray(self.first_person_pose[0],np.float64)
        cy = math.cos(math.radians(max(-89.5, min(89.5, self.pitch))))
        p = math.radians(self.pitch)
        y = math.radians(self.yaw)
        d = max(self.distance, 1e-5)
        return np.asarray(self.target, np.float64) + d * np.array(
            [cy * math.sin(y), math.sin(p), cy * math.cos(y)])

    def view_matrix(self) -> np.ndarray:
        if self.first_person_pose is not None:
            eye,forward,up=self.first_person_pose
            return L.look_at(eye,np.asarray(eye)+forward,up)
        return L.look_at(self.eye(), np.asarray(self.target, np.float64))

    def basis(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        eye = self.eye()
        target = np.asarray(self.target, np.float64)
        fwd = L.normalize(target - eye)
        right = L.normalize(np.cross(fwd, np.array([0.0, 1.0, 0.0])))
        up = np.cross(right, fwd)
        return right, up, fwd

    def orbit(self, dx: float, dy: float) -> None:
        if self.first_person_pose is not None:return
        self.yaw -= dx * 0.35
        self.pitch = max(-89.0, min(89.0, self.pitch + dy * 0.35))

    def zoom(self, steps: float) -> None:
        if self.first_person_pose is not None:
            self.horizontal_fov=float(np.clip(self.horizontal_fov-steps*3,55,110))
            return
        self.distance = max(self.min_distance,
                            min(self.max_distance, self.distance * (0.9 ** steps)))

    def pan(self, dx: float, dy: float, viewport_height: float) -> None:
        if self.first_person_pose is not None:return
        if viewport_height <= 0:
            return
        right, up, _ = self.basis()
        scale = 2.0 * self.distance * math.tan(math.radians(self.fov) * 0.5) / viewport_height
        t = np.asarray(self.target, np.float64) - right * dx * scale + up * dy * scale
        self.target = (float(t[0]), float(t[1]), float(t[2]))

    def frame(self, center: Sequence[float], radius: float,
              aspect: float = 1.0) -> None:
        self.first_person_pose=None
        r = max(float(radius), 1e-4)
        self.target = (float(center[0]), float(center[1]), float(center[2]))
        # 竖着的视口（左边树 + 右边检查器时很常见）水平视角更窄，
        # 只按垂直 FOV 算距离会把模型左右切掉，所以取两个方向里更小的那个。
        tan_v = math.tan(math.radians(self.fov) * 0.5)
        tan_eff = min(tan_v, tan_v * max(float(aspect or 1.0), 1e-3))
        self.distance = max(self.min_distance,
                            min(self.max_distance, r / tan_eff * 1.16))

    def reset(self) -> None:
        self.first_person_pose=None
        self.yaw, self.pitch = 35.0, 18.0
        self.distance = 3.4
        self.target = (0.0, 0.0, 0.0)


# --------------------------------------------------------------------------- #
# scene state
# --------------------------------------------------------------------------- #
@dataclass
class SceneState:
    mesh: Optional[Mesh] = None
    materials: List[Material] = field(default_factory=list)
    textures: List[Texture] = field(default_factory=list)
    lod_index: int = 0
    metallic_override: Optional[float] = None
    roughness_override: Optional[float] = None
    texture_override: Dict[str, Any] = field(default_factory=dict)
    lighting: L.LightingState = field(default_factory=L.LightingState)
    style: str = "game"
    exposure_ev: float = 0.25
    background: str = DEFAULT_BACKGROUND
    wireframe: bool = False
    uv_channel: int = 0
    # 默认隐藏「一张贴图都没有的 Masked/Translucent 面」（手机屏、序列帧面），
    # 它们在游戏里是贴屏 UI，画出来就是纯白一大片盖住模型。
    show_untextured: bool = False
    camera: Camera = field(default_factory=Camera)
    time: float = 0.0
    mesh_version: int = 0
    geometry_version: int = 0
    texture_version: int = 0

    def active_lod(self) -> Optional[MeshLOD]:
        if self.mesh is None or not getattr(self.mesh, "lods", None):
            return None
        i = max(0, min(int(self.lod_index), len(self.mesh.lods) - 1))
        return self.mesh.lods[i]

    def uv_channel_count(self) -> int:
        lod = self.active_lod()
        if lod is None:
            return 0
        count = getattr(lod, "uv_channel_count", None)
        if callable(count):
            try:
                return int(count())
            except Exception:                                  # noqa: BLE001
                return 1
        return 1

    def __post_init__(self) -> None:
        # 命令行/Tools 脚本想固定通道时用这个环境变量（UI 里另有下拉框）
        import os as _os
        raw = _os.environ.get("VERTEXVIEWER_UVI")
        if raw:
            try:
                self.uv_channel = max(0, int(raw))
            except ValueError:
                pass


# --------------------------------------------------------------------------- #
# GL renderer
# --------------------------------------------------------------------------- #
@dataclass
class _Draw:
    first: int
    count: int
    material: Optional[Material]
    textures: List[Optional[Texture]]


class SceneRenderer:
    """All GPU state for one GL context.  Rebuild it if the context changes."""

    def __init__(self, state: Optional[SceneState] = None):
        _require_gl()
        self.state = state
        self.shader_log: List[Dict[str, Any]] = []
        self.programs: Dict[str, int] = {}
        self._loc: Dict[int, Dict[str, int]] = {}
        self._size = (0, 0)
        self._gpu_mesh: Optional[Dict[str, Any]] = None
        self._draws: List[_Draw] = []
        self._mesh_key: Optional[Tuple[Any, ...]] = None
        self._texture_cache: Dict[Tuple[Any, ...], int] = {}
        self._texture_cache_key: Optional[Tuple[Any, ...]] = None
        self._tex_assign_key: Optional[Tuple[Any, ...]] = None
        self._tex_version = -1
        self._anisotropy = 1.0
        extensions = {GL.glGetStringi(GL.GL_EXTENSIONS, i)
                      for i in range(int(GL.glGetIntegerv(GL.GL_NUM_EXTENSIONS)))}
        if b"GL_EXT_texture_filter_anisotropic" in extensions or b"GL_ARB_texture_filter_anisotropic" in extensions:
            self._anisotropy = min(16.0, float(GL.glGetFloatv(0x84FF)))
        self._compile_programs()
        self._create_static()
        self.resize(DEFAULT_CAPTURE_SIZE[0], DEFAULT_CAPTURE_SIZE[1])

    # ---- context info ------------------------------------------------------
    def gl_info(self) -> Dict[str, Any]:
        def s(name: int) -> str:
            try:
                v = GL.glGetString(name)
                return v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)
            except Exception:
                return "?"
        return {
            "version": s(GL.GL_VERSION),
            "renderer": s(GL.GL_RENDERER),
            "vendor": s(GL.GL_VENDOR),
            "glsl": s(GL.GL_SHADING_LANGUAGE_VERSION),
            "shaders": list(self.shader_log),
        }

    # ---- shader plumbing ---------------------------------------------------
    def _compile_programs(self) -> None:
        specs = [("scene", "scene.vert", "scene.frag"),
                 ("outline", "scene.vert", "outline.frag"),
                 ("shadow", "shadow.vert", "shadow.frag"),
                 ("bg", "post.vert", "bg.frag"),
                 ("post", "post.vert", "post.frag")]
        for name, vs, fs in specs:
            self.programs[name] = self._build_program(name, vs, fs)
            self._loc[self.programs[name]] = {}

    def _build_program(self, name: str, vs_name: str, fs_name: str) -> int:
        vs_src = _shader_source(vs_name)
        fs_src = _shader_source(fs_name)
        shaders = []
        try:
            for kind, src, label in ((GL.GL_VERTEX_SHADER, vs_src, vs_name),
                                     (GL.GL_FRAGMENT_SHADER, fs_src, fs_name)):
                sh = GL.glCreateShader(kind)
                GL.glShaderSource(sh, src)
                GL.glCompileShader(sh)
                if not GL.glGetShaderiv(sh, GL.GL_COMPILE_STATUS):
                    log = (GL.glGetShaderInfoLog(sh) or b"").decode("utf-8", "replace")
                    raise RuntimeError(f"[{name}] {label} failed to compile:\n{log}")
                shaders.append(sh)
            prog = GL.glCreateProgram()
            for sh in shaders:
                GL.glAttachShader(prog, sh)
            GL.glLinkProgram(prog)
            if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
                log = (GL.glGetProgramInfoLog(prog) or b"").decode("utf-8", "replace")
                raise RuntimeError(f"[{name}] link failed:\n{log}")
        except Exception as exc:
            self.shader_log.append({"program": name, "vertex": vs_name,
                                    "fragment": fs_name, "ok": False,
                                    "error": str(exc)})
            raise
        finally:
            for sh in shaders:
                try:
                    GL.glDeleteShader(sh)
                except Exception:
                    pass
        self.shader_log.append({"program": name, "vertex": vs_name,
                                "fragment": fs_name, "ok": True, "error": ""})
        return prog

    def _u(self, program: int, name: str) -> int:
        cache = self._loc.setdefault(program, {})
        if name not in cache:
            cache[name] = GL.glGetUniformLocation(program, name)
        return cache[name]

    def _mat4(self, program: int, name: str, mat: np.ndarray) -> None:
        GL.glUniformMatrix4fv(self._u(program, name), 1, GL.GL_FALSE, L.gl_matrix(mat))

    def _mat3(self, program: int, name: str, mat: np.ndarray) -> None:
        m = np.ascontiguousarray(np.asarray(mat, np.float32)[:3, :3].T)
        GL.glUniformMatrix3fv(self._u(program, name), 1, GL.GL_FALSE, m)

    # ---- static GL objects -------------------------------------------------
    def _create_static(self) -> None:
        self._vao_empty = GL.glGenVertexArrays(1)
        self._fallback_tex = self._new_texture_2d(
            np.full((1, 1, 4), 255, np.uint8), srgb=False, mipmap=False)

        # shadow target ------------------------------------------------------
        self._shadow_fbo = GL.glGenFramebuffers(1)
        self._shadow_tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._shadow_tex)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_DEPTH_COMPONENT24, SHADOW_SIZE,
                        SHADOW_SIZE, 0, GL.GL_DEPTH_COMPONENT, GL.GL_UNSIGNED_INT, None)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_COMPARE_MODE, GL.GL_NONE)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._shadow_fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_DEPTH_ATTACHMENT,
                                  GL.GL_TEXTURE_2D, self._shadow_tex, 0)
        GL.glDrawBuffer(GL.GL_NONE)
        GL.glReadBuffer(GL.GL_NONE)
        self._check_fbo("shadow")
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)

        self._max_samples = int(GL.glGetIntegerv(GL.GL_MAX_SAMPLES) or 1)

    def _check_fbo(self, label: str) -> None:
        status = GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER)
        if status != GL.GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError(f"FBO {label} incomplete: 0x{status:04x}")

    def _new_texture_2d(self, rgba: np.ndarray, srgb: bool, mipmap: bool = True) -> int:
        arr = _as_texture_array(rgba)
        if arr is None:
            arr = np.full((1, 1, 4), 255, np.uint8)
        h, w = arr.shape[:2]
        data = np.ascontiguousarray(arr[::-1]).tobytes()   # UE V axis is top-down
        tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        internal = GL.GL_SRGB8_ALPHA8 if srgb else GL.GL_RGBA8
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, internal, w, h, 0,
                        GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, data)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_REPEAT)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_REPEAT)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        if mipmap:
            GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER,
                               GL.GL_LINEAR_MIPMAP_LINEAR)
            if self._anisotropy > 1.0:
                GL.glTexParameterf(GL.GL_TEXTURE_2D, 0x84FE, self._anisotropy)
        else:
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        return tex

    # ---- offscreen targets -------------------------------------------------
    def resize(self, width: int, height: int) -> None:
        width = max(1, int(width))
        height = max(1, int(height))
        if (width, height) == self._size and getattr(self, "_msaa_fbo", None):
            return
        self._release_targets()
        samples = min(4, max(0, self._max_samples))

        self._msaa_fbo = GL.glGenFramebuffers(1)
        self._msaa_color = GL.glGenRenderbuffers(1)
        self._msaa_depth = GL.glGenRenderbuffers(1)
        GL.glBindRenderbuffer(GL.GL_RENDERBUFFER, self._msaa_color)
        GL.glRenderbufferStorageMultisample(GL.GL_RENDERBUFFER, samples,
                                            GL.GL_RGBA16F, width, height)
        GL.glBindRenderbuffer(GL.GL_RENDERBUFFER, self._msaa_depth)
        GL.glRenderbufferStorageMultisample(GL.GL_RENDERBUFFER, samples,
                                            GL.GL_DEPTH_COMPONENT24, width, height)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._msaa_fbo)
        GL.glFramebufferRenderbuffer(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                                     GL.GL_RENDERBUFFER, self._msaa_color)
        GL.glFramebufferRenderbuffer(GL.GL_FRAMEBUFFER, GL.GL_DEPTH_ATTACHMENT,
                                     GL.GL_RENDERBUFFER, self._msaa_depth)
        self._check_fbo("msaa")

        self._resolve_fbo = GL.glGenFramebuffers(1)
        self._resolve_tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._resolve_tex)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA16F, width, height, 0,
                        GL.GL_RGBA, GL.GL_FLOAT, None)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._resolve_fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                                  GL.GL_TEXTURE_2D, self._resolve_tex, 0)
        self._check_fbo("resolve")

        # 8-bit target used for capture/readback
        self._capture_fbo = GL.glGenFramebuffers(1)
        self._capture_tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._capture_tex)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, width, height, 0,
                        GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, None)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._capture_fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                                  GL.GL_TEXTURE_2D, self._capture_tex, 0)
        self._check_fbo("capture")

        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
        self._size = (width, height)
        self._samples = samples

    def _release_targets(self) -> None:
        for attr in ("_msaa_fbo", "_resolve_fbo", "_capture_fbo"):
            v = getattr(self, attr, None)
            if v:
                GL.glDeleteFramebuffers(1, [v])
                setattr(self, attr, None)
        for attr in ("_msaa_color", "_msaa_depth"):
            v = getattr(self, attr, None)
            if v:
                GL.glDeleteRenderbuffers(1, [v])
                setattr(self, attr, None)
        for attr in ("_resolve_tex", "_capture_tex"):
            v = getattr(self, attr, None)
            if v:
                GL.glDeleteTextures([v])
                setattr(self, attr, None)

    # ---- mesh + material upload -------------------------------------------
    def _release_mesh(self) -> None:
        mesh = self._gpu_mesh or {}
        if mesh.get("vao"):
            GL.glDeleteVertexArrays(1, [mesh["vao"]])
        buffers = [mesh[k] for k in ("vbo", "ebo") if mesh.get(k)]
        if buffers:
            GL.glDeleteBuffers(len(buffers), buffers)
        self._gpu_mesh = None

    def _sync_mesh(self, state: SceneState) -> None:
        # 用对象身份而不是 id()：CPython 会把刚释放的地址复用给新对象，
        # 只比 id 会让「换模型后仍显示上一个模型」这种事偶发出现。
        key = (state.lod_index, state.mesh_version,
               int(getattr(state, "uv_channel", 0) or 0),
               bool(getattr(state, "show_untextured", False)))
        if (key == self._mesh_key
                and state.mesh is getattr(self, "_mesh_ref", None)
                and state.materials is getattr(self, "_mat_ref", None)):
            if getattr(self, '_geometry_version', -1) != state.geometry_version and self._gpu_mesh and self._gpu_mesh.get('vbo'):
                prepared = prepare_lod(state.active_lod(), int(getattr(state, 'uv_channel', 0) or 0))
                if prepared.vertex_count != self._gpu_mesh['vertex_count']:
                    raise ValueError('animation changed the vertex count')
                GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._gpu_mesh['vbo'])
                data = prepared.interleaved.tobytes()
                GL.glBufferSubData(GL.GL_ARRAY_BUFFER, 0, len(data), data)
                self._geometry_version = state.geometry_version
            return
        self._geometry_version = state.geometry_version
        self._mesh_key = key
        self._mesh_ref = state.mesh
        self._mat_ref = state.materials
        self._draws = []
        self._release_mesh()
        self._tex_assign_key = None
        if state.mesh is None or not getattr(state.mesh, "lods", None):
            return

        prepared = prepare_lod(state.active_lod(), int(getattr(state, "uv_channel", 0) or 0))
        if prepared.vertex_count == 0 or prepared.index_count < 3:
            self._draws = []
            self._gpu_mesh = {"vertex_count": prepared.vertex_count,
                              "index_count": prepared.index_count,
                              "center": prepared.center, "radius": prepared.radius}
            return

        vao = GL.glGenVertexArrays(1)
        vbo = GL.glGenBuffers(1)
        ebo = GL.glGenBuffers(1)
        GL.glBindVertexArray(vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
        data = prepared.interleaved.tobytes()
        GL.glBufferData(GL.GL_ARRAY_BUFFER, len(data), data, GL.GL_STATIC_DRAW)
        stride = MESH_VERTEX_LAYOUT * 4
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(0))
        GL.glEnableVertexAttribArray(1)
        GL.glVertexAttribPointer(1, 3, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(12))
        GL.glEnableVertexAttribArray(2)
        GL.glVertexAttribPointer(2, 2, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(24))
        GL.glEnableVertexAttribArray(3)
        GL.glVertexAttribPointer(3, 4, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(32))

        GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, ebo)
        idata = prepared.indices.tobytes()
        GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER, len(idata), idata, GL.GL_STATIC_DRAW)
        GL.glBindVertexArray(0)

        self._gpu_mesh = {
            "vao": vao, "vbo": vbo, "ebo": ebo,
            "vertex_count": prepared.vertex_count,
            "index_count": prepared.index_count,
            "center": prepared.center, "radius": prepared.radius,
        }
        self._build_draws(state, prepared)

    def _build_draws(self, state: SceneState, prepared: PreparedLOD) -> None:
        mats_by_path: Dict[str, Material] = {}
        mats_by_name: Dict[str, Material] = {}
        for m in state.materials or []:
            if not isinstance(m, Material):
                continue
            if m.pak_path:
                mats_by_path[str(m.pak_path)] = m
            key = _basename_key(m.pak_path or m.name)
            if key:
                mats_by_name.setdefault(key, m)

        draws: List[_Draw] = []
        for i, (first, count, mat_path) in enumerate(prepared.ranges):
            mat = mats_by_path.get(mat_path) if mat_path else None
            if mat is None and mat_path:
                mat = mats_by_name.get(_basename_key(mat_path))
            if mat is None:
                mat = (state.materials[i] if i < len(state.materials)
                       and isinstance(state.materials[i], Material) else None)
            if (mat is not None and not getattr(state, "show_untextured", False)
                    and mat.is_untextured_overlay):
                # 一块没有贴图的 Masked/Translucent 面（手机屏/序列帧/UI 卡片）：
                # 画出来就是一整片白，把模型本体盖住了，默认不画。
                continue
            draws.append(_Draw(first, count, mat, [None, None, None, None]))
        self._draws = draws

    def _sync_textures(self, state: SceneState) -> None:
        key = (id(self._draws), state.texture_version, id(state.textures))
        if key == self._tex_assign_key:
            return
        self._tex_assign_key = key

        if state.texture_version != self._tex_version:
            self._tex_version = state.texture_version
            for tex in self._texture_cache.values():
                GL.glDeleteTextures([tex])
            self._texture_cache.clear()
            getattr(self, "_tex_keep", {}).clear()

        by_path: Dict[str, Texture] = {}
        by_name: Dict[str, Texture] = {}
        for t in state.textures or []:
            if not isinstance(t, Texture):
                continue
            if t.pak_path:
                by_path[str(t.pak_path)] = t
            key = _basename_key(t.pak_path or t.name)
            if key:
                by_name.setdefault(key, t)

        slots = ("base", "normal", "orm", "emissive")
        for draw in self._draws:
            for si, slot in enumerate(slots):
                obj = state.texture_override.get(slot)
                if obj is not None:
                    draw.textures[si] = obj if isinstance(obj, Texture) else _OverrideTexture(obj)
                    continue
                mat = draw.material
                path = ""
                if mat is not None:
                    path = {"base": mat.base_color_texture,
                            "normal": mat.normal_texture,
                            "orm": mat.orm_texture,
                            "emissive": mat.emissive_texture}[slot]
                if path:
                    tex = by_path.get(str(path)) or by_name.get(_basename_key(path))
                    draw.textures[si] = tex

        if os.environ.get("VERTEXVIEWER_DBG_TEX"):
            for d in self._draws:
                m = d.material
                print("[tex]", getattr(m, "name", None),
                      "base=", (d.textures[0].pak_path.split('/')[-1] if d.textures[0] is not None else None),
                      "nrm=", d.textures[1] is not None, "orm=", d.textures[2] is not None,
                      "emis=", d.textures[3] is not None, flush=True)

        # 只保留还在 _texture_cache 里的那些 Texture 的强引用，避免无界增长
        live = {k[0] for k in self._texture_cache}
        self._tex_keep = {k: v for k, v in getattr(self, "_tex_keep", {}).items() if k in live}
        self._gl_textures: Dict[int, int] = {}
        for draw in self._draws:
            draw_gl = []
            for si, slot in enumerate(slots):
                tex = draw.textures[si]
                if tex is not None and not isinstance(tex, _OverrideTexture):
                    # 留个强引用：Texture 被 GC 之后 id 会被新对象复用，
                    # 只按 id 存 GL 贴图会让新模型套上旧模型的贴图。
                    self._tex_keep[id(tex)] = tex
                arr = _as_texture_array(tex)
                if arr is None:
                    draw_gl.append(0)
                    continue
                key = (id(tex), arr.shape[0], arr.shape[1], slot in ("base",))
                gl_tex = self._texture_cache.get(key)
                if gl_tex is None:
                    gl_tex = self._new_texture_2d(arr, srgb=(slot == "base"))
                    self._texture_cache[key] = gl_tex
                draw_gl.append(gl_tex)
            self._gl_textures[id(draw)] = draw_gl

    # ---- render ------------------------------------------------------------
    def render(self, state: SceneState, width: int, height: int,
               target_fbo: int = 0, readback: bool = False) -> Optional[np.ndarray]:
        _require_gl()
        self.state = state
        width = max(1, int(width))
        height = max(1, int(height))
        self.resize(width, height)
        self._sync_mesh(state)
        if self._draws:
            self._sync_textures(state)

        GL.glDisable(GL.GL_SCISSOR_TEST)
        GL.glDisable(GL.GL_BLEND)
        GL.glDisable(GL.GL_FRAMEBUFFER_SRGB)

        center, radius = (0.0, 0.0, 0.0), 1.0
        if self._gpu_mesh:
            center = self._gpu_mesh["center"]
            radius = self._gpu_mesh["radius"]

        lighting = state.lighting
        view = state.camera.view_matrix()
        aspect = width / float(height)
        near = max(1e-4, min(radius * 0.01, state.camera.distance * 0.01))
        far = max(near + 0.1, state.camera.distance + radius * 8.0 + 10.0)
        proj = L.perspective(state.camera.projection_fov(aspect), aspect, near, far)
        eye = state.camera.eye()

        if lighting.shadow and self._gpu_mesh and self._gpu_mesh.get("vao"):
            self._render_shadow(state, center, radius)

        # ---- scene pass
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._msaa_fbo)
        GL.glViewport(0, 0, width, height)
        GL.glDepthMask(GL.GL_TRUE)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        GL.glDepthMask(GL.GL_FALSE)
        self._render_background(state, aspect)

        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDepthFunc(GL.GL_LEQUAL)
        GL.glDepthMask(GL.GL_TRUE)
        GL.glEnable(GL.GL_CULL_FACE)
        GL.glCullFace(GL.GL_BACK)

        params = style_params(state.style)
        if self._gpu_mesh and self._draws:
            self._set_scene_uniforms(state, view, proj, eye, aspect)
            self._draw_sections(state, params, outline=False, view=view, proj=proj)
            if params.get("outline", 0.0) > 0.0 and not state.wireframe:
                self._draw_sections(state, params, outline=True, view=view, proj=proj)

        # ---- resolve MSAA
        GL.glBindFramebuffer(GL.GL_READ_FRAMEBUFFER, self._msaa_fbo)
        GL.glBindFramebuffer(GL.GL_DRAW_FRAMEBUFFER, self._resolve_fbo)
        GL.glBlitFramebuffer(0, 0, width, height, 0, 0, width, height,
                             GL.GL_COLOR_BUFFER_BIT, GL.GL_NEAREST)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)

        # ---- post pass
        final_fbo = self._capture_fbo if readback else int(target_fbo)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, final_fbo)
        GL.glViewport(0, 0, width, height)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_CULL_FACE)
        GL.glDisable(GL.GL_BLEND)
        self._draw_post(state, params, width, height)

        if readback:
            return self._read_pixels(self._capture_fbo, width, height)
        return None

    def _render_background(self, state: SceneState, aspect: float) -> None:
        prog = self.programs["bg"]
        GL.glUseProgram(prog)
        GL.glBindVertexArray(self._vao_empty)
        GL.glUniform1i(self._u(prog, "u_kind"), BACKGROUND_IDS.get(state.background, 0))
        GL.glUniform1f(self._u(prog, "u_aspect"), aspect)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
        GL.glBindVertexArray(0)

    def _render_shadow(self, state: SceneState, center: Sequence[float], radius: float) -> None:
        key = state.lighting.key
        light_vp = L.shadow_matrix(center, radius, key.direction())
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._shadow_fbo)
        GL.glViewport(0, 0, SHADOW_SIZE, SHADOW_SIZE)
        GL.glClear(GL.GL_DEPTH_BUFFER_BIT)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDepthMask(GL.GL_TRUE)
        GL.glDepthFunc(GL.GL_LEQUAL)
        GL.glDisable(GL.GL_CULL_FACE)
        prog = self.programs["shadow"]
        GL.glUseProgram(prog)
        self._mat4(prog, "u_model", np.eye(4))
        self._mat4(prog, "u_light_vp", light_vp)
        GL.glBindVertexArray(self._gpu_mesh["vao"])
        for draw in self._draws:
            GL.glDrawElements(GL.GL_TRIANGLES, draw.count, GL.GL_UNSIGNED_INT,
                              ctypes.c_void_p(draw.first * 4))
        GL.glBindVertexArray(0)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)

    def _set_scene_uniforms(self, state: SceneState, view: np.ndarray,
                            proj: np.ndarray, eye: np.ndarray, aspect: float) -> None:
        prog = self.programs["scene"]
        GL.glUseProgram(prog)
        GL.glUniform1i(self._u(prog, "u_style"), style_id(state.style))
        self._mat4(prog, "u_model", np.eye(4))
        self._mat4(prog, "u_view", view)
        self._mat4(prog, "u_proj", proj)
        self._mat3(prog, "u_normal_mat", np.eye(3))
        GL.glUniform1f(self._u(prog, "u_outline"), 0.0)
        GL.glUniform3f(self._u(prog, "u_cam_pos"), float(eye[0]), float(eye[1]), float(eye[2]))

        dirs, cols, angs = state.lighting.uniform_arrays()
        for i in range(3):
            GL.glUniform3f(self._u(prog, f"u_light_dir[{i}]"),
                           float(dirs[i, 0]), float(dirs[i, 1]), float(dirs[i, 2]))
            GL.glUniform3f(self._u(prog, f"u_light_color[{i}]"),
                           float(cols[i, 0]), float(cols[i, 1]), float(cols[i, 2]))
            GL.glUniform1f(self._u(prog, f"u_light_angle[{i}]"), float(angs[i]))
        lt = state.lighting
        GL.glUniform3f(self._u(prog, "u_amb_top"), *[float(x) for x in lt.ambient_top])
        GL.glUniform3f(self._u(prog, "u_amb_bottom"), *[float(x) for x in lt.ambient_bottom])
        GL.glUniform1f(self._u(prog, "u_env_intensity"), float(lt.env_intensity))

        # shadow
        use_shadow = bool(lt.shadow and self._gpu_mesh)
        GL.glUniform1i(self._u(prog, "u_shadow_enabled"), 1 if use_shadow else 0)
        if use_shadow:
            light_vp = L.shadow_matrix(self._gpu_mesh["center"], self._gpu_mesh["radius"],
                                       lt.key.direction())
            self._mat4(prog, "u_light_vp", light_vp)
            GL.glUniform1f(self._u(prog, "u_shadow_texel"), 1.0 / SHADOW_SIZE)
            GL.glUniform1f(self._u(prog, "u_shadow_radius"), float((self._gpu_mesh or {}).get("radius", 1.0)))
            GL.glActiveTexture(GL.GL_TEXTURE4)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._shadow_tex)
            GL.glUniform1i(self._u(prog, "u_shadow_map"), 4)
        else:
            self._mat4(prog, "u_light_vp", np.eye(4))
            GL.glUniform1f(self._u(prog, "u_shadow_texel"), 1.0 / SHADOW_SIZE)
            GL.glUniform1f(self._u(prog, "u_shadow_radius"), float((self._gpu_mesh or {}).get("radius", 1.0)))

        params = style_params(state.style)
        GL.glUniform1f(self._u(prog, "u_rim_strength"), float(params["rim_strength"]))
        GL.glUniform3f(self._u(prog, "u_rim_color"), *[float(x) for x in params["rim_color"]])
        GL.glUniform1f(self._u(prog, "u_posterize_levels"), float(params["posterize_levels"]))
        GL.glUniform1f(self._u(prog, "u_hue_shift"), float(params["hue_shift"]))
        GL.glUniform3f(self._u(prog, "u_style_color"), *[float(x) for x in params["style_color"]])
        GL.glUniform1f(self._u(prog, "u_grid_scale"), float(params["grid_scale"]))
        GL.glUniform1f(self._u(prog, "u_saturation"), float(params["saturation"]))
        GL.glUniform1f(self._u(prog, "u_time"), float(state.time))

        # fallback texture on every unit so samplers are always valid
        for unit in range(4):
            GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._fallback_tex)
        GL.glUniform1i(self._u(prog, "u_tex_base"), 0)
        GL.glUniform1i(self._u(prog, "u_tex_normal"), 1)
        GL.glUniform1i(self._u(prog, "u_tex_orm"), 2)
        GL.glUniform1i(self._u(prog, "u_tex_emissive"), 3)

    def _apply_material(self, draw: _Draw, state: SceneState) -> None:
        prog = self.programs["scene"]
        mat = draw.material
        base = (0.72, 0.72, 0.72, 1.0)
        metallic, roughness, emissive, two_sided = 0.0, 0.5, (0.0, 0.0, 0.0), False
        if mat is not None:
            bc = tuple(float(x) for x in (mat.base_color or (1, 1, 1, 1)))
            base = bc[:4] if len(bc) == 4 else (bc[0], bc[1], bc[2], 1.0)
            metallic = float(mat.metallic)
            roughness = float(mat.roughness)
            emissive = tuple(float(x) for x in (mat.emissive or (0, 0, 0)))[:3]
            two_sided = bool(getattr(mat, "two_sided", False))
        if state.metallic_override is not None:
            metallic = float(state.metallic_override)
        if state.roughness_override is not None:
            roughness = float(state.roughness_override)
        metallic = max(0.0, min(1.0, metallic))
        roughness = max(0.02, min(1.0, roughness))

        GL.glUniform4f(self._u(prog, "u_base_color"), base[0], base[1], base[2], base[3])
        GL.glUniform3f(self._u(prog, "u_emissive"),
                       float(emissive[0]) if emissive else 0.0,
                       float(emissive[1]) if emissive else 0.0,
                       float(emissive[2]) if emissive else 0.0)
        GL.glUniform1f(self._u(prog, "u_metallic"), metallic)
        GL.glUniform1f(self._u(prog, "u_roughness"), roughness)
        GL.glUniform1i(self._u(prog, "u_metal_mode"),
                       1 if state.metallic_override is not None else 0)
        GL.glUniform1i(self._u(prog, "u_rough_mode"),
                       1 if state.roughness_override is not None else 0)
        GL.glUniform1f(self._u(prog, "u_ao"), 1.0)
        normal = draw.textures[1] if len(draw.textures) > 1 else None
        normal_name = str(getattr(normal, "pak_path", "") or getattr(normal, "name", "")).lower()
        normal_format = str(getattr(normal, "source_format", "")).upper()
        GL.glUniform1i(self._u(prog, "u_normal_xy"),
                       int("ncemap" in normal_name or normal_format in ("BC5", "PF_BC5")))

        gl_tex = getattr(self, "_gl_textures", {}).get(id(draw), [0, 0, 0, 0])
        for unit, slot in enumerate(("base", "normal", "orm", "emissive")):
            has = 1 if (gl_tex[unit] if unit < len(gl_tex) else 0) else 0
            GL.glUniform1i(self._u(prog, f"u_has_{slot}"), has)
            if has:
                GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
                GL.glBindTexture(GL.GL_TEXTURE_2D, gl_tex[unit])

        # 始终双面渲染：该游戏的网格里面混着正反两种绕序（衣服内衬、玻璃、
        # 破损件），一旦按背面剔除就会出现「模型被切片、缺一半」的怪样子。
        GL.glDisable(GL.GL_CULL_FACE)

    def _draw_sections(self, state: SceneState, params: Dict[str, Any], outline: bool,
                       view: np.ndarray, proj: np.ndarray) -> None:
        prog = self.programs["outline"] if outline else self.programs["scene"]
        GL.glUseProgram(prog)
        if outline:
            radius = self._gpu_mesh["radius"] if self._gpu_mesh else 1.0
            width = max(0.0, float(params.get("outline", 0.0))) * radius
            self._mat4(prog, "u_model", np.eye(4))
            self._mat4(prog, "u_view", view)
            self._mat4(prog, "u_proj", proj)
            self._mat3(prog, "u_normal_mat", np.eye(3))
            GL.glUniform1f(self._u(prog, "u_outline"), width)
            GL.glUniform3f(self._u(prog, "u_outline_color"),
                           *[float(x) for x in params["outline_color"]])
            GL.glEnable(GL.GL_CULL_FACE)
            GL.glCullFace(GL.GL_FRONT)
            GL.glDepthFunc(GL.GL_LEQUAL)
            GL.glEnable(GL.GL_POLYGON_OFFSET_FILL)
            GL.glPolygonOffset(-1.0, -1.0)
        else:
            GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)

        GL.glBindVertexArray(self._gpu_mesh["vao"])
        if state.wireframe and not outline:
            GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_LINE)
        for draw in self._draws:
            if not outline:
                self._apply_material(draw, state)
            GL.glDrawElements(GL.GL_TRIANGLES, draw.count, GL.GL_UNSIGNED_INT,
                              ctypes.c_void_p(draw.first * 4))
        if state.wireframe and not outline:
            GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_FILL)
        GL.glBindVertexArray(0)
        if outline:
            GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)
            GL.glCullFace(GL.GL_BACK)
            GL.glDepthFunc(GL.GL_LEQUAL)

    def _draw_post(self, state: SceneState, params: Dict[str, Any],
                   width: int, height: int) -> None:
        prog = self.programs["post"]
        GL.glUseProgram(prog)
        GL.glBindVertexArray(self._vao_empty)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._resolve_tex)
        GL.glUniform1i(self._u(prog, "u_scene"), 0)
        GL.glUniform2f(self._u(prog, "u_texel"), 1.0 / width, 1.0 / height)
        GL.glUniform1f(self._u(prog, "u_exposure"), float(2.0 ** float(state.exposure_ev)))
        GL.glUniform1f(self._u(prog, "u_bloom"), float(params.get("bloom", 0.0)))
        GL.glUniform1f(self._u(prog, "u_vignette"), float(params.get("vignette", 0.3)))
        GL.glUniform1f(self._u(prog, "u_grain"), float(params.get("grain", 0.0)))
        GL.glUniform1f(self._u(prog, "u_contrast"), float(params.get("contrast", 1.0)))
        GL.glUniform1f(self._u(prog, "u_ca"), float(params.get("ca", 0.0)))
        GL.glUniform1f(self._u(prog, "u_saturation"), float(params.get("post_saturation",
                                                                       params.get("saturation", 1.0))))
        GL.glUniform1f(self._u(prog, "u_time"), float(state.time))
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
        GL.glBindVertexArray(0)

    # ---- readback ----------------------------------------------------------
    def _read_pixels(self, fbo: int, width: int, height: int) -> np.ndarray:
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
        GL.glReadBuffer(GL.GL_COLOR_ATTACHMENT0)
        GL.glPixelStorei(GL.GL_PACK_ALIGNMENT, 1)
        buf = np.empty((height, width, 4), np.uint8)
        try:
            GL.glReadPixels(0, 0, width, height, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, buf)
        except Exception:
            ptr = buf.ctypes.data_as(ctypes.POINTER(ctypes.c_ubyte))
            GL.glReadPixels(0, 0, width, height, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE,
                            ctypes.cast(ptr, ctypes.c_void_p))
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
        return np.ascontiguousarray(buf[::-1])


class _OverrideTexture:
    """Lightweight Texture stand-in for ``set_texture_override`` numpy arrays."""

    def __init__(self, rgba: Any):
        self.name = "override"
        self.pak_path = ""
        self.rgba = rgba
        arr = _as_texture_array(rgba)
        self.width = 0 if arr is None else int(arr.shape[1])
        self.height = 0 if arr is None else int(arr.shape[0])
        self.srgb = True
        self.source_format = "override"


# --------------------------------------------------------------------------- #
# offscreen viewer
# --------------------------------------------------------------------------- #
class OffscreenViewer:
    """Headless renderer on its own QOffscreenSurface + QOpenGLContext."""

    def __init__(self, state: Optional[SceneState] = None,
                 width: int = DEFAULT_CAPTURE_SIZE[0],
                 height: int = DEFAULT_CAPTURE_SIZE[1]):
        self._app = QGuiApplication.instance()
        self._owns_app = False
        if self._app is None:
            self._app = QGuiApplication([])
            self._owns_app = True
        fmt = make_surface_format(0)
        self.surface = QOffscreenSurface()
        self.surface.setFormat(fmt)
        self.surface.create()
        if not self.surface.isValid():
            raise RuntimeError("QOffscreenSurface could not be created")
        self.context = QOpenGLContext()
        self.context.setFormat(fmt)
        if not self.context.create():
            raise RuntimeError("QOpenGLContext could not be created")
        if not self.context.makeCurrent(self.surface):
            raise RuntimeError("could not make the offscreen GL context current")
        self.state = state if state is not None else SceneState()
        self.renderer = SceneRenderer(self.state)
        self.renderer.resize(width, height)
        self.gl_info = self.renderer.gl_info()
        self._last_frame_ms: List[float] = []

    def make_current(self) -> None:
        if not self.context.makeCurrent(self.surface):
            raise RuntimeError("could not make the offscreen GL context current")

    def render(self, width: int = DEFAULT_CAPTURE_SIZE[0],
               height: int = DEFAULT_CAPTURE_SIZE[1]) -> np.ndarray:
        self.make_current()
        t0 = time.perf_counter()
        GL.glFinish()
        pixels = self.renderer.render(self.state, width, height, readback=True)
        GL.glFinish()
        self._last_frame_ms.append((time.perf_counter() - t0) * 1000.0)
        return pixels if pixels is not None else np.zeros((height, width, 4), np.uint8)

    def capture(self, path: str, width: int = DEFAULT_CAPTURE_SIZE[0],
                height: int = DEFAULT_CAPTURE_SIZE[1]) -> str:
        pixels = self.render(width, height)
        save_png(path, pixels)
        return path

    def benchmark(self, frames: int = 30, width: int = DEFAULT_CAPTURE_SIZE[0],
                  height: int = DEFAULT_CAPTURE_SIZE[1]) -> Dict[str, float]:
        self.make_current()
        self.renderer.render(self.state, width, height, readback=True)
        GL.glFinish()
        times: List[float] = []
        for i in range(max(1, frames)):
            self.state.time = float(i) * 0.016
            t0 = time.perf_counter()
            self.renderer.render(self.state, width, height, readback=True)
            GL.glFinish()
            times.append((time.perf_counter() - t0) * 1000.0)
        arr = np.asarray(times, np.float64)
        return {
            "frames": int(arr.size),
            "width": width, "height": height,
            "mean_ms": float(arr.mean()),
            "p50_ms": float(np.percentile(arr, 50)),
            "p95_ms": float(np.percentile(arr, 95)),
            "min_ms": float(arr.min()),
            "max_ms": float(arr.max()),
            "fps": float(1000.0 / max(arr.mean(), 1e-6)),
        }

    def release(self) -> None:
        try:
            self.context.doneCurrent()
        except Exception:
            pass


def save_png(path: str, pixels: np.ndarray) -> str:
    """Save an (H, W, 4|3) uint8 top-down image."""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    arr = np.ascontiguousarray(pixels)
    if arr.ndim == 3 and arr.shape[2] >= 3:
        rgb = arr[..., :3]
    else:
        raise ValueError(f"unsupported pixel array {arr.shape}")
    try:
        from PIL import Image  # Pillow is in the project's dependency list
        Image.fromarray(rgb).save(path)
    except Exception:
        from PySide6.QtGui import QImage
        h, w = rgb.shape[:2]
        img = QImage(np.ascontiguousarray(rgb).data, w, h, w * 3, QImage.Format.Format_RGB888)
        if not img.save(path):
            raise RuntimeError(f"could not write {path}")
    return path


# --------------------------------------------------------------------------- #
# QOpenGLWidget
# --------------------------------------------------------------------------- #
class MeshViewer(QOpenGLWidget):
    """Interactive viewer.  All API calls are safe before the widget is shown."""

    def __init__(self, parent=None, style: str = "game"):
        super().__init__(parent)
        self.setFormat(make_surface_format(0))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(QSize(160, 120))
        self._state = SceneState(style=normalize_style(style))
        self._renderer: Optional[SceneRenderer] = None
        self._offscreen: Optional[OffscreenViewer] = None
        self._gl_error: Optional[str] = None
        self._last_pos: Optional[QPointF] = None
        self._last_button = None
        self._frame_hook: Optional[Any] = None
        self._need_frame = False

    # ---- Qt integration ----------------------------------------------------
    def initializeGL(self) -> None:  # noqa: N802 (Qt naming)
        try:
            _require_gl()
            self._renderer = SceneRenderer(self._state)
        except Exception as exc:  # keep the widget alive, capture still works
            self._renderer = None
            self._gl_error = str(exc)

    def resizeGL(self, w: int, h: int) -> None:  # noqa: N802
        pass

    def paintGL(self) -> None:  # noqa: N802
        if self._renderer is None:
            return
        dpr = self.devicePixelRatioF() or 1.0
        width = max(1, int(round(self.width() * dpr)))
        height = max(1, int(round(self.height() * dpr)))
        if self._need_frame and self._state.mesh is not None:
            # 第一次真正绘制时才知道视口宽高比，这里再取一次景，保证模型不被切边
            self._need_frame = False
            self.frame_all()
        try:
            self._renderer.render(
                self._state, width, height,
                target_fbo=self.defaultFramebufferObject())
        except Exception as exc:  # never take the UI down over a draw error
            if self._gl_error is None:
                self._gl_error = str(exc)

    # ---- public API --------------------------------------------------------
    def update_geometry(self):
        """Refresh skinned vertices without reloading materials, textures or camera."""
        self._state.geometry_version += 1
        self.update()

    def set_first_person(self, pose):
        self._state.camera.set_first_person(pose)
        self._need_frame=False
        self.update()

    def set_mesh(self, mesh, materials=None, textures=None, *, preserve_camera=False) -> None:
        if isinstance(mesh, MeshLOD):
            mesh = Mesh(name="inline", lods=[mesh])
        if mesh is not None and not isinstance(mesh, Mesh):
            raise TypeError("set_mesh() expects core.types.Mesh, MeshLOD or None")
        if materials is not None and isinstance(materials, Material):
            materials = [materials]
        if textures is not None and isinstance(textures, Texture):
            textures = [textures]
        same_mesh = mesh is self._state.mesh
        self._state.mesh = mesh
        self._state.materials = list(materials or [])
        # 记住原始材质表：1P 模型常常「一个 section + 四个材质」（打包时没留
        # 分段信息），必要时让用户手动指定整套网格用哪一个材质。
        self._all_materials = list(materials or [])
        self._state.textures = list(textures or [])
        self._state.lod_index = 0
        self._state.mesh_version += 1
        self._state.texture_version += 1
        self._need_frame = not same_mesh and not preserve_camera
        # 同一个网格只是贴图/材质后到（异步解包常见）时**绝不能**重新取景，
        # 否则用户正拖着鼠标看模型，后台贴图一到相机就“啪”地复位。
        if mesh is not None and getattr(mesh, "lods", None) and not same_mesh and not preserve_camera:
            self.frame_all()
        self.update()

    def set_lod(self, index: int) -> None:
        mesh = self._state.mesh
        if mesh is None or not getattr(mesh, "lods", None):
            self._state.lod_index = 0
            return
        idx = max(0, min(int(index), len(mesh.lods) - 1))
        if idx != self._state.lod_index:
            self._state.lod_index = idx
            self._state.mesh_version += 1
            self.frame_all()
        self.update()

    def set_material_override(self, metallic: Optional[float] = None,
                              roughness: Optional[float] = None) -> None:
        self._state.metallic_override = None if metallic is None else float(np.clip(metallic, 0, 1))
        self._state.roughness_override = None if roughness is None else float(np.clip(roughness, 0.02, 1))
        self.update()

    def set_texture_override(self, slot: str, rgba) -> None:
        slot = str(slot).lower()
        if slot not in ("base", "normal", "orm", "emissive"):
            raise ValueError("slot must be 'base', 'normal', 'orm' or 'emissive'")
        if rgba is None:
            self._state.texture_override.pop(slot, None)
        else:
            if isinstance(rgba, Texture):
                self._state.texture_override[slot] = rgba
            else:
                arr = _as_texture_array(rgba)
                self._state.texture_override[slot] = np.array(arr, copy=True) if arr is not None else None
        self._state.texture_version += 1
        self.update()

    def set_lighting(self, params: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
        self._state.lighting.merge(params, **kwargs)
        self.update()

    def set_single_material(self, index: int) -> None:
        """整个网格统一用第 index 个材质渲染。

        该游戏的 1P 模型有四个材质（枪身/屏幕/贴花…），但 cooked 数据里只留了
        一个 section，没法自动分段；在材质页选一行、点「整套用这个」就能手动纠正，
        比看着四件套共用第一张贴图强。
        """
        mats = list(getattr(self, "_all_materials", []) or [])
        if not mats:
            return
        index = max(0, min(int(index), len(mats) - 1))
        self._state.materials = [mats[index]] * len(mats)
        self._state.mesh_version += 1
        self.update()

    def set_uv_channel(self, index: int) -> None:
        """挑这套 LOD 的第几套 UV 去采样贴图（默认 UV0）。

        该游戏的静态/骨骼网格普遍带 2~3 套 UV；材质里没记录 TexCoord 索引，
        所以留一个手动开关：切错通道时贴图还在、但整块位置全错——这类问题
        光看贴图文件是查不出来的，必须能在视口里当场对比。
        """
        lod = self._state.active_lod()
        have = int(getattr(lod, "uv_channel_count", 1) or 1) if lod is not None else 1
        idx = max(0, int(index))
        if have > 1:
            idx = min(idx, have - 1)
        else:
            idx = 0
        if idx != self._state.uv_channel:
            self._state.uv_channel = idx
            self.update()

    def set_style(self, name: str) -> None:
        canonical = normalize_style(name)
        if canonical not in STYLE_IDS:
            raise ValueError(f"unknown style {name!r}; choose from {STYLE_NAMES}")
        self._state.style = canonical
        self.update()

    def set_exposure(self, ev: float) -> None:
        self._state.exposure_ev = max(-8.0, min(8.0, float(ev)))
        self.update()

    def set_background(self, kind: str) -> None:
        kind = str(kind).lower()
        if kind not in BACKGROUND_IDS:
            raise ValueError(f"unknown background {kind!r}; choose from {tuple(BACKGROUND_IDS)}")
        self._state.background = kind
        self.update()

    def reset_camera(self) -> None:
        self._state.camera.reset()
        if self._state.mesh is not None:
            self.frame_all()
        else:
            self.update()

    def frame_all(self) -> None:
        center, radius = mesh_bounds(self._state.mesh, self._state.lod_index)
        w = max(1, self.width())
        h = max(1, self.height())
        self._state.camera.frame(center, radius, aspect=w / float(h))
        self.update()

    def set_wireframe(self, on: bool) -> None:
        self._state.wireframe = bool(on)
        self.update()

    # -- 检视演示（转台动画） -------------------------------------------------
    def start_inspect(self, duration: float = 3.2) -> None:
        """按给定时长绕竖轴转一圈，配合一点俯仰摆动。

        该游戏的检视动画是 ACL 压缩的骨骼序列，播放它需要 ACL 解码器 +
        骨骼蒙皮；在补上那套之前，用「同节奏转台」把物品 360° 展示出来。
        """
        duration = max(0.6, float(duration or 3.2))
        from PySide6.QtCore import QTimer as _QTimer
        if getattr(self, "_inspect_timer", None) is None:
            self._inspect_timer = _QTimer(self)
            self._inspect_timer.timeout.connect(self._inspect_step)
        self._inspect_duration = duration
        self._inspect_t = 0.0
        self._inspect_yaw0 = float(self._state.camera.yaw)
        self._inspect_pitch0 = float(self._state.camera.pitch)
        self._inspect_timer.start(16)

    def stop_inspect(self) -> None:
        timer = getattr(self, "_inspect_timer", None)
        if timer is not None:
            timer.stop()
        self._inspect_t = None

    def is_inspecting(self) -> bool:
        return getattr(self, "_inspect_t", None) is not None

    def _inspect_step(self) -> None:
        t = getattr(self, "_inspect_t", None)
        if t is None:
            return
        duration = float(getattr(self, "_inspect_duration", 3.2))
        t += 0.016
        if t >= duration:                     # 循环播放
            t -= duration
        self._inspect_t = t
        phase = t / duration
        self._state.camera.yaw = self._inspect_yaw0 + 360.0 * phase
        self._state.camera.pitch = self._inspect_pitch0 + 6.0 * math.sin(phase * 2.0 * math.pi)
        self.update()

    def set_show_untextured(self, on: bool) -> None:
        """显示/隐藏「一张贴图都没有的 Masked/Translucent 面」（手机屏、序列帧）。"""
        self._state.show_untextured = bool(on)
        self.update()

    def capture(self, path: str, width: int = DEFAULT_CAPTURE_SIZE[0],
                height: int = DEFAULT_CAPTURE_SIZE[1]) -> str:
        """Render through a private offscreen context and save PNG (no display)."""
        if self._offscreen is None:
            self._offscreen = OffscreenViewer(self._state)
        return self._offscreen.capture(path, width, height)

    def preview(self, width: int = DEFAULT_CAPTURE_SIZE[0],
                height: int = DEFAULT_CAPTURE_SIZE[1]) -> np.ndarray:
        if self._offscreen is None:
            self._offscreen = OffscreenViewer(self._state)
        self._offscreen.state = self._state
        return self._offscreen.render(width, height)

    # ---- introspection -----------------------------------------------------
    @property
    def state(self) -> SceneState:
        return self._state

    @property
    def gl_info(self) -> Dict[str, Any]:
        if self._renderer is not None:
            return self._renderer.gl_info()
        if self._offscreen is not None:
            return self._offscreen.gl_info
        return {"error": self._gl_error or "not initialized"}

    @property
    def gl_error(self) -> Optional[str]:
        return self._gl_error

    # ---- interaction -------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._last_pos = event.position()
        self._last_button = event.button()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._last_pos is None:
            return
        pos = event.position()
        dx = pos.x() - self._last_pos.x()
        dy = pos.y() - self._last_pos.y()
        cam = self._state.camera
        if event.buttons() & Qt.MouseButton.LeftButton:
            cam.orbit(dx, dy)
            self.update()
        elif event.buttons() & (Qt.MouseButton.MiddleButton | Qt.MouseButton.RightButton):
            cam.pan(dx, dy, max(1, self.height()))
            self.update()
        self._last_pos = pos

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._last_pos = None
        self._last_button = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y() / 120.0
        self._state.camera.zoom(delta)
        self.update()


configure_surface_format(0)

__all__ = [
    "MeshViewer", "OffscreenViewer", "SceneState", "SceneRenderer", "Camera",
    "PreparedLOD", "prepare_lod", "mesh_bounds", "save_png",
    "configure_surface_format", "make_surface_format",
]
