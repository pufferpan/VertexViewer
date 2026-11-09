"""宣传图素材：同一把枪的不同渲染风格（pbr / neon / blueprint / clay / toon / posterize）。

用法： python tools/poster_styles.py <输出目录>
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from core import gunsmith as gs  # noqa: E402
from core import loader  # noqa: E402
import render  # noqa: E402

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else r"work\poster")
BASE = sys.argv[2] if len(sys.argv) > 2 else "Rec_AR_M4A1-Std_001_3P.uasset"
STYLES = ("pbr", "neon", "blueprint", "clay", "toon", "posterize")

os.makedirs(OUT, exist_ok=True)
app = QApplication([])
idx = loader.index()
base = [k for k in idx if k.endswith(BASE)][0]
bundle = loader.load_model(base, lod=0, want_textures=True)
specs = gs.official_loadout(base)
pairs = []
for spec in specs:
    b = loader.load_model(spec.vpath, lod=0, want_textures=True)
    if getattr(b, "mesh", None):
        pairs.append((spec, b))
combo = gs.assemble(bundle, pairs, base_vpath=base)
print("[styles] parts", len(pairs))

viewer = render.MeshViewer()
viewer.resize(1000, 700)
viewer.set_background("dark")
viewer.set_mesh(combo.mesh, combo.materials, combo.textures)
viewer.frame_all()

for style in STYLES:
    try:
        viewer.set_style(style)
    except Exception as exc:                                     # noqa: BLE001
        print("[styles] skip", style, exc)
        continue
    out = os.path.join(OUT, f"style_{style}.png")
    viewer.capture(out, width=1000, height=700)
    print("[styles] saved", out)
print("[styles] done")
