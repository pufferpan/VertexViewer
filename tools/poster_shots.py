"""宣传图素材：把几把「官方配件」整枪离屏渲染成透明背景 PNG。

用法： python tools/poster_shots.py <输出目录>
产物： <out>/gun_<枪名>.png（1000x700，RGBA，透明底）
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from core import gunsmith as gs  # noqa: E402
from core import loader  # noqa: E402
import render  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else r"work\poster"
BASES = [
    ("M4A1", "Rec_AR_M4A1-Std_001_3P.uasset"),
    ("HK416", "Rec_AR_HK416_021_3P.uasset"),
    ("AK12", "Rec_AR_AK12_030_3P.uasset"),
    ("SCAR-H", "Rec_AR_ScarH_045_3P.uasset"),
    ("MP5A4", "Rec_SMG_MP5A4-Std_004_3P.uasset"),
    ("AK74", "Rec_AR_AK74-Std_002_3P.uasset"),
    ("SG553", "Rec_AR_SG553_024_3P.uasset"),
]

os.makedirs(OUT, exist_ok=True)
app = QApplication([])
idx = loader.index()


def find(suffix: str) -> str:
    hits = [k for k in idx if k.endswith(suffix)]
    if not hits:
        low = suffix.lower()
        hits = [k for k in idx if k.lower().endswith(low)]
    return hits[0] if hits else ""


viewer = render.MeshViewer()
viewer.resize(1000, 700)
viewer.set_background("dark")
viewer.set_style("pbr")

for label, suffix in BASES:
    base = find(suffix)
    if not base:
        print(f"[poster] miss base {suffix}")
        continue
    bundle = loader.load_model(base, lod=0, want_textures=True)
    if not getattr(bundle, "mesh", None):
        print(f"[poster] no mesh {base}")
        continue
    try:
        specs = gs.official_loadout(base)
    except Exception as exc:                                     # noqa: BLE001
        print(f"[poster] loadout failed {label}: {exc}")
        specs = []
    pairs = []
    for spec in specs:
        b = loader.load_model(spec.vpath, lod=0, want_textures=True)
        if getattr(b, "mesh", None):
            pairs.append((spec, b))
    combo = gs.assemble(bundle, pairs, base_vpath=base)
    viewer.set_mesh(combo.mesh, combo.materials, combo.textures)
    viewer.frame_all()
    out = os.path.join(OUT, f"gun_{label}.png")
    viewer.capture(out, width=1000, height=700)
    print(f"[poster] {label}: {len(pairs)} parts -> {out}")

print("[poster] done", OUT)
