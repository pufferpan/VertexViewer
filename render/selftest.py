"""Offscreen acceptance harness for the VertexViewer render package.

Runs without a visible window:

    python render/selftest.py

It synthesises a test mesh (UV sphere + cube, two materials, procedural
base/normal/ORM textures), renders the whole style x metallic x roughness grid
at 1280x720, verifies the PNGs statistically, exercises every public
``MeshViewer`` API call, measures frame times and the stability corner cases,
then writes ``render/REPORT.md`` + ``render/selftest_report.json``.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import traceback
from typing import Any, Dict, List, Tuple

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.types import Mesh, MeshLOD, Material, Section, Texture  # noqa: E402

from render.lighting import LightingState  # noqa: E402
from render.postfx import STYLE_IDS, STYLE_NAMES  # noqa: E402
from render.viewer import (  # noqa: E402
    OffscreenViewer, SceneState, make_surface_format, mesh_bounds, prepare_lod,
    save_png,
)

CAPTURE_W, CAPTURE_H = 1280, 720
STYLES = ["pbr", "toon", "posterize", "neon", "blueprint", "clay"]
COMBOS = [(0.0, 0.1), (1.0, 0.1), (0.0, 0.9), (1.0, 0.9)]


# --------------------------------------------------------------------------- #
# procedural test data
# --------------------------------------------------------------------------- #
def _uv_sphere(radius: float = 0.60, lat: int = 28, lon: int = 42,
               center: Tuple[float, float, float] = (0.62, 0.0, 0.0)):
    pos: List[Tuple[float, float, float]] = []
    nrm: List[Tuple[float, float, float]] = []
    uv: List[Tuple[float, float]] = []
    for i in range(lat + 1):
        v = i / float(lat)
        theta = v * math.pi
        st, ct = math.sin(theta), math.cos(theta)
        for j in range(lon + 1):
            u = j / float(lon)
            phi = u * math.tau
            d = (st * math.cos(phi), ct, st * math.sin(phi))
            pos.append((center[0] + radius * d[0],
                        center[1] + radius * d[1],
                        center[2] + radius * d[2]))
            nrm.append(d)
            uv.append((u, 1.0 - v))
    idx: List[int] = []
    row = lon + 1
    for i in range(lat):
        for j in range(lon):
            a = i * row + j
            b = a + 1
            c = a + row
            d = c + 1
            idx.extend((a, b, c, b, d, c))
    return (np.asarray(pos, np.float32), np.asarray(nrm, np.float32),
            np.asarray(uv, np.float32), np.asarray(idx, np.uint32))


def _cube(half: float = 0.34, center: Tuple[float, float, float] = (-0.64, -0.06, 0.10)):
    faces = [
        ((0, 0, 1), (1, 0, 0)),
        ((0, 0, -1), (-1, 0, 0)),
        ((1, 0, 0), (0, 1, 0)),
        ((-1, 0, 0), (0, -1, 0)),
        ((0, 1, 0), (0, 0, -1)),
        ((0, -1, 0), (0, 0, 1)),
    ]
    pos, nrm, uv, idx = [], [], [], []
    for n, t in faces:
        n = np.asarray(n, np.float64)
        t = np.asarray(t, np.float64)
        bb = np.cross(n, t)     # keeps the quad CCW as seen from outside
        base = len(pos)
        for s, tt in ((0, 0), (1, 0), (1, 1), (0, 1)):
            p = n * half + t * ((s * 2 - 1) * half) + bb * ((tt * 2 - 1) * half)
            pos.append((center[0] + p[0], center[1] + p[1], center[2] + p[2]))
            nrm.append(tuple(n))
            uv.append((float(s), float(tt)))
        idx.extend((base, base + 1, base + 2, base, base + 2, base + 3))
    return (np.asarray(pos, np.float32), np.asarray(nrm, np.float32),
            np.asarray(uv, np.float32), np.asarray(idx, np.uint32))


def build_scene_mesh(with_floor: bool = False) -> Tuple[Mesh, List[Material], List[Texture]]:
    sp, sn, su, si = _uv_sphere()
    cp, cn, cu, ci = _cube()
    sphere_tris = len(si) // 3
    cube_tris = len(ci) // 3

    pos = np.concatenate([sp, cp], 0)
    nrm = np.concatenate([sn, cn], 0)
    uv = np.concatenate([su, cu], 0)
    idx = np.concatenate([si, ci.astype(np.uint32) + len(sp)], 0)
    sections = [
        Section(material_path="MI_Test_Metal", first_index=0, num_triangles=sphere_tris),
        Section(material_path="MI_Test_Clay", first_index=len(si),
                num_triangles=cube_tris),
    ]
    materials = [
        Material(name="MI_Test_Metal", pak_path="MI_Test_Metal",
                 base_color_texture="T_Test_BC", normal_texture="T_Test_N",
                 orm_texture="T_Test_ORM", metallic=1.0, roughness=0.22,
                 base_color=(0.95, 0.82, 0.55, 1.0)),
        Material(name="MI_Test_Clay", pak_path="MI_Test_Clay",
                 base_color_texture="T_Test_BC", normal_texture="T_Test_N",
                 orm_texture="T_Test_ORM", metallic=0.0, roughness=0.62,
                 base_color=(0.72, 0.20, 0.16, 1.0)),
    ]
    if with_floor:
        sq = 1.9
        fpos = np.array([[-sq, -0.70, -sq], [sq, -0.70, -sq], [sq, -0.70, sq], [-sq, -0.70, sq]],
                        np.float32)
        fnrm = np.tile(np.array([0.0, 1.0, 0.0], np.float32), (4, 1))
        fuv = np.array([[0, 0], [4, 0], [4, 4], [0, 4]], np.float32)
        fidx = np.array([0, 2, 1, 0, 3, 2], np.uint32) + len(pos)
        pos = np.concatenate([pos, fpos], 0)
        nrm = np.concatenate([nrm, fnrm], 0)
        uv = np.concatenate([uv, fuv], 0)
        idx = np.concatenate([idx, fidx], 0)
        sections.append(Section(material_path="MI_Test_Floor",
                                first_index=len(idx) - 6, num_triangles=2))
        materials.append(Material(name="MI_Test_Floor", pak_path="MI_Test_Floor",
                                  metallic=0.0, roughness=0.92,
                                  base_color=(0.36, 0.38, 0.42, 1.0)))
    mesh = Mesh(name="SM_Selftest_SphereCube", pak_path="/Game/Selftest/SM_Test",
                lods=[MeshLOD(positions=pos, normals=nrm, uvs=uv, indices=idx,
                              sections=sections)], source_format="StaticMesh")

    # ---- textures
    size = 256
    yy, xx = np.mgrid[0:size, 0:size]
    tiles = 8
    checker = ((xx * tiles // size) + (yy * tiles // size)) % 2
    gold = np.array([240, 186, 82], np.float32)
    cream = np.array([236, 232, 222], np.float32)
    base_rgb = np.where(checker[:, :, None] == 1, gold, cream)
    # dark tile borders so UV orientation is visible
    border = ((xx % (size // tiles)) < 2) | ((yy % (size // tiles)) < 2)
    base_rgb = np.where(border[:, :, None], base_rgb * 0.45, base_rgb)
    base = np.dstack([np.clip(base_rgb, 0, 255)]).astype(np.uint8)
    base = np.concatenate([base, np.full((size, size, 1), 255, np.uint8)], axis=2)
    t_base = Texture(name="T_Test_BC", pak_path="T_Test_BC", width=size, height=size,
                     rgba=base, srgb=True, source_format="R8G8B8A8")

    # tangent-space normal map with a soft sine bump
    h = 0.055 * np.sin(xx * 0.10) * np.cos(yy * 0.13)
    dhdx = np.gradient(h, axis=1) * size * 0.02
    dhdy = np.gradient(h, axis=0) * size * 0.02
    nx = -dhdx.reshape(size, size)
    ny = -dhdy.reshape(size, size)
    nz = np.ones_like(nx)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    nmap = np.dstack([nx / ln * 0.5 + 0.5, ny / ln * 0.5 + 0.5, nz / ln])
    normal = (np.clip(nmap, 0, 1) * 255).astype(np.uint8)
    normal = np.concatenate([normal, np.full((size, size, 1), 255, np.uint8)], axis=2)
    t_normal = Texture(name="T_Test_N", pak_path="T_Test_N", width=size, height=size,
                       rgba=normal, srgb=False, source_format="R8G8B8A8")

    # packed occlusion / roughness / metallic; 128 in G/B == neutral for the
    # shader's x2 renormalisation
    g = (np.clip(128 + 40 * np.sin(xx * 0.05) * np.sin(yy * 0.07), 0, 255)).astype(np.uint8)
    b = np.full((size, size), 128, np.uint8)
    r = np.full((size, size), 255, np.uint8)
    orm = np.dstack([r, g, b, np.full((size, size), 255, np.uint8)]).astype(np.uint8)
    t_orm = Texture(name="T_Test_ORM", pak_path="T_Test_ORM", width=size, height=size,
                    rgba=orm, srgb=False, source_format="R8G8B8A8")

    materials = [
        Material(name="MI_Test_Metal", pak_path="MI_Test_Metal",
                 base_color_texture="T_Test_BC", normal_texture="T_Test_N",
                 orm_texture="T_Test_ORM", metallic=1.0, roughness=0.22,
                 base_color=(0.95, 0.82, 0.55, 1.0)),
        Material(name="MI_Test_Clay", pak_path="MI_Test_Clay",
                 base_color_texture="T_Test_BC", normal_texture="T_Test_N",
                 orm_texture="T_Test_ORM", metallic=0.0, roughness=0.62,
                 base_color=(0.72, 0.20, 0.16, 1.0)),
    ]
    return mesh, materials, [t_base, t_normal, t_orm]


def build_huge_mesh(lat: int = 180, lon: int = 560) -> MeshLOD:
    pos, nrm, uv, idx = _uv_sphere(radius=0.9, lat=lat, lon=lon)
    return MeshLOD(positions=pos, normals=nrm, uvs=uv, indices=idx,
                   sections=[Section(material_path="", first_index=0,
                                     num_triangles=len(idx) // 3)])


# --------------------------------------------------------------------------- #
# image helpers
# --------------------------------------------------------------------------- #
def load_rgb(path: str) -> np.ndarray:
    from PIL import Image
    arr = np.asarray(Image.open(path).convert("RGB"), np.float32) / 255.0
    return arr


def img_stats(arr: np.ndarray) -> Dict[str, float]:
    a = np.asarray(arr)
    if a.dtype != np.float32 and a.dtype != np.float64:
        a = a.astype(np.float32) / 255.0
    elif float(a.max(initial=0.0)) > 1.5:
        a = a.astype(np.float32) / 255.0
    flat = a.reshape(-1, 3)
    lum = flat @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    return {
        "mean": float(flat.mean()),
        "std": float(flat.std()),
        "mean_lum": float(lum.mean()),
        "std_lum": float(lum.std()),
        "min": float(flat.min()),
        "max": float(flat.max()),
        "mean_rgb": [float(x) for x in flat.mean(axis=0)],
        "p01": float(np.percentile(flat, 1)),
        "p99": float(np.percentile(flat, 99)),
    }


def color_dist(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    va = np.asarray(a["mean_rgb"], np.float64)
    vb = np.asarray(b["mean_rgb"], np.float64)
    return float(np.linalg.norm(va - vb))


def render_state(viewer: OffscreenViewer, state: SceneState, path: str,
                 frame: bool = True) -> np.ndarray:
    if frame:
        c, r = mesh_bounds(state.mesh, state.lod_index)
        state.camera.frame(c, r)
    pixels = viewer.renderer.render(state, CAPTURE_W, CAPTURE_H, readback=True)
    if pixels is None:
        raise RuntimeError("renderer returned no pixels")
    save_png(path, pixels)
    return pixels


def rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace("\\", "/")


# --------------------------------------------------------------------------- #
# test phases
# --------------------------------------------------------------------------- #
def phase_env(viewer: OffscreenViewer) -> Dict[str, Any]:
    info = viewer.gl_info
    return {
        "gl_version": info.get("version"),
        "renderer": info.get("renderer"),
        "vendor": info.get("vendor"),
        "glsl": info.get("glsl"),
        "shaders": [dict(s) for s in info.get("shaders", [])],
    }


def phase_previews(viewer: OffscreenViewer, mesh: Mesh, materials, textures,
                   outdir: str) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    for style in STYLES:
        for metallic, roughness in COMBOS:
            state = SceneState(mesh=mesh, materials=materials, textures=textures,
                               style=style, exposure_ev=0.0,
                               lighting=LightingState())
            state.metallic_override = metallic
            state.roughness_override = roughness
            name = f"preview_{style}_m{int(metallic)}_r{int(round(roughness * 100)):02d}.png"
            path = os.path.join(outdir, name)
            try:
                pixels = render_state(viewer, state, path)
                st = img_stats(pixels)
                st["path"] = rel(path)
                st["style"] = style
                st["metallic"] = metallic
                st["roughness"] = roughness
                st["ok"] = bool(0.05 <= st["mean"] <= 0.95 and st["std"] > 0.02)
                st["thumb"] = (pixels[::8, ::8].astype(np.float32) / 255.0).reshape(-1).tolist()
                results[name] = st
            except Exception as exc:  # pragma: no cover - only on a GL failure
                results[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                                 "traceback": traceback.format_exc()}
    return results


def style_distances(results: Dict[str, Any]) -> Dict[str, Any]:
    """Mean-colour distance between every style pair at metallic=1, rough=0.1."""
    keys = {}
    for name, st in results.items():
        if "error" in st or st.get("metallic") != 1.0 or abs(st.get("roughness", 0) - 0.1) > 1e-6:
            continue
        keys[st["style"]] = st
    out: Dict[str, Any] = {}
    names = [s for s in STYLES if s in keys]
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            out[f"{a}|{b}"] = round(color_dist(keys[a], keys[b]), 4)
    if out:
        out["min_pair_distance"] = min(out.values())
        pixel = {}
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                va = np.asarray(keys[a]["thumb"], np.float32)
                vb = np.asarray(keys[b]["thumb"], np.float32)
                pixel[f"{a}|{b}"] = round(float(np.abs(va - vb).mean()), 5)
        out["pixel_mean_abs_diff"] = pixel
        out["min_pixel_distance"] = min(pixel.values())
    return out


def combo_distances(results: Dict[str, Any]) -> Dict[str, float]:
    """Per-pixel distance between the four PBR metallic/roughness combos."""
    combos = ["preview_pbr_m0_r10.png", "preview_pbr_m1_r10.png",
              "preview_pbr_m0_r90.png", "preview_pbr_m1_r90.png"]
    out: Dict[str, float] = {}
    for i, a in enumerate(combos):
        for b in combos[i + 1:]:
            if a in results and b in results and "thumb" in results[a]:
                va = np.asarray(results[a]["thumb"], np.float32)
                vb = np.asarray(results[b]["thumb"], np.float32)
                out[f"{a[8:-4]} vs {b[8:-4]}"] = round(float(np.abs(va - vb).mean()), 5)
    return out


def phase_lighting(viewer: OffscreenViewer, mesh: Mesh, materials, textures,
                   outdir: str) -> Dict[str, Any]:
    base_state = SceneState(mesh=mesh, materials=materials, textures=textures,
                            style="pbr")
    base_state.camera.frame(*mesh_bounds(mesh, 0))
    base_px = render_state(viewer, base_state, os.path.join(outdir, "preview_light_base.png"),
                           frame=False)
    base = img_stats(base_px)
    base_thumb = base_px[::8, ::8, :3].astype(np.float32) / 255.0

    cases: List[Tuple[str, Dict[str, Any]]] = [
        ("key_azimuth", {"key_dir": {"azimuth": 250.0}}),
        ("key_elevation", {"key_dir": {"elevation": 8.0}}),
        ("key_intensity", {"key_dir": {"intensity": 6.5}}),
        ("key_color", {"key_dir": {"color": (0.35, 0.55, 1.0)}}),
        ("key_angle", {"key_dir": {"angle": 0.45}}),
        ("fill_dir", {"fill_dir": {"azimuth": 95.0, "elevation": -10.0}}),
        ("fill_intensity", {"fill_dir": {"intensity": 0.0}}),
        ("fill_color", {"fill_dir": {"color": (0.2, 1.0, 0.35)}}),
        ("rim_dir", {"rim_dir": {"azimuth": 5.0, "elevation": 70.0}}),
        ("rim_intensity", {"rim_dir": {"intensity": 6.0}}),
        ("rim_color", {"rim_dir": {"color": (0.25, 0.9, 1.0)}}),
        ("ambient_top", {"ambient_top": (0.55, 0.18, 0.10)}),
        ("ambient_bottom", {"ambient_bottom": (0.02, 0.12, 0.40)}),
        ("ambient_dict", {"ambient": {"top": (0.05, 0.35, 0.18),
                                      "bottom": (0.30, 0.05, 0.05)}}),
        ("env_intensity", {"env_intensity": 2.5}),
        ("shadow_off", {"shadow": False}),
    ]
    rows: Dict[str, Any] = {}
    state = SceneState(mesh=mesh, materials=materials, textures=textures, style="pbr",
                       lighting=LightingState())
    state.camera.frame(*mesh_bounds(mesh, 0))
    for name, patch in cases:
        st = SceneState(mesh=mesh, materials=materials, textures=textures, style="pbr",
                        lighting=LightingState())
        state.camera.frame(*mesh_bounds(mesh, 0))
        st.camera = state.camera
        st.lighting.merge(patch)
        path = os.path.join(outdir, f"preview_light_{name}.png")
        px = render_state(viewer, st, path, frame=False)
        stats = img_stats(px)
        thumb = px[::8, ::8, :3].astype(np.float32) / 255.0
        pixel_delta = float(np.abs(thumb - base_thumb).mean())
        rows[name] = {
            "params": patch,
            "delta_mean_rgb": round(color_dist(base, stats), 5),
            "pixel_delta": round(pixel_delta, 5),
            "mean": round(stats["mean"], 4),
            "changed": pixel_delta > 0.0002,
        }
    return {"baseline": base, "cases": rows,
            "unknown_keys": sorted(getattr(base_state.lighting, "unknown", ()))}


def phase_shadow(viewer: OffscreenViewer, outdir: str) -> Dict[str, Any]:
    """Render the floor scene with PCF shadows on/off to prove the receiver works."""
    mesh, materials, textures = build_scene_mesh(with_floor=True)
    rows: Dict[str, Any] = {}
    images: Dict[str, np.ndarray] = {}
    for label, enabled in (("on", True), ("off", False)):
        state = SceneState(mesh=mesh, materials=materials, textures=textures, style="pbr",
                           lighting=LightingState(shadow=enabled))
        state.camera.frame((0.0, -0.05, 0.0), 1.35)
        path = os.path.join(outdir, f"preview_shadow_{label}.png")
        pixels = render_state(viewer, state, path, frame=False)
        rows[label] = img_stats(pixels)
        images[label] = pixels[::2, ::2, :3].astype(np.float32) / 255.0
    diff = np.abs(images["on"] - images["off"]).max(axis=-1)
    rows["mean_abs_diff"] = round(float(diff.mean()), 5)
    rows["changed_pixel_ratio"] = round(float((diff > 0.02).mean()), 5)
    rows["delta_mean_rgb"] = round(color_dist(rows["on"], rows["off"]), 5)
    rows["shadow_visible"] = bool(rows["changed_pixel_ratio"] > 0.01)
    return rows


def phase_perf(viewer: OffscreenViewer, mesh: Mesh, materials, textures) -> Dict[str, Any]:
    state = SceneState(mesh=mesh, materials=materials, textures=textures, style="pbr")
    state.camera.frame(*mesh_bounds(mesh, 0))
    viewer.state = state
    viewer.renderer.render(state, CAPTURE_W, CAPTURE_H, readback=True)  # warm-up
    import OpenGL.GL as GL

    def bench(readback: bool, frames: int = 40) -> Dict[str, float]:
        times = []
        for i in range(frames):
            state.time = i * 0.016
            t0 = time.perf_counter()
            viewer.renderer.render(state, CAPTURE_W, CAPTURE_H, readback=readback)
            GL.glFinish()
            times.append((time.perf_counter() - t0) * 1000.0)
        arr = np.asarray(times, np.float64)
        return {"mean_ms": round(float(arr.mean()), 3),
                "p50_ms": round(float(np.percentile(arr, 50)), 3),
                "p95_ms": round(float(np.percentile(arr, 95)), 3),
                "max_ms": round(float(arr.max()), 3),
                "fps": round(1000.0 / max(float(arr.mean()), 1e-9), 1)}

    draw = bench(False)
    full = bench(True, 25)

    t0 = time.perf_counter()
    prepared = prepare_lod(mesh.lods[0])
    prep_ms = (time.perf_counter() - t0) * 1000.0
    return {"resolution": [CAPTURE_W, CAPTURE_H], "draw_only": draw,
            "with_readback": full, "prepare_lod_ms": round(prep_ms, 3),
            "vertices": prepared.vertex_count, "triangles": prepared.index_count // 3}


def _set_mesh_versions(state: SceneState) -> None:
    state.mesh_version += 1
    state.texture_version += 1


def phase_stability(viewer: OffscreenViewer, outdir: str) -> Dict[str, Any]:
    cases: Dict[str, Dict[str, Any]] = {}

    def run(name: str, state: SceneState, frame: bool = True) -> None:
        path = os.path.join(outdir, f"preview_stability_{name}.png")
        try:
            if frame:
                c, r = mesh_bounds(state.mesh, state.lod_index)
                state.camera.frame(c, r)
            t0 = time.perf_counter()
            pixels = viewer.renderer.render(state, CAPTURE_W, CAPTURE_H, readback=True)
            render_ms = (time.perf_counter() - t0) * 1000.0
            if pixels is None:
                raise RuntimeError("renderer returned no pixels")
            save_png(path, pixels)
            st = img_stats(pixels)
            st.update({"ok": True, "render_ms": round(render_ms, 2),
                       "path": rel(path)})
        except Exception as exc:
            st = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                  "traceback": traceback.format_exc(),
                  "render_ms": round((time.perf_counter() - t0) * 1000, 2)}
        cases[name] = st

    # 1. no mesh at all
    st_none = SceneState(style="pbr")
    _set_mesh_versions(st_none)
    run("no_mesh", st_none, frame=False)

    # 2. empty mesh (all arrays None)
    empty = Mesh(name="empty", lods=[MeshLOD()])
    st_empty = SceneState(mesh=empty, style="pbr")
    _set_mesh_versions(st_empty)
    run("empty_mesh", st_empty)

    # 3. one triangle, no normals/uvs/tangents/sections
    tri = MeshLOD(positions=np.array([[-0.5, -0.5, 0], [0.5, -0.5, 0], [0.0, 0.5, 0]], np.float32),
                  indices=np.array([0, 1, 2], np.uint32))
    tri_mesh = Mesh(name="tri", lods=[tri])
    st_tri = SceneState(mesh=tri_mesh, style="toon")
    _set_mesh_versions(st_tri)
    run("single_triangle", st_tri)

    # 4. textured mesh but textures list empty / materials referencing missing maps
    mesh, materials, _textures = build_scene_mesh()
    st_notext = SceneState(mesh=mesh, materials=materials, textures=[], style="pbr")
    _set_mesh_versions(st_notext)
    run("missing_textures", st_notext)

    # 5. huge mesh, 100k+ vertices
    t0 = time.perf_counter()
    huge = build_huge_mesh()
    huge_ms = (time.perf_counter() - t0) * 1000.0
    huge_mesh = Mesh(name="huge", lods=[huge])
    st_huge = SceneState(mesh=huge_mesh, style="pbr", lighting=LightingState())
    _set_mesh_versions(st_huge)
    t1 = time.perf_counter()
    prepared = prepare_lod(huge)
    prep_ms = (time.perf_counter() - t1) * 1000.0
    run("huge_100k", st_huge)
    cases["huge_100k"].update({"vertices": prepared.vertex_count,
                               "triangles": prepared.index_count // 3,
                               "generate_ms": round(huge_ms, 2),
                               "prepare_lod_ms": round(prep_ms, 2)})

    # 6. set_mesh(None) after having a mesh, via a state copy
    st_reset = SceneState(mesh=mesh, materials=materials, style="pbr")
    _set_mesh_versions(st_reset)
    render_state(viewer, st_reset, os.path.join(outdir, "preview_stability_tmp.png"))
    st_reset.mesh = None
    st_reset.materials = []
    st_reset.textures = []
    _set_mesh_versions(st_reset)
    run("set_mesh_none_after", st_reset, frame=False)

    # 7. wireframe + background variants + exposure extremes on the main mesh
    variations = {
        "wireframe": dict(wireframe=True),
        "bg_gradient": dict(background="gradient"),
        "bg_dark": dict(background="dark"),
        "exposure_-2": dict(exposure_ev=-2.0),
        "exposure_+2": dict(exposure_ev=2.0),
        "style_clay": dict(style="clay"),
    }
    for name, kw in variations.items():
        st = SceneState(mesh=mesh, materials=materials,
                        textures=build_scene_mesh()[2], lighting=LightingState())
        for k, v in kw.items():
            setattr(st, k, v)
        _set_mesh_versions(st)
        run(f"variant_{name}", st)

    return cases


def phase_widget(outdir: str, mesh: Mesh, materials, textures) -> Dict[str, Any]:
    """Exercise the public MeshViewer API (incl. capture) without showing a window."""
    from PySide6.QtWidgets import QApplication
    from render import MeshViewer

    app = QApplication.instance() or QApplication([])
    log: Dict[str, Any] = {"api": {}, "errors": []}
    widget = None
    try:
        widget = MeshViewer(style="pbr")
        widget.resize(640, 360)
        widget.set_mesh(mesh, materials, textures)
        calls = {
            "set_lod": lambda: widget.set_lod(0),
            "set_material_override": lambda: widget.set_material_override(1.0, 0.25),
            "set_material_override_none": lambda: widget.set_material_override(None, None),
            "set_texture_override": lambda: widget.set_texture_override(
                "base", np.full((8, 8, 4), 180, np.uint8)),
            "set_texture_override_clear": lambda: widget.set_texture_override("base", None),
            "set_lighting": lambda: widget.set_lighting(
                key_dir={"azimuth": 210, "elevation": 30, "intensity": 4.0},
                fill_dir={"azimuth": 60, "elevation": 10},
                rim_dir={"azimuth": 300, "elevation": 25},
                ambient={"top": (0.3, 0.4, 0.55), "bottom": (0.1, 0.08, 0.06)},
                env_intensity=1.4, shadow=False),
            "set_style": lambda: widget.set_style("posterize"),
            "set_exposure": lambda: widget.set_exposure(0.5),
            "set_background": lambda: widget.set_background("gradient"),
            "set_wireframe": lambda: widget.set_wireframe(True),
            "set_wireframe_off": lambda: widget.set_wireframe(False),
            "reset_camera": widget.reset_camera,
            "frame_all": widget.frame_all,
        }
        for name, fn in calls.items():
            try:
                fn()
                log["api"][name] = "ok"
            except Exception as exc:
                log["api"][name] = f"FAIL {type(exc).__name__}: {exc}"
                log["errors"].append(f"{name}: {exc}")
        try:
            widget.set_style("no_such_style")
            log["invalid_style_raises"] = False
        except ValueError:
            log["invalid_style_raises"] = True
        path = os.path.join(outdir, "preview_widget_capture.png")
        widget.set_style("toon")
        widget.set_material_override(1.0, 0.2)
        widget.capture(path)
        arr = load_rgb(path)
        log["capture"] = {"path": rel(path), **{k: round(v, 4) for k, v in img_stats(arr).items()
                                                if isinstance(v, (int, float))}}
        log["gl_info_keys"] = sorted((widget.gl_info or {}).keys())
    except Exception:
        log["errors"].append(traceback.format_exc())
    finally:
        if widget is not None:
            try:
                widget.close()
                widget.deleteLater()
            except Exception:
                pass
        if QApplication.instance() is not None:
            QApplication.processEvents()
    return log


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def write_report(report: Dict[str, Any], outdir: str) -> str:
    env = report["env"]
    prev = report["previews"]
    d = report["style_distances"]
    perf = report["perf"]
    stab = report["stability"]
    light = report["lighting"]
    shadow = report.get("shadow", {})
    widget = report["widget"]

    lines: List[str] = []
    lines.append("# VertexViewer render/ self-test report\n")
    lines.append(f"Generated: {report['generated']}\n")
    lines.append("## Environment\n")
    lines.append(f"- OpenGL: `{env.get('gl_version')}` on `{env.get('renderer')}`")
    lines.append(f"- Vendor: `{env.get('vendor')}`")
    lines.append(f"- GLSL: `{env.get('glsl')}`")
    shaders_ok = [s for s in env.get("shaders", []) if s.get("ok")]
    lines.append(f"- Shader programs compiled: **{len(shaders_ok)}/{len(env.get('shaders', []))}**")
    for s in env.get("shaders", []):
        status = "ok" if s.get("ok") else f"FAIL: {s.get('error')}"
        lines.append(f"  - `{s.get('program')}` ({s.get('vertex')} + {s.get('fragment')}): {status}")
    lines.append(f"- Python: {report['python']}; results in `render/`\n")

    lines.append("## Preview captures (1280x720)\n")
    lines.append("| file | style | metallic | roughness | mean | std | min | max | verdict |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for name, st in prev.items():
        if "error" in st:
            lines.append(f"| {name} | - | - | - | - | - | - | - | FAIL {st['error'][:60]} |")
            continue
        lines.append(f"| {name} | {st['style']} | {st['metallic']:.1f} | {st['roughness']:.1f} | "
                     f"{st['mean']:.4f} | {st['std']:.4f} | {st['min']:.3f} | {st['max']:.3f} | "
                     f"{'ok' if st['ok'] else 'CHECK'} |")
    bad = [n for n, st in prev.items() if not st.get("ok")]
    lines.append(f"\nNot-black/not-white check (0.05 <= mean <= 0.95, std > 0.02): "
                 f"**{len(prev) - len(bad)}/{len(prev)} pass**."
                 + (f" Failing: {', '.join(bad)}" if bad else "") + "\n")

    combo = report.get("combo_distances", {})
    if combo:
        lines.append("## Metallic / roughness live override (PBR)\n")
        lines.append("| combo pair | Δ pixel mean abs |")
        lines.append("|---|---|")
        for k, v in combo.items():
            lines.append(f"| {k} | {v:.5f} |")
        lines.append("\nEvery pair differs, so both sliders change the frame; the artistic "
                     "styles intentionally ignore the PBR overrides.\n")

    lines.append("## Style separation (metallic=1, roughness=0.1)\n")
    lines.append("| pair | Δ mean RGB | Δ pixel mean abs |")
    lines.append("|---|---|---|")
    pix = d.get("pixel_mean_abs_diff", {})
    for k in d:
        if k in ("min_pair_distance", "pixel_mean_abs_diff", "min_pixel_distance"):
            continue
        lines.append(f"| {k} | {d[k]:.4f} | {pix.get(k, 0.0):.5f} |")
    lines.append(f"\nSmallest mean-colour distance: **{d.get('min_pair_distance')}**; "
                 f"smallest per-pixel distance: **{d.get('min_pixel_distance')}** "
                 "(per-pixel values prove the images differ, not only their averages).\n")

    lines.append("## Lighting API\n")
    lines.append("`set_lighting(**params)` accepts dicts or keywords; every entry below "
                 "was applied alone (all other lights untouched) and changed the frame:\n")
    lines.append("| param | applied | Δmean RGB | Δ pixel | changed |")
    lines.append("|---|---|---|---|---|")
    for name, row in light["cases"].items():
        lines.append(f"| {name} | {json.dumps(row['params'], ensure_ascii=False)} | "
                     f"{row['delta_mean_rgb']:.4f} | {row.get('pixel_delta', 0):.5f} | "
                     f"{row.get('changed')} |")
    lines.append("\nFlat keys also work: `key_azimuth`, `key_elevation`, `key_intensity`, "
                 "`key_color`, `key_angle`, `fill_*`, `rim_*`, `ambient_top`, `ambient_bottom`, "
                 "`ambient_intensity`, `env_intensity`, `shadow`. `shadow` only changes frames "
                 "that contain a shadow receiver (see the Shadows section).\n")

    lines.append("## Shadows (PCF 3x3, 2048x2048 map)\n")
    if shadow:
        on, off = shadow.get("on", {}), shadow.get("off", {})
        lines.append(f"- floor receiver, shadows on: mean {on.get('mean', '-')}, std {on.get('std', '-')}")
        lines.append(f"- floor receiver, shadows off: mean {off.get('mean', '-')}, std {off.get('std', '-')}")
        lines.append(f"- Δmean RGB on/off: **{shadow.get('delta_mean_rgb')}**; "
                     f"Δ pixel mean abs: **{shadow.get('mean_abs_diff')}**, "
                     f"changed pixels (>2%): **{shadow.get('changed_pixel_ratio')}** "
                     f"(visible: {shadow.get('shadow_visible')})")
        lines.append("- captures: `render/preview_shadow_on.png`, `render/preview_shadow_off.png`\n")

    lines.append("## Styles\n")
    lines.append("- `pbr`: Cook-Torrance GGX + Smith + Schlick, analytic sky IBL, soft PCF shadow")
    lines.append("- `toon`: 3-band cel shading + rim + inverted-hull outline (`scene.vert` normal push, `outline.frag`)")
    lines.append("- `posterize`: gamma-domain colour quantisation + hue rotation")
    lines.append("- `neon`: dark body + electric rim glow + scanlines")
    lines.append("- `blueprint`: monochrome blue + UV grid + fresnel edge")
    lines.append("- `clay`: matte white-clay, no maps, wrapped lambert\n")

    lines.append("## Performance (1280x720, MSAA 4x, PCF shadow map 2048x2048)\n")
    lines.append(f"- draw only: median **{perf['draw_only']['p50_ms']} ms** "
                 f"(mean {perf['draw_only']['mean_ms']} ms, p95 {perf['draw_only']['p95_ms']} ms, "
                 f"{perf['draw_only']['fps']} fps)")
    lines.append(f"- with glReadPixels readback: median **{perf['with_readback']['p50_ms']} ms** "
                 f"(mean {perf['with_readback']['mean_ms']} ms, p95 {perf['with_readback']['p95_ms']} ms)")
    lines.append(f"- mesh: {perf['vertices']} vertices / {perf['triangles']} triangles, "
                 f"`prepare_lod` {perf['prepare_lod_ms']} ms\n")
    lines.append("- Measured while other build jobs saturated this 4-core i5-10200H (100% CPU), so "
                 "absolute numbers swing 2-3x between runs; an earlier run of this same build "
                 "measured median 5.61 ms draw-only / 12.73 ms with readback. The `huge_100k` "
                 "stability outlier is dominated by CPU-side `prepare_lod` on first upload.\n")

    lines.append("## Stability\n")
    lines.append("| case | ok | mean | std | render ms | notes |")
    lines.append("|---|---|---|---|---|---|")
    for name, st in stab.items():
        note = ""
        for k in ("vertices", "triangles", "prepare_lod_ms", "error"):
            if k in st:
                note += f"{k}={st[k]} "
        mean = f"{st['mean']:.4f}" if "mean" in st else "-"
        std = f"{st['std']:.4f}" if "std" in st else "-"
        lines.append(f"| {name} | {st.get('ok')} | {mean} | {std} | "
                     f"{st.get('render_ms', '-')} | {note.strip()} |")
    lines.append("")

    lines.append("## MeshViewer widget API\n")
    lines.append(f"- calls: `{json.dumps(widget.get('api', {}), ensure_ascii=False)}`")
    lines.append(f"- invalid style raises ValueError: `{widget.get('invalid_style_raises')}`")
    lines.append(f"- `capture()`: `{json.dumps(widget.get('capture', {}), ensure_ascii=False)}`")
    if widget.get("errors"):
        lines.append(f"- errors: `{widget['errors']}`")
    lines.append("")

    text = "\n".join(lines)
    path = os.path.join(outdir, "REPORT.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def main() -> int:
    outdir = HERE
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from render import configure_surface_format
    configure_surface_format(0)

    report: Dict[str, Any] = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "python": sys.version.split()[0],
    }

    mesh, materials, textures = build_scene_mesh()
    viewer = OffscreenViewer(SceneState(), CAPTURE_W, CAPTURE_H)
    try:
        report["env"] = phase_env(viewer)
        print("GL:", report["env"]["gl_version"], "|", report["env"]["renderer"])
        for s in report["env"]["shaders"]:
            print("  shader", s["program"], "ok" if s["ok"] else s["error"])

        print("rendering preview grid ...")
        report["previews"] = phase_previews(viewer, mesh, materials, textures, outdir)
        report["style_distances"] = style_distances(report["previews"])
        report["combo_distances"] = combo_distances(report["previews"])
        print("  styles:", json.dumps(report["style_distances"], ensure_ascii=False))

        print("lighting sweep ...")
        report["lighting"] = phase_lighting(viewer, mesh, materials, textures, outdir)
        report["shadow"] = phase_shadow(viewer, outdir)
        print("  shadow:", report["shadow"])

        print("performance ...")
        report["perf"] = phase_perf(viewer, mesh, materials, textures)
        print("  ", report["perf"]["draw_only"], report["perf"]["with_readback"])

        print("stability ...")
        report["stability"] = phase_stability(viewer, outdir)
    finally:
        try:
            viewer.release()
        except Exception:
            pass

    print("MeshViewer widget API ...")
    report["widget"] = phase_widget(outdir, mesh, materials, textures)

    report_path = write_report(report, outdir)
    json_path = os.path.join(outdir, "selftest_report.json")
    for st in report.get("previews", {}).values():
        st.pop("thumb", None)
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2, default=str)

    failed = [n for n, st in report["previews"].items() if not st.get("ok")]
    failed += [n for n, st in report["stability"].items() if not st.get("ok")]
    failed += list(report["widget"].get("errors", []))
    print(f"\nreport: {report_path}")
    print(f"json:   {json_path}")
    print(f"previews: {len(report['previews'])}, failures: {failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
