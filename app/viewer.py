"""Viewport mounting + normalized viewer API.

`render.MeshViewer` (the real GPU renderer, owned by the render agent) is used
whenever a GL context is actually available. On a headless/offscreen platform
there is no reachable GL context at all (`QOpenGLContext.create()` fails), and a
`QOpenGLWidget` cannot be grabbed into a screenshot, so the software shaded
`FallbackViewer` is mounted instead. Both expose the same documented method set;
`Viewport` is the thin proxy the UI talks to, so neither the pages nor the
inspector know which backend is live.

Selection order:
    VERTEXVIEWER_VIEWER=gl         force render.MeshViewer (fallback on error)
    VERTEXVIEWER_VIEWER=fallback   force the software viewer
    unset / auto               software on offscreen/minimal, GL otherwise
"""
from __future__ import annotations

import os
from typing import Any, Optional, Tuple

from app.fluent_api import QApplication, QLabel, Qt, QVBoxLayout, QWidget
from app.fallback_view import MAX_TRIS, FallbackViewer

__all__ = ["Viewport", "create_viewport", "renderer_module", "GL_AVAILABLE"]


def _platform_name() -> str:
    app = QApplication.instance()
    try:
        return app.platformName() if app is not None else ""
    except Exception:                                       # noqa: BLE001
        return ""


def renderer_module():
    """The `render` package if it is importable, else None."""
    try:
        import render as mod
    except Exception:                                       # noqa: BLE001
        return None
    return mod if hasattr(mod, "MeshViewer") else None


GL_AVAILABLE = renderer_module() is not None


class Viewport(QWidget):
    """Holds either `render.MeshViewer` or `FallbackViewer` and proxies the API."""

    def __init__(self, parent=None, force: Optional[str] = None,
                 host: Optional[QWidget] = None) -> None:
        super().__init__(parent or host)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.backend, self.backend_detail, self.inner = self._make_inner(force)
        self._mesh = None
        self._triangles = None
        if self.inner is not None:
            layout.addWidget(self.inner)
        else:  # both backends failed -- keep the window usable
            self.inner = QLabel("渲染器加载中…")
            self.inner.setAlignment(Qt.AlignCenter)
            layout.addWidget(self.inner)
            self.backend, self.backend_detail = "none", "no viewer backend"
        self.setMinimumSize(320, 240)

    # -- construction ------------------------------------------------------ #
    def _make_inner(self, force: Optional[str]) -> Tuple[str, str, Any]:
        choice = (force or os.environ.get("VERTEXVIEWER_VIEWER") or "auto").strip().lower()
        platform = _platform_name()
        if choice == "fallback":
            return "software", "VERTEXVIEWER_VIEWER=fallback", FallbackViewer(self)
        if choice == "auto" and platform in ("offscreen", "minimal"):
            return ("software",
                    f"platform={platform}: no GL grab, software shading",
                    FallbackViewer(self))
        mod = renderer_module()
        if mod is None:
            return "software", "render.MeshViewer unavailable", FallbackViewer(self)
        try:
            widget = mod.MeshViewer(self)
        except Exception as exc:                            # noqa: BLE001
            return "software", f"MeshViewer init failed: {exc}", FallbackViewer(self)
        err = getattr(widget, "gl_error", None)
        if err:
            try:
                widget.deleteLater()
            except Exception:                               # noqa: BLE001
                pass
            return "software", f"GL init failed: {err}", FallbackViewer(self)
        return "gl", "render.MeshViewer (OpenGL)", widget

    # -- pass-through API -------------------------------------------------- #
    @property
    def is_gl(self) -> bool:
        return self.backend == "gl"

    @property
    def triangle_count(self) -> int:
        inner = self.inner
        if hasattr(inner, "triangle_count"):
            try:
                return int(inner.triangle_count)
            except Exception:                               # noqa: BLE001
                return 0
        if self._triangles is not None:                     # 我们自己记的，见 set_mesh
            return int(self._triangles)
        state = getattr(inner, "state", None)
        lod = getattr(state, "lod", None)
        if lod is not None:
            try:
                return int(lod.triangle_count)
            except Exception:                               # noqa: BLE001
                return 0
        return 0

    def params(self) -> dict:
        if hasattr(self.inner, "params"):
            try:
                return dict(self.inner.params())
            except Exception:                               # noqa: BLE001
                return {}
        state = getattr(self.inner, "state", None)
        if state is None:
            return {}
        return {
            "style": getattr(state, "style", ""),
            "exposure": getattr(state, "exposure_ev", 0.0),
            "background": getattr(state, "background", ""),
            "wireframe": getattr(state, "wireframe", False),
        }

    def update_geometry(self):
        if hasattr(self.inner, "update_geometry"):
            self.inner.update_geometry()
        elif self._mesh is not None:
            # Software preview keeps its own projected triangle cache.
            self.inner.set_mesh(self._mesh, self._animation_materials, self._animation_textures, preserve_camera=True)

    def set_first_person(self, pose):
        self.inner.set_first_person(pose)

    def set_mesh(self, mesh, materials=None, textures=None, *, preserve_camera=False) -> None:
        self._animation_materials = materials
        self._animation_textures = textures
        self._mesh = mesh
        self._set_triangle_count(0)
        self.inner.set_mesh(mesh, materials, textures, preserve_camera=preserve_camera)
        self._set_triangle_count(0)

    def _set_triangle_count(self, index: int) -> None:
        lods = getattr(self._mesh, "lods", None) or []
        if 0 <= index < len(lods):
            try:
                self._triangles = int(len(lods[index].indices) // 3)
            except Exception:                               # noqa: BLE001
                self._triangles = None

    def set_lod(self, index: int) -> None:
        self.inner.set_lod(index)
        self._set_triangle_count(index)

    def set_material_override(self, metallic=None, roughness=None) -> None:
        self.inner.set_material_override(metallic, roughness)

    def set_texture_override(self, slot, rgba) -> None:
        self.inner.set_texture_override(slot, rgba)

    def set_lighting(self, **params) -> None:
        self.inner.set_lighting(**params)

    def set_single_material(self, index: int) -> None:
        inner = self.inner
        if hasattr(inner, "set_single_material"):
            inner.set_single_material(index)

    def start_inspect(self, duration: float = 3.2) -> None:
        inner = self.inner
        if hasattr(inner, "start_inspect"):
            inner.start_inspect(duration)

    def stop_inspect(self) -> None:
        inner = self.inner
        if hasattr(inner, "stop_inspect"):
            inner.stop_inspect()

    def set_uv_channel(self, index: int) -> None:
        inner = self.inner
        if not hasattr(inner, "set_uv_channel"):
            return
        inner.set_uv_channel(index)

    def set_style(self, name: str) -> None:
        self.inner.set_style(name)

    def set_exposure(self, ev: float) -> None:
        self.inner.set_exposure(ev)

    def set_background(self, kind: str) -> None:
        self.inner.set_background(kind)

    def reset_camera(self) -> None:
        self.inner.reset_camera()

    def frame_all(self) -> None:
        self.inner.frame_all()

    def set_wireframe(self, on: bool) -> None:
        self.inner.set_wireframe(on)

    def set_show_untextured(self, on: bool) -> None:
        if hasattr(self.inner, "set_show_untextured"):
            self.inner.set_show_untextured(bool(on))

    def capture(self, path: str) -> bool:
        """Save the current frame to `path`; returns True on success."""
        import os as _os
        _os.makedirs(_os.path.dirname(_os.path.abspath(path)) or ".", exist_ok=True)
        inner = self.inner
        try:
            result = inner.capture(path)
        except Exception:                                   # noqa: BLE001
            result = False
        if isinstance(result, str):
            return _os.path.exists(path)
        if isinstance(result, bool):
            return result
        return _os.path.exists(path)

    def grab_frame(self):
        """A QPixmap of the viewport (GL backends may need `capture` instead)."""
        return self.grab()


def create_viewport(parent=None, force: Optional[str] = None) -> Viewport:
    return Viewport(parent=parent, force=force)


def describe_backend(viewport: "Viewport") -> str:
    return f"{viewport.backend}: {viewport.backend_detail}"
