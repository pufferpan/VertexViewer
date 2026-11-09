"""竖版整枪渲染：给浅蓝网格宣传图用（560×1140，一屏一支枪）。

用法： python tools/poster_portrait.py
产物： work/promo_grid/tiles/tile_gun_<名>.png、tile_style_<风格>.png
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from core import gunsmith as gs  # noqa: E402
from core.types import Mesh  # noqa: E402
from core import loader  # noqa: E402
import render  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "work", "promo_grid", "tiles")
TW, TH = 560, 1140

BASES = [
    ("M4A1", "Rec_AR_M4A1-Std_001_3P.uasset", "pbr"),
    ("HK416", "Rec_AR_HK416_021_3P.uasset", "pbr"),
    ("AK12", "Rec_AR_AK12_030_3P.uasset", "pbr"),
    ("SCAR-H", "Rec_AR_ScarH_045_3P.uasset", "pbr"),
    ("MP5A4", "Rec_SMG_MP5A4-Std_004_3P.uasset", "pbr"),
    ("SG553", "Rec_AR_SG553_024_3P.uasset", "pbr"),
    ("AK74", "Rec_AR_AK74-Std_002_3P.uasset", "pbr"),
    ("UZI", "Rec_SMG_UZI_3P.uasset", "pbr"),
]
STYLES = ["neon", "blueprint", "clay", "toon", "posterize"]

os.makedirs(OUT, exist_ok=True)
app = QApplication([])
idx = loader.index()


def find(suffix: str) -> str:
    hits = [k for k in idx if k.endswith(suffix)]
    if not hits:
        hits = [k for k in idx if k.lower().endswith(suffix.lower()) and "/rec/" in k.lower()]
    return hits[0] if hits else ""


viewer = render.MeshViewer()
viewer.resize(TW, TH)
viewer.set_background("dark")
viewer.set_style("pbr")

done = 0
for label, suffix, _style in BASES:
    base = find(suffix)
    if not base:
        print("[portrait] miss", suffix)
        continue
    bundle = loader.load_model(base, lod=0, want_textures=True)
    if not getattr(bundle, "mesh", None):
        continue
    specs = gs.official_loadout(base)
    pairs = []
    for spec in specs:
        b = loader.load_model(spec.vpath, lod=0, want_textures=True)
        if getattr(b, "mesh", None):
            pairs.append((spec, b))
    combo = gs.assemble(bundle, pairs, base_vpath=base)
    # 竖卡要「斜着放一支枪」才好看：把整支枪绕深度轴转 32°，再从正侧面看
    tilt = gs._trs(rot_ypr=(32.0, 0.0, 0.0))
    lods = [gs._apply_matrix(lod, tilt) for lod in combo.mesh.lods] if combo.mesh else []
    viewer.set_mesh(Mesh(name="poster", lods=lods), combo.materials, combo.textures)
    viewer.frame_all()
    cam = viewer._state.camera                                    # noqa: SLF001
    cam.yaw, cam.pitch = -6.0, 9.0
    viewer.frame_all()
    cam.distance *= 0.82
    path = os.path.join(OUT, f"tile_gun_{label}.png")
    viewer.capture(path, width=TW, height=TH)
    print("[portrait]", path, len(pairs), "parts")
    done += 1

    if label == "M4A1":
        for style in STYLES:
            try:
                viewer.set_style(style)
            except Exception as exc:                             # noqa: BLE001
                print("[portrait] style skip", style, exc)
                continue
            p2 = os.path.join(OUT, f"tile_style_{style}.png")
            viewer.capture(p2, width=TW, height=TH)
            print("[portrait]", p2)
            done += 1
        viewer.set_style("pbr")

# 再来几张浅底（studio）的，网格里明暗混着才不闷
viewer.set_background("studio")
for label, suffix, _style in BASES[:4]:
    base = find(suffix)
    if not base:
        continue
    bundle = loader.load_model(base, lod=0, want_textures=True)
    specs = gs.official_loadout(base)
    pairs = [(s2, b2) for s2, b2 in
             ((sp, loader.load_model(sp.vpath, lod=0, want_textures=True)) for sp in specs)
             if getattr(b2, "mesh", None)]
    combo = gs.assemble(bundle, pairs, base_vpath=base)
    tilt = gs._trs(rot_ypr=(32.0, 0.0, 0.0))
    lods = [gs._apply_matrix(lod, tilt) for lod in combo.mesh.lods] if combo.mesh else []
    viewer.set_mesh(Mesh(name="poster", lods=lods), combo.materials, combo.textures)
    cam = viewer._state.camera                                    # noqa: SLF001
    cam.yaw, cam.pitch = -6.0, 9.0
    viewer.frame_all()
    cam.distance *= 0.82
    path = os.path.join(OUT, f"tile_gun_{label}_light.png")
    viewer.capture(path, width=TW, height=TH)
    print("[portrait]", path)
    done += 1

print("[portrait] files", done)
