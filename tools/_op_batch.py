"""批量体检干员网格：顶点/三角/材质数/贴图数/耗时/异常。

用法： python tools/_op_batch.py [数量]
"""
from __future__ import annotations

import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import loader  # noqa: E402

limit = int(sys.argv[1]) if len(sys.argv) > 1 else 14
idx = loader.index()
pat = re.compile(r"M_[A-Za-z0-9_]+_(Body_3P_HD|Body_UI_HD|Face_UI_HD|Upper_1P_HD|Lower_3P_HD)\.uasset$")
pool = [k for k in idx if pat.search(k)]
pool.sort()
print("候选:", len(pool))

# 干员本体 + 皮肤各取一部分
hero = [k for k in pool if "/Models/Characters" in k]
skin = [k for k in pool if "/Commerical/CharAppear" in k]
picks = hero[: limit // 2 + limit % 2] + skin[: limit // 2]

print(f"{'资产':<46} {'顶点':>7} {'三角':>7} {'材质':>4} {'贴图':>4} {'秒':>5} 备注")
for vp in picks:
    name = "/".join(vp.split("/")[-2:])
    t0 = time.time()
    try:
        b = loader.load_model(vp, want_textures=False)
        dt = time.time() - t0
        mesh = getattr(b, "mesh", None)
        lod = mesh.lods[0] if mesh and mesh.lods else None
        verts = len(lod.positions) if lod else 0
        tris = sum(s.num_triangles for s in lod.sections) if lod else 0
        secs = len(lod.sections) if lod else 0
        mats = len(b.materials)
        texs = len(b.textures)
        note = ""
        if tris == 0:
            note = "!! 无三角"
        elif secs <= 1 and mats > 1:
            note = f"仅 {secs} 段 / {mats} 材质"
        print(f"{name:<46} {verts:>7} {tris:>7} {mats:>4} {texs:>4} {dt:>5.1f} {note}")
    except Exception as exc:                                   # noqa: BLE001
        print(f"{name:<46} {'-':>7} {'-':>7} {'-':>4} {'-':>4} {time.time() - t0:>5.1f} "
              f"!! {str(exc)[:60]}")
