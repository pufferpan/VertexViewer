"""全库 UV 审计：找「贴图错位」类资产的量化特征。

    python tools/uv_audit.py [取样数]

指标（每个 LOD）：
  n / uvshape    顶点数、UV 数组形状
  uvbox           UV0 的 u/v 范围
  deg%            退化三角形占比（3 个角的 UV 面积 ~ 0，但 3D 面积不 ~ 0）
  out%            UV 出界（超出 [-0.05, 1.05]）三角形占比
  stretch         UV 边长 / 3D 边长的中位数比值（按包围盒归一化后）
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from core import loader  # noqa: E402

CATALOG = r"G:\xmcl-fetch\work\mesh_catalog.json"


def lod_metrics(lod):
    uv = lod.uvs
    pos = lod.positions
    idx = lod.indices
    if uv is None or idx.size < 3:
        return None
    tri = idx.reshape(-1, 3)
    tri = tri[(tri < uv.shape[0]).all(axis=1)]
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    u = uv
    uva = np.stack([u[a, 0], u[b, 0], u[c, 0]], 1)
    uvb = np.stack([u[a, 1], u[b, 1], u[c, 1]], 1)
    uv_area = np.abs((uvb[:, 1] - uvb[:, 0]) * (uva[:, 2] - uva[:, 0])
                     - (uva[:, 1] - uva[:, 0]) * (uvb[:, 2] - uvb[:, 0])) * 0.5
    p = pos
    e1 = p[b] - p[a]
    e2 = p[c] - p[a]
    p3_area = 0.5 * np.linalg.norm(np.cross(e1, e2), axis=1)
    small3 = p3_area > 1e-9
    deg = float((uv_area[small3] < 1e-9).mean()) if small3.any() else 0.0
    out = float(((uva < -0.05) | (uva > 1.05) | (uvb < -0.05) | (uvb > 1.05)).any(axis=1).mean())
    r3 = np.linalg.norm(e1, axis=1) + 1e-12
    ruv = np.linalg.norm(np.stack([uva[:, 1] - uva[:, 0], uvb[:, 1] - uvb[:, 0]], 1), axis=1)
    stretch = float(np.median(ruv / r3)) if r3.size else 0.0
    return dict(n=int(uv.shape[0]), uvshape=tuple(uv.shape),
                uvbox=(round(float(u[:, 0].min()), 3), round(float(u[:, 0].max()), 3),
                       round(float(u[:, 1].min()), 3), round(float(u[:, 1].max()), 3)),
                deg=deg, out=out, stretch=stretch, tris=int(tri.shape[0]))


def pick(n):
    cat = json.load(open(CATALOG, encoding="utf-8"))
    meshes = [k for k, v in cat.items() if v in ("StaticMesh", "SkeletalMesh")]
    sm = [k for k in meshes if cat[k] == "StaticMesh" and "/Models/" in k and "/SM_" in k]
    step = max(1, len(sm) // n)
    return sm[::step][:n]


def main(argv):
    args = argv[1:]
    if len(args) == 1 and args[0].isdigit():
        vps = pick(int(args[0]))
    else:
        vps = args or pick(24)
    rows = []
    for vp in vps:
        name = vp.rsplit("/", 1)[-1]
        try:
            m = loader.load_mesh(vp)
        except Exception as exc:                                   # noqa: BLE001
            print(f"{name}: LOAD FAIL {exc}")
            continue
        if not m or not m.lods:
            print(f"{name}: no mesh")
            continue
        met = lod_metrics(m.lods[0])
        if met is None:
            print(f"{name}: no uv")
            continue
        rows.append((name, met))
        print(f"{name[:52]:52s} n={met['n']:5d} deg={met['deg']*100:5.1f}% "
              f"out={met['out']*100:5.1f}% stretch={met['stretch']:.3f} "
              f"box={met['uvbox']}")
    if not rows:
        return
    bad = [r for r in rows if r[1]["deg"] > 0.05]
    print(f"\n退化三角形 >5% 的资产: {len(bad)}/{len(rows)}")
    for name, met in bad:
        print("  ", name, f"deg={met['deg']*100:.1f}%")


if __name__ == "__main__":
    main(sys.argv)
