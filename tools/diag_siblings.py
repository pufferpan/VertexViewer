"""Scan a set of skeletal-mesh assets and report per-LOD topology quality.

usage: python tools/diag_siblings.py <path-substring> [limit]
Prints, per asset: per-LOD  tris / boundary_ratio / ref% / degenerate%
and a final tally of how many assets are "clean" (LOD0 boundary < 0.25).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from core import loader, mesh as M
from tools.diag_index import boundary_and_stats


def run(sub, limit=40, show=True):
    idx = loader.index()
    paths = [k for k in idx if k.endswith(".uasset") and sub in k]
    rows = []
    for p in paths[:limit]:
        try:
            m = M.load_mesh_from_blobs(p, loader.load_blobs(p))
        except Exception as e:
            print(f"  {os.path.basename(p)[:52]:52s} FAIL {type(e).__name__}: {e}")
            continue
        st = []
        bad = False
        for lod in m.lods:
            ind = np.asarray(lod.indices).ravel()
            P = np.asarray(lod.positions)
            if ind.size < 3:
                st.append("0t")
                continue
            s = boundary_and_stats(ind, len(P))
            st.append(f"{s['tris']}t/b{s['boundary_ratio']:.2f}/r{100*s['verts_used']/max(1,len(P)):.0f}%")
            if s["boundary_ratio"] > 0.30 or s["degenerate"] > 0.001:
                bad = True
        rows.append((os.path.basename(p), st, bad))
        if show:
            print(f"  {os.path.basename(p)[:52]:52s} {'BROKEN' if bad else 'ok    '} " + " | ".join(st))
    nbad = sum(1 for r in rows if r[2])
    print(f"\n{len(rows)} assets, {nbad} flagged (LOD0-ish boundary>0.30), {len(rows)-nbad} clean")
    return rows


if __name__ == "__main__":
    sub = sys.argv[1]
    lim = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    run(sub, lim)
