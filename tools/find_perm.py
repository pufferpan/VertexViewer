"""Search a cooked payload for a vertex remap table (permutation of 0..n-1).

A cooked skeletal mesh sometimes stores the vertex buffer in a *reordered* form
(e.g. sorted by skin weights) and keeps the original ordering as a
``TArray<uint16>`` permutation next to it.  If such a table exists, the index
buffer has to be pushed through it before it lines up with the positions.

usage: python tools/find_perm.py <asset-name> [<asset-name> ...]
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from core import loader, mesh as M


def find_perm(buf, n, dtype="<u2"):
    """all offsets where buf[o:o+n] is a permutation of 0..n-1"""
    itemsize = np.dtype(dtype).itemsize
    limit = len(buf) - n * itemsize
    if limit <= 0:
        return []
    # read the whole buffer once, then use a prefix sum to prefilter
    total = (len(buf) - len(buf) % itemsize) // itemsize
    arr = np.frombuffer(buf, dtype=dtype, count=total)
    csum = np.concatenate([[0], np.cumsum(arr.astype(np.int64))])
    target = n * (n - 1) // 2
    hits = []
    starts = np.arange(0, total - n + 1)
    sums = csum[starts + n] - csum[starts]
    cand = starts[np.nonzero(sums == target)[0]]
    for s in cand:
        w = arr[s:s + n]
        if w.max() >= n:
            continue
        if len(np.unique(w)) == n:
            hits.append(int(s) * itemsize)
    return hits


def main(names):
    idx = loader.index()
    for nm in names:
        v = [k for k in idx if k.endswith("/" + nm + ".uasset")][0]
        blobs = loader.load_blobs(v)
        buf = blobs["uasset"] + (blobs.get("uexp") or b"") + (blobs.get("ubulk") or b"")
        m = M.load_mesh_from_blobs(v, blobs)
        print(f"{nm}: len={len(buf)} lods={len(m.lods)} verts0={len(m.lods[0].positions)}")
        for li, lod in enumerate(m.lods[:2]):
            n = len(lod.positions)
            for dt in ("<u2", "<u4"):
                hits = find_perm(buf, n, dt)
                print(f"   LOD{li} n={n} {dt}: permutation-table hits -> {hits[:8]}")
    return


if __name__ == "__main__":
    main(sys.argv[1:] or ["M_Head_Head_Helmet_HAAVK_094_3P_HD"])
