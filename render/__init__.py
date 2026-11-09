"""VertexViewer rendering package.

    from render import MeshViewer, configure_surface_format

Call :func:`configure_surface_format` *before* creating the ``QApplication`` so
the widget gets a 3.3 core-profile context (depth 24), then instantiate
``MeshViewer`` and drive it through its documented API.
"""
from __future__ import annotations

from .lighting import (
    DirectionalLight, LightingState, angles_from_dir, dir_from_angles,
    look_at, ortho, perspective, shadow_matrix,
)
from .postfx import (
    BACKGROUND_IDS, STYLE_ALIASES, STYLE_IDS, STYLE_NAMES, STYLE_PARAMS,
    image_stats, color_distance, mean_color, normalize_style, style_id,
    style_params,
)
from .viewer import (
    Camera, MeshViewer, OffscreenViewer, PreparedLOD, SceneRenderer, SceneState,
    configure_surface_format, make_surface_format, mesh_bounds, prepare_lod,
    save_png,
)

__all__ = [
    "MeshViewer", "OffscreenViewer", "SceneRenderer", "SceneState", "Camera",
    "PreparedLOD", "prepare_lod", "mesh_bounds", "save_png",
    "configure_surface_format", "make_surface_format",
    "LightingState", "DirectionalLight", "dir_from_angles", "angles_from_dir",
    "look_at", "perspective", "ortho", "shadow_matrix",
    "STYLE_IDS", "STYLE_NAMES", "STYLE_ALIASES", "STYLE_PARAMS", "BACKGROUND_IDS",
    "normalize_style", "style_id", "style_params",
    "image_stats", "mean_color", "color_distance",
]
