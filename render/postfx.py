"""Stylised-look registry plus CPU-side tone mapping helpers.

The GPU does the real work (``shaders/post.frag``); this module owns the
per-style parameter table the viewer uploads, and duplicates the ACES + sRGB
maths in numpy so tests can reason about pixels without a GL context.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Tuple

import numpy as np

# style name -> shader branch id
STYLE_IDS: Dict[str, int] = {
    "pbr": 0,
    "toon": 1,
    "posterize": 2,
    "neon": 3,
    "blueprint": 4,
    "clay": 5,
    "game": 6,
}

STYLE_NAMES = tuple(STYLE_IDS.keys())

# friendly aliases the art-style combo box might send
STYLE_ALIASES: Dict[str, str] = {
    # 「游戏里那种」胶片感
    "df": "game",
    "ingame": "game",
    "art": "game",
    "cinematic": "game",
    "rim": "neon",
    "neonrim": "neon",
    "cel": "toon",
    "cartoon": "toon",
    "flat": "posterize",
    "bands": "posterize",
    "white": "clay",
    "matte": "clay",
    "blue": "blueprint",
    "normal": "pbr",
    "default": "pbr",
}


def normalize_style(name: str) -> str:
    n = str(name).strip().lower()
    return STYLE_ALIASES.get(n, n)

# per-style uniforms + post parameters
#   outline        : inverted-hull width as a fraction of the scene radius (0 = off)
#   outline_color  : linear RGB of the hull
#   bloom, vignette, saturation, grain : post.frag uniforms
STYLE_PARAMS: Dict[str, Dict[str, Any]] = {
    "pbr": dict(
        rim_strength=0.35, rim_color=(1.0, 1.0, 1.0),
        posterize_levels=6.0, hue_shift=0.0,
        style_color=(0.70, 0.70, 0.70), grid_scale=4.0,
        saturation=1.0, bloom=0.0, vignette=0.32, grain=0.004,
        outline=0.0, outline_color=(0.02, 0.02, 0.025),
    ),
    "toon": dict(
        rim_strength=1.30, rim_color=(1.0, 0.90, 0.72),
        posterize_levels=4.0, hue_shift=0.0,
        style_color=(0.95, 0.85, 0.70), grid_scale=4.0,
        saturation=1.10, bloom=0.0, vignette=0.26, grain=0.004,
        outline=0.011, outline_color=(0.015, 0.015, 0.02),
    ),
    "posterize": dict(
        rim_strength=0.6, rim_color=(1.0, 1.0, 1.0),
        posterize_levels=4.0, hue_shift=0.45,
        style_color=(0.70, 0.70, 0.70), grid_scale=4.0,
        saturation=1.30, bloom=0.0, vignette=0.30, grain=0.004,
        outline=0.0, outline_color=(0.02, 0.02, 0.025),
    ),
    "neon": dict(
        rim_strength=2.10, rim_color=(0.15, 0.85, 1.0),
        posterize_levels=4.0, hue_shift=0.0,
        style_color=(0.05, 0.09, 0.20), grid_scale=4.0,
        saturation=1.25, bloom=0.70, vignette=0.55, grain=0.006,
        outline=0.0, outline_color=(0.02, 0.02, 0.025),
    ),
    "blueprint": dict(
        rim_strength=0.4, rim_color=(0.7, 0.9, 1.0),
        posterize_levels=4.0, hue_shift=0.0,
        style_color=(0.07, 0.17, 0.42), grid_scale=10.0,
        saturation=1.0, bloom=0.0, vignette=0.30, grain=0.003,
        outline=0.0, outline_color=(0.02, 0.02, 0.025),
    ),
    "game": dict(
        # Keep material highlights; no extra bloom or painted-on white rim.
        rim_strength=0.0, rim_color=(1.0, 0.93, 0.82),
        posterize_levels=6.0, hue_shift=0.0,
        style_color=(0.62, 0.66, 0.72), grid_scale=4.0,
        saturation=1.05, bloom=0.0, vignette=0.30, grain=0.005,
        contrast=1.07, ca=0.0009,
        outline=0.0, outline_color=(0.02, 0.02, 0.025),
    ),
    "clay": dict(
        rim_strength=0.55, rim_color=(1.0, 0.98, 0.95),
        posterize_levels=4.0, hue_shift=0.0,
        style_color=(0.78, 0.73, 0.66), grid_scale=4.0,
        saturation=1.0, bloom=0.0, vignette=0.30, grain=0.003,
        outline=0.0, outline_color=(0.02, 0.02, 0.025),
    ),
}

# background kinds -> bg.frag u_kind
BACKGROUND_IDS: Dict[str, int] = {"studio": 0, "gradient": 1, "dark": 2}


def style_id(name: str) -> int:
    n = normalize_style(name)
    if n not in STYLE_IDS:
        raise ValueError(f"unknown style {name!r}; choose from {STYLE_NAMES}")
    return STYLE_IDS[n]


def style_params(name: str) -> Dict[str, Any]:
    n = normalize_style(name)
    return STYLE_PARAMS[n if n in STYLE_PARAMS else "pbr"]


# --------------------------------------------------------------------------- #
# CPU tonemap reference (mirrors post.frag)
# --------------------------------------------------------------------------- #
def aces_fit(x: np.ndarray) -> np.ndarray:
    a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
    x = np.asarray(x, np.float64)
    return np.clip((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0)


def srgb_encode(c: np.ndarray) -> np.ndarray:
    c = np.clip(np.asarray(c, np.float64), 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def tonemap(rgb: np.ndarray, exposure_ev: float = 0.0) -> np.ndarray:
    return srgb_encode(aces_fit(np.asarray(rgb, np.float64) * (2.0 ** exposure_ev)))


# --------------------------------------------------------------------------- #
# image statistics (used by the unattended acceptance run)
# --------------------------------------------------------------------------- #
def image_stats(img: np.ndarray) -> Dict[str, float]:
    """Stats of an (H, W, 3|4) uint8 or float image, normalised to 0..1."""
    a = np.asarray(img)
    if a.dtype == np.uint8:
        a = a.astype(np.float64) / 255.0
    else:
        a = a.astype(np.float64)
    if a.ndim == 3:
        a = a[..., :3]
    return {
        "mean": float(a.mean()),
        "std": float(a.std()),
        "min": float(a.min()),
        "max": float(a.max()),
        "p01": float(np.percentile(a, 1)),
        "p99": float(np.percentile(a, 99)),
    }


def mean_color(img: np.ndarray) -> np.ndarray:
    a = np.asarray(img)
    if a.dtype == np.uint8:
        a = a.astype(np.float64) / 255.0
    if a.ndim == 3:
        a = a[..., :3]
    return a.reshape(-1, a.shape[-1]).mean(axis=0)


def color_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Mean absolute per-channel difference between two images (0..1)."""
    x, y = np.asarray(a), np.asarray(b)
    if x.shape != y.shape:
        raise ValueError(f"shape mismatch {x.shape} vs {y.shape}")
    if x.dtype == np.uint8:
        x = x.astype(np.float64) / 255.0
    if y.dtype == np.uint8:
        y = y.astype(np.float64) / 255.0
    x = x[..., :3]
    y = y[..., :3]
    return float(np.abs(x - y).mean())


def clip01(img: np.ndarray) -> np.ndarray:
    """HDR linear rgb -> 8-bit sRGB, for CPU previews/debug dumps."""
    return (np.clip(tonemap(img), 0, 1) * 255.0 + 0.5).astype(np.uint8)


__all__ = [
    "STYLE_IDS", "STYLE_NAMES", "STYLE_PARAMS", "STYLE_ALIASES", "BACKGROUND_IDS",
    "normalize_style", "style_id", "style_params", "aces_fit", "srgb_encode",
    "tonemap", "image_stats", "mean_color", "color_distance", "clip01",
]
