"""Sample head/equipment meshes and report which index-container flavour they use.

usage: python tools/sample_flavour.py [count] [pattern]

For every matched asset it prints one line with:
  name | stream (inline|ubulk) | LOD0 verts/tris | boundary_ratio | comps | maxcomp%
The point is to know how many assets share the "no-ubulk, index buffer before
the position header" flavour that M_Head_Head_Helmet_HAAVK_094_3P_HD uses,
and how 094's topology compares with the rest of the family.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from core import loader, mesh as M
from tools.scan_index_tri import comp_stats


def main():
    cnt = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    pat = sys.argv[2] if len(sys.argv) > 2 else "/Equipments_HD/"
    idx = loader.index()
    cand = [k for k in idx
            if k.endswith("_3P_HD.uasset") and pat in k and "/Materials/" not in k]
    seen, picked = set(), []
    for k in cand:
        base = os.path.basename(k)
        if base in seen:
            continue
        seen.add(base)
        picked.append(k)
    print(f"{len(cand)} candidates, using first {min(cnt, len(picked))}")
    rows = []
    for k in picked[:cnt]:
        name = os.path.basename(k)[:-len(".uasset")]
        try:
            blobs = loader.load_blobs(k)
            m = M.load_mesh_from_blobs(k, blobs)
        except Exception as exc:
            print(f"{name[:46]:46s} SKIP {type(exc).__name__}: {exc}")
            continue
        if not m.lods:
            continue
        lod = m.lods[0]
        nv = len(lod.positions)
        tri = np.asarray(lod.indices).ravel()
        if tri.size == 0 or tri.size % 3 or tri.max() >= nv:
            print(f"{name[:46]:46s} odd index block n={tri.size} nv={nv}")
            continue
        b, mx, nc, nu = comp_stats(tri.reshape(-1, 3), nv)
        stream = "ubulk" if (blobs.get("ubulk") or b"") else "inline"
        rows.append((name, stream, nv, tri.size // 3, b, nc, mx / (tri.size // 3)))
        print(f"{name[:46]:46s} {stream:6s} v{nv:6d} t{tri.size // 3:6d} "
              f"b={b:.3f} comps={nc:4d} max={100 * mx / (tri.size // 3):5.1f}%")
    if rows:
        b = np.array([r[4] for r in rows])
        mp = np.array([r[6] for r in rows])
        inl = sum(1 for r in rows if r[1] == "inline")
        print(f"\n{len(rows)} meshes: inline={inl} ubulk={len(rows) - inl}")
        print(f"boundary   min/med/max = {b.min():.3f}/{np.median(b):.3f}/{b.max():.3f}")
        print(f"maxcomp%   min/med/max = {100 * mp.min():.1f}/{100 * np.median(mp):.1f}/{100 * mp.max():.1f}")
        print(f"meshes with maxcomp<12%: {(mp < 0.12).sum()}; <20%: {(mp < 0.20).sum()}")


if __name__ == "__main__":
    main()
