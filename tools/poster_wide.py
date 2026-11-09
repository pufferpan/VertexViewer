"""两张 16:9 的整枪渲染（PBR），给页面网格当“主视觉”。

用法： python tools/poster_wide.py
产物： work/promo_grid/pages/pg_hero_<名>.png（1600×900）
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from core import gunsmith as gs  # noqa: E402
from core import loader  # noqa: E402
import render  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "work", "promo_grid", "pages")
BASES = [
    ("M4A1", "Rec_AR_M4A1-Std_001_3P.uasset", "pbr"),
    ("AK12", "Rec_AR_AK12_030_3P.uasset", "pbr"),
    ("MP5A4", "Rec_SMG_MP5A4-Std_004_3P.uasset", "pbr"),
    ("neon", "Rec_AR_M4A1-Std_001_3P.uasset", "neon"),
]
W, HH = 1600, 900

os.makedirs(OUT, exist_ok=True)
app = QApplication([])
idx = loader.index()
viewer = render.MeshViewer()
viewer.resize(W, HH)
viewer.set_background("studio")

for label, suffix, style in BASES:
    hits = [k for k in idx if k.endswith(suffix)]
    if not hits:
        print("[wide] miss", suffix)
        continue
    base = hits[0]
    bundle = loader.load_model(base, lod=0, want_textures=True)
    pairs = []
    for spec in gs.official_loadout(base):
        b = loader.load_model(spec.vpath, lod=0, want_textures=True)
        if getattr(b, "mesh", None):
            pairs.append((spec, b))
    combo = gs.assemble(bundle, pairs, base_vpath=base)
    viewer.set_style(style)
    viewer.set_mesh(combo.mesh, combo.materials, combo.textures)
    viewer.frame_all()
    cam = viewer._state.camera                                    # noqa: SLF001
    cam.distance *= 0.88
    path = os.path.join(OUT, f"pg_hero_{label}.png")
    viewer.capture(path, width=W, height=HH)
    print("[wide] saved", path)
print("[wide] done")
