"""Lighting model for the VertexViewer renderer.

Pure numpy / dataclasses -- no Qt, no OpenGL -- so it can be unit tested and
reused by the UI layer (the sliders bind straight to :class:`LightingState`).

Convention
----------
A light's ``direction`` is the unit vector pointing **from the surface toward
the light** (what you would feed to ``dot(N, L)``).  The UI exposes azimuth
(degrees, around +Y, 0 = +X, 90 = +Z) and elevation (degrees above the
horizon), which is friendlier than raw vectors.

Ambient light is a two-colour hemisphere: ``top`` for normals pointing up,
``bottom`` for normals pointing down.  Together with ``env_intensity`` it also
drives the analytic sky used for the IBL approximation in the shaders, so no
HDRI file is ever needed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

Vec3 = Tuple[float, float, float]

# --------------------------------------------------------------------------- #
# math helpers (row-major numpy matrices; the GL layer transposes on upload)
# --------------------------------------------------------------------------- #
def normalize(v: Sequence[float]) -> np.ndarray:
    a = np.asarray(v, dtype=np.float64).reshape(3)
    n = float(np.linalg.norm(a))
    if n < 1e-12:
        return np.array([0.0, 1.0, 0.0])
    return a / n


def dir_from_angles(azimuth: float, elevation: float) -> Vec3:
    """Azimuth/elevation in degrees -> unit vector toward the light."""
    az = math.radians(float(azimuth))
    el = math.radians(float(elevation))
    c = math.cos(el)
    return (c * math.cos(az), math.sin(el), c * math.sin(az))


def angles_from_dir(direction: Sequence[float]) -> Tuple[float, float]:
    d = normalize(direction)
    elev = math.degrees(math.asin(max(-1.0, min(1.0, float(d[1])))))
    az = math.degrees(math.atan2(float(d[2]), float(d[0])))
    return az, elev


def look_at(eye: Sequence[float], center: Sequence[float],
            up: Sequence[float] = (0.0, 1.0, 0.0)) -> np.ndarray:
    eye = np.asarray(eye, np.float64)
    center = np.asarray(center, np.float64)
    up = np.asarray(up, np.float64)
    f = normalize(center - eye)
    if abs(float(np.dot(f, normalize(up)))) > 0.999:
        up = np.array([0.0, 0.0, 1.0]) if abs(f[1]) > 0.9 else np.array([0.0, 1.0, 0.0])
    s = normalize(np.cross(f, up))
    u = np.cross(s, f)
    m = np.eye(4)
    m[0, :3] = s
    m[1, :3] = u
    m[2, :3] = -f
    m[0, 3] = -float(np.dot(s, eye))
    m[1, 3] = -float(np.dot(u, eye))
    m[2, 3] = float(np.dot(f, eye))
    return m


def perspective(fov_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    t = 1.0 / math.tan(math.radians(fov_deg) * 0.5)
    m = np.zeros((4, 4), np.float64)
    m[0, 0] = t / max(aspect, 1e-6)
    m[1, 1] = t
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2.0 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def ortho(left: float, right: float, bottom: float, top: float,
          near: float, far: float) -> np.ndarray:
    m = np.identity(4)
    m[0, 0] = 2.0 / (right - left)
    m[1, 1] = 2.0 / (top - bottom)
    m[2, 2] = -2.0 / (far - near)
    m[0, 3] = -(right + left) / (right - left)
    m[1, 3] = -(top + bottom) / (top - bottom)
    m[2, 3] = -(far + near) / (far - near)
    return m


def shadow_matrix(center: Sequence[float], radius: float,
                  light_dir: Sequence[float]) -> np.ndarray:
    """Orthographic light matrix that tightly covers a bounding sphere."""
    d = normalize(light_dir)
    radius = max(float(radius), 1e-4)
    dist = radius * 2.5
    eye = np.asarray(center, np.float64) + d * dist
    view = look_at(eye, center)
    ext = radius * 1.25
    proj = ortho(-ext, ext, -ext, ext, 0.01, dist + radius * 3.0)
    return proj @ view


def gl_matrix(m: np.ndarray) -> np.ndarray:
    """Row-major numpy matrix -> contiguous column-major array for GLSL."""
    return np.ascontiguousarray(np.asarray(m, np.float32).T)


# --------------------------------------------------------------------------- #
# lights
# --------------------------------------------------------------------------- #
@dataclass
class DirectionalLight:
    """One UI-controllable directional light."""

    name: str = "key"
    azimuth: float = 135.0          # degrees around +Y (0=+X, 90=+Z)
    elevation: float = 40.0         # degrees above the horizon
    intensity: float = 3.2
    color: Vec3 = (1.0, 0.96, 0.90)
    angle: float = 0.12             # angular radius, radians (soft highlight)

    # ---- derived -----------------------------------------------------------
    def direction(self) -> Vec3:
        return dir_from_angles(self.azimuth, self.elevation)

    def radiance(self) -> Tuple[float, float, float]:
        c = np.asarray(self.color, np.float64) * float(self.intensity)
        return (float(c[0]), float(c[1]), float(c[2]))

    def set_direction(self, direction: Sequence[float]) -> None:
        az, el = angles_from_dir(direction)
        self.azimuth, self.elevation = az, el

    def as_dict(self) -> Dict[str, Any]:
        d = self.direction()
        return {
            "azimuth": self.azimuth,
            "elevation": self.elevation,
            "intensity": self.intensity,
            "color": list(self.color),
            "angle": self.angle,
            "direction": [round(float(x), 5) for x in d],
        }


@dataclass
class LightingState:
    """Everything the sliders can touch.  ``merge`` accepts partial updates."""

    key: DirectionalLight = field(default_factory=lambda: DirectionalLight(
        "key", 135.0, 42.0, 3.2, (1.0, 0.96, 0.90), 0.10))
    fill: DirectionalLight = field(default_factory=lambda: DirectionalLight(
        "fill", -55.0, 12.0, 0.9, (0.55, 0.68, 1.0), 0.35))
    rim: DirectionalLight = field(default_factory=lambda: DirectionalLight(
        "rim", 215.0, 28.0, 1.9, (1.0, 0.88, 0.75), 0.20))
    # 稍微亮一点的天空光：黑枪（M4A1/AK 这些默认涂装）也能看出导轨和棱角
    ambient_top: Vec3 = (0.30, 0.35, 0.46)
    ambient_bottom: Vec3 = (0.10, 0.093, 0.085)
    env_intensity: float = 1.15
    shadow: bool = True

    # ---- queries -----------------------------------------------------------
    @property
    def lights(self) -> Tuple[DirectionalLight, DirectionalLight, DirectionalLight]:
        return (self.key, self.fill, self.rim)

    def uniform_arrays(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        dirs = np.zeros((3, 3), np.float32)
        cols = np.zeros((3, 3), np.float32)
        angs = np.zeros(3, np.float32)
        for i, l in enumerate(self.lights):
            dirs[i] = l.direction()
            cols[i] = l.radiance()
            angs[i] = max(0.0, float(l.angle))
        return dirs, cols, angs

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key.as_dict(),
            "fill": self.fill.as_dict(),
            "rim": self.rim.as_dict(),
            "ambient": {"top": list(self.ambient_top),
                        "bottom": list(self.ambient_bottom)},
            "env_intensity": self.env_intensity,
            "shadow": self.shadow,
        }

    # ---- mutation ----------------------------------------------------------
    def merge(self, params: Optional[Dict[str, Any]] = None,
              **kwargs: Any) -> "LightingState":
        """Apply a partial update.

        Accepted keys
        -------------
        ``key_dir`` / ``fill_dir`` / ``rim_dir``
            dict with azimuth/elevation/intensity/color/angle, or a 3-sequence
            interpreted as the direction vector toward the light.
        ``key_azimuth``, ``key_elevation``, ``key_intensity``, ``key_color``,
        ``key_angle`` (same for fill/rim)
            flat single-property updates.
        ``ambient``
            dict with ``top`` / ``bottom`` / ``intensity``.
        ``ambient_top``, ``ambient_bottom``, ``env_intensity``, ``shadow``
        """
        data: Dict[str, Any] = {}
        if params:
            if not isinstance(params, dict):
                raise TypeError("set_lighting() expects a dict or keyword arguments")
            data.update(params)
        data.update(kwargs)

        for name in ("key", "fill", "rim"):
            light: DirectionalLight = getattr(self, name)
            sub = data.pop(f"{name}_dir", None)
            if sub is not None:
                _apply_light_sub(light, sub)
            for prop in ("azimuth", "elevation", "intensity", "color", "angle"):
                key = f"{name}_{prop}"
                if key in data:
                    setattr(light, prop, _coerce_light_prop(prop, data.pop(key)))

        amb = data.pop("ambient", None)
        if isinstance(amb, dict):
            if "top" in amb:
                self.ambient_top = _coerce_color(amb["top"])
            if "bottom" in amb:
                self.ambient_bottom = _coerce_color(amb["bottom"])
            if "intensity" in amb:
                self.env_intensity = float(amb["intensity"])
            if "env_intensity" in amb:
                self.env_intensity = float(amb["env_intensity"])
        if "ambient_top" in data:
            self.ambient_top = _coerce_color(data.pop("ambient_top"))
        if "ambient_bottom" in data:
            self.ambient_bottom = _coerce_color(data.pop("ambient_bottom"))
        if "env_intensity" in data:
            self.env_intensity = max(0.0, float(data.pop("env_intensity")))
        if "shadow" in data:
            self.shadow = bool(data.pop("shadow"))

        self.unknown = tuple(sorted(data.keys())) if data else ()
        return self

    def copy(self) -> "LightingState":
        return LightingState(**{
            "key": replace(self.key), "fill": replace(self.fill), "rim": replace(self.rim),
            "ambient_top": tuple(self.ambient_top),
            "ambient_bottom": tuple(self.ambient_bottom),
            "env_intensity": self.env_intensity, "shadow": self.shadow,
        })


def _coerce_color(v: Any) -> Vec3:
    if isinstance(v, (int, float)):
        x = float(v)
        return (x, x, x)
    a = [float(x) for x in v]
    if len(a) == 1:
        return (a[0], a[0], a[0])
    if len(a) == 2:
        return (a[0], a[1], 1.0)
    return (a[0], a[1], a[2])


def _coerce_light_prop(prop: str, value: Any) -> Any:
    if prop in ("azimuth", "elevation", "intensity", "angle"):
        return float(value)
    if prop == "color":
        return _coerce_color(value)
    return value


def _apply_light_sub(light: DirectionalLight, sub: Any) -> None:
    if isinstance(sub, dict):
        d = dict(sub)
        if "direction" in d:
            light.set_direction(d.pop("direction"))
        if "az" in d and "azimuth" not in d:
            d["azimuth"] = d.pop("az")
        if "elev" in d and "elevation" not in d:
            d["elevation"] = d.pop("elev")
        if "height" in d and "elevation" not in d:
            d["elevation"] = d.pop("height")
        if "power" in d and "intensity" not in d:
            d["intensity"] = d.pop("power")
        for prop in ("azimuth", "elevation", "intensity", "angle"):
            if prop in d:
                setattr(light, prop, float(d[prop]))
        if "color" in d:
            light.color = _coerce_color(d["color"])
        return
    # a bare 3-vector is a direction
    seq = list(sub)
    if len(seq) == 2:
        light.azimuth, light.elevation = float(seq[0]), float(seq[1])
    elif len(seq) == 3:
        light.set_direction(seq)
    else:
        raise ValueError(f"cannot interpret light spec {sub!r}")


__all__ = [
    "DirectionalLight", "LightingState", "dir_from_angles", "angles_from_dir",
    "look_at", "perspective", "ortho", "shadow_matrix", "gl_matrix", "normalize",
]
