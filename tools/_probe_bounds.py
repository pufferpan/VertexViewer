import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np                                    # noqa: E402

from core import gunsmith as gs                       # noqa: E402
from core import loader                               # noqa: E402

C = "../../../DeltaForce/Content/Models/Weapons/Parts/"
REFS = [
    ("Rec", C + "Rec/AR/Rec_AR_M4A1-Std_001/Rec_AR_M4A1-Std_001_3P.uasset"),
    ("Bar", C + "Bar/Bar_S-370_M4A1-Std_001/Bar_S-370_M4A1-Std_001_3P.uasset"),
    ("Muz", C + "Muz/Muz_S-F_M4A1-Std_001/Muz_S-F_M4A1-Std_001_3P.uasset"),
    ("Mag", C + "Mag/Mag_556-45-30R_M4A1-Std_001/Mag_556-45-30R_M4A1-Std_001_3P.uasset"),
    ("Sto", C + "Sto/Sto_A_M4A1-Std_001/Sto_A_M4A1-Std_001_3P.uasset"),
    ("PisG", C + "PisG/PisG_B_M4A1-Std_001/PisG_B_M4A1-Std_001_3P.uasset"),
]

for tag, vp in REFS:
    try:
        bundle = loader.load_model(vp, want_textures=False)
    except Exception as exc:                                  # noqa: BLE001
        print("%-5s LOAD FAIL %s" % (tag, exc))
        continue
    lod = gs._lod0(bundle)
    if lod is None:
        print("%-5s no mesh" % tag)
        continue
    lo, hi = gs.bounds(lod)
    print("%-5s verts=%-6d lo=(%7.3f %7.3f %7.3f) hi=(%7.3f %7.3f %7.3f) size=(%6.3f %6.3f %6.3f)"
          % (tag, len(lod.positions), lo[0], lo[1], lo[2], hi[0], hi[1], hi[2],
             hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]))
    _ = np
