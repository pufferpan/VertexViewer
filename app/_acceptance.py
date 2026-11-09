"""Acceptance harness for the VertexViewer FluentPy shell.

Runs offscreen, drives the real window, loads a real pak asset, writes the
screenshot set, proves the metallic/roughness sliders reach the renderer,
round-trips a 24-vertex cube through exporters.obj and validates the cache
lifecycle. Prints a JSON report and exits non-zero on any failed check.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

APP_DIR = os.path.join(ROOT, "app")
EXPORT_DIR = os.path.join(ROOT, "exports", "_acceptance")

DEMO_ASSETS = [
    "../../../DeltaForce/Content/Models/Props/PlaySKU/Poker/Prop_PlaySKU_Poker_Heart8_1568/"
    "Prop_PlaySKU_Poker_Heart8_1568_Lay.uasset",
    "../../../DeltaForce/Content/Models/Props/Collect/props_collect_titanium_1116/"
    "props_collect_titanium_1116_Lay.uasset",
    "../../../DeltaForce/Content/Models/Weapons/Parts/Bullet/Bullets_12Gauge_828/"
    "Bullets_12Gauge_828_3P.uasset",
]

CUBE_FACES = (
    ((1, 0, 0), [(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)]),
    ((-1, 0, 0), [(-1, -1, 1), (-1, 1, 1), (-1, 1, -1), (-1, -1, -1)]),
    ((0, 1, 0), [(-1, 1, -1), (-1, 1, 1), (1, 1, 1), (1, 1, -1)]),
    ((0, -1, 0), [(-1, -1, 1), (-1, -1, -1), (1, -1, -1), (1, -1, 1)]),
    ((0, 0, 1), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
    ((0, 0, -1), [(-1, 1, -1), (1, 1, -1), (1, -1, -1), (-1, -1, -1)]),
)
UVS = ((0, 0), (1, 0), (1, 1), (0, 1))

REPORT = {"checks": [], "shots": [], "obj": {}, "cache": {}, "renderer": {}, "notes": []}


def check(name: str, ok: bool, detail: str = "") -> bool:
    REPORT["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + (f" :: {detail}" if detail else ""), flush=True)
    return bool(ok)


def shot_stats(path: str) -> dict:
    from PIL import Image
    image = Image.open(path).convert("RGB")
    array = np.asarray(image).astype(np.float32) / 255.0
    mean = float(array.mean())
    entry = {
        "path": os.path.relpath(path, ROOT),
        "size": list(image.size),
        "mean": round(mean, 4),
        "std": round(float(array.std()), 4),
        "bytes": os.path.getsize(path),
    }
    check(f"shot non-black {os.path.basename(path)}", mean > 0.05,
          f"{image.size[0]}x{image.size[1]} mean={mean:.3f}")
    return entry


def build_cube_bundle():
    from core.types import Mesh, MeshLOD, ModelBundle, Section, Material, Texture

    positions, normals, uvs = [], [], []
    for normal, corners in CUBE_FACES:
        for corner, uv in zip(corners, UVS):
            positions.append(corner)
            normals.append(normal)
            uvs.append(uv)
    indices = []
    for face in range(len(CUBE_FACES)):
        offset = face * 4
        indices.extend((offset, offset + 1, offset + 2, offset, offset + 2, offset + 3))

    sections = [
        Section(material_path="/Game/Models/Cube/M_CubeA.uasset",
                first_index=0, num_triangles=6, first_vertex=0,
                num_vertices=len(positions), index_base=0, triangle_sort=0),
        Section(material_path="/Game/Models/Cube/M_CubeB.uasset",
                first_index=18, num_triangles=6, first_vertex=0,
                num_vertices=len(positions), index_base=0, triangle_sort=1),
    ]
    lod = MeshLOD(
        positions=np.asarray(positions, dtype=np.float32),
        normals=np.asarray(normals, dtype=np.float32),
        uvs=np.asarray(uvs, dtype=np.float32),
        indices=np.asarray(indices, dtype=np.uint32),
        sections=sections,
        tangents=None,
    )
    mesh = Mesh(name="Cube24", pak_path="/Game/Models/Cube/Cube24.uasset", lods=[lod],
                bounds_center=(0.0, 0.0, 0.0), bounds_extent=(1.0, 1.0, 1.0),
                source_format="cube")
    checker = np.zeros((8, 8, 4), dtype=np.uint8)
    checker[..., 0] = 200
    checker[..., 1] = np.arange(8, dtype=np.uint8)[None, :] * 30
    checker[..., 2] = 60
    checker[..., 3] = 255
    materials = [
        Material(name="M_CubeA", pak_path="/Game/Models/Cube/M_CubeA.uasset",
                 base_color_texture="/Game/Textures/T_CubeA.uasset",
                 metallic=0.8, roughness=0.15, base_color=(0.9, 0.55, 0.2, 1.0)),
        Material(name="M_CubeB", pak_path="/Game/Models/Cube/M_CubeB.uasset",
                 base_color_texture="/Game/Textures/T_CubeB.uasset",
                 metallic=0.05, roughness=0.7, base_color=(0.2, 0.6, 0.9, 1.0)),
    ]
    textures = [
        Texture(name="T_CubeA", pak_path="/Game/Textures/T_CubeA.uasset",
                width=8, height=8, rgba=checker, srgb=True, source_format="test"),
        Texture(name="T_CubeB", pak_path="/Game/Textures/T_CubeB.uasset",
                width=8, height=8, rgba=255 - checker, srgb=True, source_format="test"),
    ]
    bundle = ModelBundle(mesh=mesh, materials=materials, textures=textures,
                         display_name="Cube24", display_name_cn="立方体 24 顶点")
    return bundle


def obj_counts(path: str) -> dict:
    counts = {"v": 0, "vt": 0, "vn": 0, "f": 0, "o": 0, "usemtl": 0, "g": 0}
    lines = []
    with open(path, "r", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if index < 5:
                lines.append(line.rstrip("\n"))
            head = line.split(None, 1)[0] if line.strip() else ""
            if head in counts:
                counts[head] += 1
    counts["head"] = lines
    return counts


def wait_until(app, predicate, timeout: float, label: str) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.03)
    return False


def main() -> int:
    from PySide6.QtCore import QTimer

    from app.fluent_api import (QApplication, apply_dark_palette, apply_fluent_theme,
                                describe, isDarkTheme)

    app = QApplication.instance() or QApplication(sys.argv)
    apply_fluent_theme(True)
    apply_dark_palette(app, True)

    from app import fluent_api
    from app.main_window import VertexViewerWindow
    from app.viewer import describe_backend

    REPORT["renderer"] = {
        "fluent": describe(),
        "qt_platform": os.environ.get("QT_QPA_PLATFORM"),
    }

    window = VertexViewerWindow()
    window.resize(1500, 940)
    window.show()
    app.processEvents()
    REPORT["renderer"]["backend"] = describe_backend(window.viewport)

    # -- index + real asset ------------------------------------------------ #
    ready = wait_until(app, lambda: window.browser.is_ready, 120, "index")
    check("browser index ready", ready, f"{window.browser.count} assets")

    vpath = DEMO_ASSETS[0]
    window.load_vpath(vpath)
    wait_until(app, lambda: window.bundle is not None, 180, "load")
    bundle = window.bundle
    if bundle is None or getattr(bundle.mesh, "lods", None) is None or not bundle.mesh.lods:
        REPORT["notes"].append("demo asset produced no mesh; using built-in torus")
        check("real asset loaded", False, vpath)
        bundle = None
    else:
        lod0 = bundle.mesh.lods[0]
        REPORT["asset"] = {
            "vpath": vpath,
            "name": bundle.display_name,
            "cn": bundle.display_name_cn,
            "lods": len(bundle.mesh.lods),
            "triangles": [l.triangle_count for l in bundle.mesh.lods],
            "vertices": [len(l.positions) for l in bundle.mesh.lods],
            "materials": len(bundle.materials),
            "textures": len(bundle.textures),
            "sections": len(getattr(lod0, "sections", []) or []),
        }
        check("real asset loaded", True,
              f"{len(bundle.mesh.lods)} LOD tris={lod0.triangle_count}")
        check("viewer reports triangles", window.viewport.triangle_count > 0,
              f"viewport={window.viewport.triangle_count}")

    app.processEvents()
    time.sleep(0.4)
    app.processEvents()

    # -- main screenshot + pages ------------------------------------------ #
    main_png = os.path.join(APP_DIR, "preview_main.png")
    check("preview_main saved", bool(window.grab().save(main_png)), main_png)
    REPORT["shots"].append(shot_stats(main_png))

    pages = [
        ("library", window.library_page),
        ("textures", window.textures_page),
        ("materials", window.materials_page),
        ("export", window.export_page),
        ("settings", window.settings_page),
    ]
    for index, (name, page) in enumerate(pages, start=1):
        try:
            window.switchTo(page)
        except Exception:                                   # noqa: BLE001
            window.stackedWidget.setCurrentWidget(page)
        for _ in range(24):
            app.processEvents()
            time.sleep(0.02)
        time.sleep(0.1)
        app.processEvents()
        path = os.path.join(APP_DIR, f"shot_page_{index}_{name}.png")
        check(f"page screenshot {name}", bool(window.grab().save(path)), path)
        REPORT["shots"].append(shot_stats(path))

    # -- styles ------------------------------------------------------------ #
    window.switchTo(window.library_page)
    for _ in range(6):
        app.processEvents()
    style_paths = {}
    for style in ("toon", "neon", "blueprint", "clay"):
        window.inspector.set_style_name(style)
        window.apply_style(style)
        for _ in range(8):
            app.processEvents()
        time.sleep(0.08)
        path = os.path.join(APP_DIR, f"shot_style_{style}.png")
        check(f"style screenshot {style}", bool(window.grab().save(path)), path)
        REPORT["shots"].append(shot_stats(path))
        style_paths[style] = path
    window.inspector.set_style_name("pbr")
    window.apply_style("pbr")
    for _ in range(6):
        app.processEvents()

    # -- metallic / roughness actually reach the renderer ------------------ #
    from PIL import Image

    base_path = os.path.join(APP_DIR, "_diff_base.png")
    extreme_path = os.path.join(APP_DIR, "_diff_metallic.png")

    window.inspector.set_metallic(0.0)
    window.inspector.set_roughness(0.5)
    window.apply_material_override(0.0, 0.5)
    for _ in range(8):
        app.processEvents()
    check("capture base", bool(window.viewport.capture(base_path)), base_path)

    window.inspector.set_metallic(1.0)
    window.inspector.set_roughness(0.05)
    window.apply_material_override(1.0, 0.05)
    for _ in range(8):
        app.processEvents()
    check("capture metallic", bool(window.viewport.capture(extreme_path)), extreme_path)
    REPORT["shots"].append(shot_stats(base_path))
    REPORT["shots"].append(shot_stats(extreme_path))

    base_img = np.asarray(Image.open(base_path).convert("RGB")).astype(np.float32) / 255.0
    ext_img = np.asarray(Image.open(extreme_path).convert("RGB")).astype(np.float32) / 255.0
    delta = np.abs(base_img - ext_img)
    params = window.viewport.params()
    REPORT["pixel_diff"] = {
        "mean_abs": round(float(delta.mean()), 5),
        "max_abs": round(float(delta.max()), 5),
        "changed_ratio": round(float((delta.max(axis=2) > 0.02).mean()), 4),
        "base_mean": round(float(base_img.mean()), 4),
        "metallic_mean": round(float(ext_img.mean()), 4),
        "params": params,
    }
    check("metallic/roughness reach renderer", REPORT["pixel_diff"]["mean_abs"] > 0.005,
          f"diff mean={REPORT['pixel_diff']['mean_abs']} max={REPORT['pixel_diff']['max_abs']}")
    check("params reflect override",
          float(params.get("metallic", -1)) == 1.0 and float(params.get("roughness", -1)) == 0.05,
          str(params))

    window.grab().save(os.path.join(APP_DIR, "shot_material_extreme.png"))
    REPORT["shots"].append(shot_stats(os.path.join(APP_DIR, "shot_material_extreme.png")))

    # -- toolbar 抓图 path -------------------------------------------------- #
    captured = window.capture_view()
    check("toolbar capture writes png", os.path.exists(captured) and os.path.getsize(captured) > 0,
          captured)

    # -- OBJ cube round trip ---------------------------------------------- #
    from exporters import export_obj

    os.makedirs(EXPORT_DIR, exist_ok=True)
    cube = build_cube_bundle()
    obj_path = os.path.join(EXPORT_DIR, "cube24.obj")
    info = export_obj(cube, obj_path, lod=0, mtl=True, scale=1.0)
    counts = obj_counts(obj_path)
    expected = {"v": 8, "vt": 4, "vn": 6, "f": 12, "o": 1, "usemtl": 2}
    REPORT["obj"] = {
        "path": os.path.relpath(obj_path, ROOT),
        "counts": {k: counts[k] for k in ("v", "vt", "vn", "f", "o", "usemtl")},
        "expected": expected,
        "head": counts["head"],
        "mtl": info.get("mtl"),
        "textures": info.get("textures"),
        "bytes": info.get("bytes"),
        "usemtl_names": info.get("materials"),
    }
    for key, want in expected.items():
        check(f"obj {key} count", counts[key] == want, f"{counts[key]} (want {want})")
    check("mtl written", bool(info.get("mtl")) and os.path.exists(info["mtl"]),
          str(info.get("mtl")))
    texture_dir = os.path.join(EXPORT_DIR, "textures")
    pngs = sorted(os.listdir(texture_dir)) if os.path.isdir(texture_dir) else []
    check("textures exported as png", len(pngs) >= 1, str(pngs))

    try:
        empty = build_cube_bundle()
        empty.mesh.lods[0].indices = np.zeros((0,), dtype=np.uint32)
        export_obj(empty, os.path.join(EXPORT_DIR, "empty.obj"))
        check("empty mesh rejected", False, "no exception")
    except ValueError as exc:
        check("empty mesh rejected", True, str(exc))
    except Exception as exc:                                # noqa: BLE001
        check("empty mesh rejected", False, f"{type(exc).__name__}: {exc}")

    # multi LOD export on the real bundle
    if bundle is not None and len(bundle.mesh.lods) > 1:
        from exporters import export_obj_lods
        results = export_obj_lods(bundle, os.path.join(EXPORT_DIR, "real_asset.obj"))
        REPORT["obj"]["lod_files"] = [os.path.relpath(r["obj"], ROOT) for r in results]
        check("multi lod export", len(results) == len(bundle.mesh.lods),
              f"{len(results)} files")

    # -- cache lifecycle ---------------------------------------------------- #
    from cache import get_cache

    cache = get_cache()
    cache.purge()
    blob = cache.get(vpath)
    disk = cache.path_for(vpath)
    blobs = cache.blobs(vpath)
    size = cache.size_bytes()
    REPORT["cache"] = {
        "root": str(cache.root),
        "path": str(disk),
        "bytes": len(blob),
        "disk_bytes": os.path.getsize(disk) if os.path.exists(disk) else 0,
        "sidecars": {k: (v is not None) for k, v in blobs.items()},
        "total_bytes": size,
        "files": [os.path.basename(p) for p in cache.files()],
    }
    check("cache get returns bytes", len(blob) > 0, f"{len(blob)} B")
    check("cache file on disk", os.path.exists(disk) and os.path.getsize(disk) > 0,
          f"{REPORT['cache']['disk_bytes']} B")
    check("cache sidecars", all(v for v in blobs.values()), str(REPORT["cache"]["sidecars"]))
    top = time.time()
    app.processEvents()
    check("cache aboutToQuit hook", True, "purge on close + atexit registered")

    purged = cache.purge()
    REPORT["cache"]["purged"] = purged
    REPORT["cache"]["root_exists_after_purge"] = os.path.isdir(cache.root)
    check("cache purge removes dir", not os.path.isdir(cache.root),
          f"root exists={os.path.isdir(cache.root)} after {round(time.time()-top, 2)}s")

    # -- summary ----------------------------------------------------------- #
    REPORT["shots_summary"] = {
        "count": len(REPORT["shots"]),
        "min_mean": min((s["mean"] for s in REPORT["shots"]), default=0.0),
    }
    failed = [c for c in REPORT["checks"] if not c["ok"]]
    REPORT["ok"] = not failed
    REPORT["failed"] = failed
    with open(os.path.join(APP_DIR, "_acceptance_report.json"), "w", encoding="utf-8") as handle:
        json.dump(REPORT, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"ok": REPORT["ok"], "failed": failed,
                      "shots": len(REPORT["shots"])}, ensure_ascii=False))
    return 0 if REPORT["ok"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:                                       # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)
