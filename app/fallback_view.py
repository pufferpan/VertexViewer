"""Software shaded stand-in for `render.MeshViewer`.

`render.MeshViewer` is a `QOpenGLWidget` owned by the renderer agent. Until that
module lands (or on a machine without a usable GL driver) the window swaps in
this widget. It implements **the exact same method contract** so the rest of the
UI never needs to know which one is mounted:

    set_mesh(mesh, materials=None, textures=None)   set_lod(i)
    set_material_override(metallic=None, roughness=None)
    set_texture_override(slot, rgba)                set_lighting(**params)
    set_style(name)                                 set_exposure(ev)
    set_background(kind)                            reset_camera() / frame_all()
    set_wireframe(bool)                             capture(path)

Implementation: numpy shading of the triangle soup + `QPainter` for the actual
polys (painter's algorithm, so no depth buffer needed). 12k triangles are drawn
per frame which keeps an offscreen screenshot under ~150 ms.

With no mesh loaded it renders a procedural torus knot demo so the viewport is
never a grey rectangle (and so screenshots always show real shading).
"""
from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Sequence

import numpy as np

from app.fluent_api import (QColor, QFont, QLinearGradient, QPainter, QPen,
                            QPointF, QPolygonF, QRadialGradient, Qt, QWidget)

MAX_TRIS = 12000


# --------------------------------------------------------------------------- #
# geometry helpers
# --------------------------------------------------------------------------- #
def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    n[n < 1e-9] = 1.0
    return v / n


def demo_geometry(segments: int = 140, sides: int = 18):
    """Torus knot (p=3, q=5): positions/normals/index buffer in GL metres."""
    t = np.linspace(0.0, 2.0 * math.pi, segments, endpoint=False)
    p, q = 3.0, 5.0
    r = 2.0 + np.cos(q * t)
    x = r * np.cos(p * t)
    y = r * np.sin(p * t)
    z = np.sin(q * t) * 1.4
    centre = np.stack([x, y, z], axis=1)

    dt = 1e-3
    r2 = 2.0 + np.cos(q * (t + dt))
    x2 = r2 * np.cos(p * (t + dt))
    y2 = r2 * np.sin(p * (t + dt))
    z2 = np.sin(q * (t + dt)) * 1.4
    tangent = np.stack([x2 - x, y2 - y, z2 - z], axis=1)
    tangent = _normalize(tangent)
    up = np.array([0.0, 0.0, 1.0])
    normal = _normalize(np.cross(tangent, up))
    binormal = _normalize(np.cross(tangent, normal))

    tube = 0.45
    ang = np.linspace(0.0, 2.0 * math.pi, sides, endpoint=False)
    ca, sa = np.cos(ang)[None, :, None], np.sin(ang)[None, :, None]
    ring_dir = normal[:, None, :] * ca + binormal[:, None, :] * sa
    positions = centre[:, None, :] + ring_dir * tube
    normals = _normalize(ring_dir)

    idx = []
    for i in range(segments):
        i2 = (i + 1) % segments
        for j in range(sides):
            j2 = (j + 1) % sides
            a = i * sides + j
            b = i * sides + j2
            c = i2 * sides + j2
            d = i2 * sides + j
            idx += [a, b, c, a, c, d]

    pos = positions.reshape(-1, 3) * 0.12
    nrm = normals.reshape(-1, 3)
    return pos.astype(np.float32), nrm.astype(np.float32), np.asarray(idx, np.int64)


# --------------------------------------------------------------------------- #
# viewer
# --------------------------------------------------------------------------- #
class FallbackViewer(QWidget):
    DEFAULT_LIGHTING: Dict[str, object] = {
        "azimuth": 42.0, "elevation": 38.0, "intensity": 1.35,
        "color": (1.0, 0.97, 0.92), "fill": 0.42, "rim": 0.55, "ambient": 0.18,
    }
    STYLES = ("game", "pbr", "toon", "posterize", "neon", "blueprint", "clay")
    BACKGROUNDS = ("studio", "gradient", "dark", "grid", "white")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(420, 320)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

        self._mesh = None
        self._lod_index = 0
        self._materials: List[object] = []
        self._textures: List[object] = []
        self._pos: Optional[np.ndarray] = None
        self._nrm: Optional[np.ndarray] = None
        self._idx: Optional[np.ndarray] = None
        self._tri_mat: Optional[np.ndarray] = None
        self._base_rgb = np.array([0.72, 0.72, 0.75], np.float32)

        self._metallic: Optional[float] = None
        self._roughness: Optional[float] = None
        self._style = "game"
        self._exposure = 0.0
        self._background = "studio"
        self._wireframe = False
        self._lighting = dict(self.DEFAULT_LIGHTING)
        self._tex_override: Dict[str, np.ndarray] = {}

        self._yaw = -38.0
        self._pitch = 20.0
        self._zoom = 1.0
        self._first_person=None
        self._center = np.zeros(3, np.float32)
        self._radius = 1.0
        self._drag_origin = None
        self._demo = True
        self._info = ""

        self.set_demo_mesh()

    # -- contract ---------------------------------------------------------- #
    def set_mesh(self, mesh, materials=None, textures=None, *, preserve_camera=False) -> None:
        self._mesh = mesh
        self._materials = list(materials or [])
        self._textures = list(textures or [])
        self._demo = mesh is None or not getattr(mesh, "lods", None)
        if self._demo:
            self.set_demo_mesh()
            return
        self._lod_index = min(self._lod_index, len(mesh.lods) - 1)
        self._load_lod(self._lod_index)
        if not preserve_camera:
            self.reset_camera()

    def set_lod(self, index: int) -> None:
        if self._mesh is None or not getattr(self._mesh, "lods", None):
            return
        index = max(0, min(int(index), len(self._mesh.lods) - 1))
        self._lod_index = index
        self._load_lod(index)
        self.update()

    def set_material_override(self, metallic: Optional[float] = None,
                              roughness: Optional[float] = None) -> None:
        self._metallic = metallic
        self._roughness = roughness
        self.update()

    def set_texture_override(self, slot: str, rgba) -> None:
        if rgba is None:
            self._tex_override.pop(slot, None)
        else:
            arr = np.asarray(rgba)
            if arr.ndim == 3:
                self._tex_override[slot] = arr.reshape(-1, arr.shape[-1]).mean(axis=0) / 255.0
        self.update()

    def set_lighting(self, **params) -> None:
        for key, value in params.items():
            if key in self._lighting:
                self._lighting[key] = value
        self.update()

    def set_style(self, name: str) -> None:
        self._style = (name or "pbr").lower()
        if self._style not in self.STYLES:
            self._style = "game"
        self.update()

    def set_exposure(self, ev: float) -> None:
        self._exposure = float(ev)
        self.update()

    def set_background(self, kind: str) -> None:
        self._background = (kind or "dark").lower()
        self.update()

    def set_wireframe(self, enabled: bool) -> None:
        self._wireframe = bool(enabled)
        self.update()

    def reset_camera(self) -> None:
        self._first_person=None
        self._yaw, self._pitch, self._zoom = -38.0, 20.0, 1.0
        self.update()

    def frame_all(self) -> None:
        self._first_person=None
        self._zoom = 1.0
        self._yaw, self._pitch = -38.0, 20.0
        self.update()

    def set_first_person(self, pose):
        self._first_person=pose
        self.update()

    def capture(self, path: str) -> bool:
        pix = self.grab()
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        return bool(pix.save(path))

    # -- state introspection (used by the UI/tests) ------------------------ #
    def params(self) -> Dict[str, object]:
        return {
            "style": self._style, "exposure": self._exposure,
            "background": self._background, "wireframe": self._wireframe,
            "metallic": self._metallic, "roughness": self._roughness,
            "lod": self._lod_index,
            "triangles": self.triangle_count, "lighting": dict(self._lighting),
            "demo": self._demo,
        }

    @property
    def triangle_count(self) -> int:
        return 0 if self._idx is None else int(len(self._idx) // 3)

    # -- geometry ---------------------------------------------------------- #
    def set_demo_mesh(self) -> None:
        pos, nrm, idx = demo_geometry()
        self._pos, self._nrm, self._idx = pos, nrm, idx
        self._tri_mat = np.zeros(len(idx) // 3, np.int32)
        self._base_rgb = np.array([0.75, 0.74, 0.70], np.float32)
        self._center = ((pos.max(axis=0) + pos.min(axis=0)) * 0.5).astype(np.float32)
        self._radius = float(np.linalg.norm(pos - self._center, axis=1).max()) or 1.0
        self._demo = True
        self._info = "演示网格 · 软件着色占位"
        self.update()

    def _load_lod(self, index: int) -> None:
        lod = self._mesh.lods[index]
        self._pos = np.asarray(lod.positions, np.float32).reshape(-1, 3)
        nrm = None if lod.normals is None else np.asarray(lod.normals, np.float32).reshape(-1, 3)
        if lod.indices is None or len(lod.indices) < 3:
            self._idx = None
            self._tri_mat = None
            self._info = "该 LOD 没有三角形"
            return
        idx = np.asarray(lod.indices, np.int64).reshape(-1)
        if len(idx) % 3:
            idx = idx[: len(idx) // 3 * 3]
        self._idx = idx
        if nrm is None or len(nrm) != len(self._pos):
            tri = self._pos[idx].reshape(-1, 3, 3)
            face = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
            nrm = np.zeros_like(self._pos)
            for k in range(3):
                np.add.at(nrm, idx.reshape(-1, 3)[:, k], face)
            nrm = _normalize(nrm.astype(np.float32))
        self._nrm = nrm

        # triangle -> material index (sections are in index-buffer order)
        mat_of_tri = np.zeros(len(idx) // 3, np.int32)
        sections = list(getattr(lod, "sections", []) or [])
        if sections and self._materials:
            paths = [getattr(m, "pak_path", "") for m in self._materials]
            for sec in sections:
                first = max(0, int(sec.first_index)) // 3
                count = int(sec.num_triangles) or int(sec.num_vertices) // 3
                last = min(len(mat_of_tri), first + max(0, count))
                if last <= first:
                    continue
                mi = 0
                for i, p in enumerate(paths):
                    if p and p == getattr(sec, "material_path", ""):
                        mi = i
                        break
                mat_of_tri[first:last] = mi
        self._tri_mat = mat_of_tri
        self._base_rgb = self._material_color()
        self._center = ((self._pos.max(axis=0) + self._pos.min(axis=0)) * 0.5).astype(np.float32)
        self._radius = float(np.linalg.norm(self._pos - self._center, axis=1).max()) or 1.0
        self._demo = False
        name = getattr(self._mesh, "name", "") or getattr(self._mesh, "pak_path", "")
        self._info = os.path.splitext(os.path.basename(str(name)))[0]

    def _material_color(self) -> np.ndarray:
        for mat in self._materials:
            color = getattr(mat, "base_color", None)
            if color:
                return np.array(color[:3], np.float32)
        return np.array([0.72, 0.72, 0.75], np.float32)

    # -- painting ---------------------------------------------------------- #
    def paintEvent(self, event) -> None:                       # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        self._paint_background(painter, rect)
        if self._pos is None or self._idx is None or len(self._idx) == 0:
            painter.setPen(QPen(QColor(160, 160, 160)))
            painter.drawText(rect, Qt.AlignCenter, "没有可显示的网格\n把 .uasset 拖进来")
            painter.end()
            return

        painter.setRenderHint(QPainter.Antialiasing, True)
        cyaw, syaw = math.cos(math.radians(self._yaw)), math.sin(math.radians(self._yaw))
        cpit, spit = math.cos(math.radians(self._pitch)), math.sin(math.radians(self._pitch))
        rot_y = np.array([[cyaw, 0, syaw], [0, 1, 0], [-syaw, 0, cyaw]], np.float32)
        rot_x = np.array([[1, 0, 0], [0, cpit, -spit], [0, spit, cpit]], np.float32)
        rot = rot_x @ rot_y

        rel = (self._pos - self._center) @ rot.T
        nrel = self._nrm @ rot.T
        scale = (min(rect.width(), rect.height()) * 0.46) / max(self._radius, 1e-6) * self._zoom
        sx = rect.center().x() + rel[:, 0] * scale
        sy = rect.center().y() - rel[:, 1] * scale
        depth = rel[:, 2]
        if self._first_person is not None:
            from render.lighting import look_at
            eye,forward,up=self._first_person
            view=look_at(eye,np.asarray(eye)+forward,up)
            rel=self._pos @ view[:3,:3].T+view[:3,3]
            nrel=self._nrm @ view[:3,:3].T
            distance=np.maximum(-rel[:,2],.001)
            focal=rect.width()*.5
            sx=rect.center().x()+rel[:,0]*focal/distance
            sy=rect.center().y()-rel[:,1]*focal/distance
            depth=rel[:,2]

        tris = self._idx.reshape(-1, 3)
        tri_depth = depth[tris].mean(axis=1)
        tri_mat = self._tri_mat if self._tri_mat is not None else np.zeros(len(tris), np.int32)
        tri_n = _normalize(nrel[tris].mean(axis=1))

        stride = max(1, int(math.ceil(len(tris) / MAX_TRIS)))
        sel = np.arange(0, len(tris), stride)
        if self._first_person is not None:sel=sel[np.all(rel[tris[sel],2]<-.003,axis=1)]
        order = sel[np.argsort(tri_depth[sel])]

        colors = self._shade(tri_n[order], tri_mat[order], rel, order)

        pts = np.stack([sx[tris], sy[tris]], axis=2)          # (M,3,2)
        # AA on polygons leaves hairline gaps between neighbours -> seams; the
        # model is dense enough that crisp edges look better anyway.
        painter.setRenderHint(QPainter.Antialiasing, False)
        pen = QPen(QColor(255, 255, 255, 90)) if self._wireframe else QPen(Qt.NoPen)
        painter.setPen(pen)
        for row, tri_index in enumerate(order):
            poly = pts[tri_index]
            c = colors[row]
            painter.setBrush(QColor(int(c[0]), int(c[1]), int(c[2])))
            painter.drawPolygon(QPolygonF([QPointF(float(poly[0, 0]), float(poly[0, 1])),
                                           QPointF(float(poly[1, 0]), float(poly[1, 1])),
                                           QPointF(float(poly[2, 0]), float(poly[2, 1]))]))

        self._paint_hud(painter, rect, len(tris))
        painter.end()
    def _shade(self, normals: np.ndarray, mat_index: np.ndarray,
               rel: np.ndarray, order: np.ndarray) -> np.ndarray:
        light = self._lighting
        az = math.radians(float(light.get("azimuth", 42.0)))
        el = math.radians(float(light.get("elevation", 38.0)))
        ldir = np.array([math.cos(el) * math.sin(az), math.sin(el),
                         math.cos(el) * math.cos(az)], np.float32)
        ldir /= max(1e-6, float(np.linalg.norm(ldir)))
        fill_dir = _normalize(np.array([-ldir[0], -ldir[1] * 0.4 + 0.5, 0.35], np.float32))
        color = np.array(light.get("color", (1, 1, 1)), np.float32).reshape(3)
        intensity = float(light.get("intensity", 1.35))
        fill = float(light.get("fill", 0.42))
        rim = float(light.get("rim", 0.55))
        ambient = float(light.get("ambient", 0.18))

        base = self._base_rgb.astype(np.float32)
        if "base" in self._tex_override:
            base = base * 0.4 + self._tex_override["base"].astype(np.float32)[:3] * 0.6

        metallic = self._metallic
        if metallic is None:
            metallic = float(getattr(self._materials[0], "metallic", 0.0)) if self._materials else 0.0
        roughness = self._roughness
        if roughness is None:
            roughness = float(getattr(self._materials[0], "roughness", 0.5)) if self._materials else 0.5
        metallic = max(0.0, min(1.0, float(metallic)))
        roughness = max(0.02, min(1.0, float(roughness)))

        n = normals
        view = np.array([0.0, 0.0, 1.0], np.float32)
        diff = np.clip(n @ ldir, 0.0, None)
        fill_l = np.clip(n @ fill_dir, 0.0, None) * fill
        half = _normalize(ldir[None, :] + view[None, :])[0]
        shininess = max(2.0, 2.0 / (roughness * roughness))
        spec = np.power(np.clip(n @ half, 0.0, None), shininess)
        fresnel = np.power(1.0 - np.clip(np.abs(n @ view), 0.0, 1.0), 3.0)
        rim_term = fresnel * rim
        spec_strength = 0.04 + 0.96 * metallic

        if self._style == "toon":
            levels = np.floor((diff * 4.0) + 0.5) / 4.0
            tone = base[None, :] * (levels[:, None] * 0.85 + ambient + fill_l[:, None] * 0.3)
            out = tone + (0.06 * model_tint(base))[None, :] * spec[:, None]
        elif self._style == "posterize":
            lam = ambient + diff * intensity + fill_l
            out = base[None, :] * lam[:, None] + spec[:, None] * spec_strength * 0.5
            out = np.round(np.clip(out, 0, 1) * 6.0) / 6.0
        elif self._style == "neon":
            hue = 0.5 + 0.5 * np.tanh(n[:, 0] * 2.0)
            neon = np.stack([0.15 + 0.85 * hue, 0.25 + 0.4 * np.clip(n[:, 1], 0, 1),
                             0.9 - 0.6 * hue], axis=1)
            out = base[None, :] * 0.12 + neon * (0.25 + 0.55 * rim_term[:, None]) \
                + spec[:, None] * (0.3 + 0.7 * metallic) * 0.5
        elif self._style == "blueprint":
            edge = np.abs(n @ view)
            out = (0.06 + 0.30 * edge)[:, None] * np.array([0.25, 0.55, 1.0], np.float32)[None, :]
        elif self._style == "clay":
            clay = np.array([0.72, 0.60, 0.50], np.float32)
            lam = ambient + diff * intensity * 0.95 + fill_l * 0.6
            soft = np.clip(np.sum(n * ldir, axis=1), 0.0, 1.0) * 0.15
            out = clay[None, :] * np.clip(lam + soft, 0.0, 1.6)[:, None]
        else:  # pbr
            diffuse_col = base[None, :] * (1.0 - 0.35 * metallic)
            lam = ambient + diff * intensity + fill_l
            out = diffuse_col * lam[:, None]
            out = out * (1.0 - 0.15 * metallic) + spec[:, None] * (spec_strength * intensity) \
                * (base[None, :] * (0.3 + 0.7 * metallic) + 0.5)
            out = out + (rim_term[:, None] * 0.28) * color[None, :]
        out = out * 2.0 ** float(self._exposure)
        out = np.clip(np.nan_to_num(out), 0.0, 1.0)
        return (out * 255.0).astype(np.int32)

    def _paint_background(self, painter: QPainter, rect) -> None:
        kind = self._background
        if kind == "white":
            painter.fillRect(rect, QColor(246, 246, 246))
        elif kind == "studio":
            grad = QRadialGradient(rect.center().x(), rect.height() * 0.42,
                                   max(rect.width(), rect.height()) * 0.85)
            grad.setColorAt(0.0, QColor(84, 88, 98))
            grad.setColorAt(0.65, QColor(44, 46, 54))
            grad.setColorAt(1.0, QColor(18, 18, 22))
            painter.fillRect(rect, grad)
        elif kind == "gradient":
            grad = QLinearGradient(0, 0, 0, rect.height())
            grad.setColorAt(0.0, QColor(28, 34, 46))
            grad.setColorAt(1.0, QColor(8, 10, 16))
            painter.fillRect(rect, grad)
        elif kind == "grid":
            painter.fillRect(rect, QColor(30, 30, 34))
            painter.setPen(QPen(QColor(58, 58, 64), 1))
            step = 32
            for x in range(0, rect.width(), step):
                painter.drawLine(x, 0, x, rect.height())
            for y in range(0, rect.height(), step):
                painter.drawLine(0, y, rect.width(), y)
        else:
            painter.fillRect(rect, QColor(24, 24, 28))

    def _paint_hud(self, painter: QPainter, rect, tris: int) -> None:
        painter.setPen(QPen(QColor(200, 200, 205)))
        font = QFont("Segoe UI")
        font.setPixelSize(11)
        painter.setFont(font)
        text = f"{self._info}" if self._info else ""
        meta = f"LOD {self._lod_index} · {tris} tris · {self._style}"
        if self._demo:
            meta += " · 软件着色占位"
        painter.drawText(rect.adjusted(12, 8, -12, -12), Qt.AlignLeft | Qt.AlignTop, text)
        painter.drawText(rect.adjusted(12, 22, -12, -12), Qt.AlignLeft | Qt.AlignTop, meta)

    # -- interaction ------------------------------------------------------- #
    def mousePressEvent(self, event) -> None:                  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_origin = event.position()

    def mouseMoveEvent(self, event) -> None:                   # noqa: N802
        if self._first_person is not None:return
        if self._drag_origin is None:
            return
        delta = event.position() - self._drag_origin
        self._drag_origin = event.position()
        self._yaw += delta.x() * 0.5
        self._pitch = max(-89.0, min(89.0, self._pitch + delta.y() * 0.5))
        self.update()

    def mouseReleaseEvent(self, event) -> None:                # noqa: N802
        self._drag_origin = None

    def wheelEvent(self, event) -> None:                       # noqa: N802
        if self._first_person is not None:return
        steps = event.angleDelta().y() / 120.0
        self._zoom = max(0.15, min(8.0, self._zoom * (1.12 ** steps)))
        self.update()


def model_tint(base: np.ndarray) -> np.ndarray:
    return np.array([base[2], base[0] * 0.6, base[1] * 0.8], np.float32)
