"""Brute-force scan a cooked payload for the *best* u16 triangle list.

For every even byte offset we take a window of L u16 values and keep the window
when every value is a valid vertex id (< nv).  Survivors are first ranked by
mean triangle edge length (cheap, vectorised: a shuffled list pairs far-apart
vertices), then the best ones are scored with the acceptance metrics
(boundary ratio + largest connected component share).

usage: python tools/scan_index_tri.py <asset-name> [L ...]
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from core import loader, mesh as M


def comp_stats(tri, nv):
    n = len(tri)
    E = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]], 0)
    k = np.sort(E, axis=1).astype(np.int64)
    key = k[:, 0] * 1000000 + k[:, 1]
    o = np.argsort(key, kind="stable")
    key = key[o]
    to = np.tile(np.arange(n), 3)[o]
    st = np.nonzero(np.r_[True, key[1:] != key[:-1]])[0]
    en = np.r_[st[1:], len(key)]
    boundary = int((en - st == 1).sum())
    nuniq = len(st)
    par = np.arange(n)

    def f(a):
        r = a
        while par[r] != r:
            r = par[r]
        while par[a] != r:
            par[a], a = r, par[a]
        return r

    for s, e in zip(st, en):
        if e - s >= 2:
            a = f(int(to[s]))
            for j in range(s + 1, e):
                b = f(int(to[j]))
                if a != b:
                    par[b] = a
    roots = np.array([f(i) for i in range(n)])
    u, c = np.unique(roots, return_counts=True)
    return boundary / max(1, nuniq), int(c.max()), len(u), nuniq


def score_offsets(arr, offs, L, pos, nv, topk=25, label="", par=0):
    if len(offs) == 0:
        print(f"  {label}: 0 windows")
        return []
    W = np.stack([arr[o:o + L] for o in offs]).astype(np.int32)
    W = W.reshape(len(offs), -1, 3)
    p = pos[W]                                   # (ncand, ntris, 3, 3)
    e = np.linalg.norm(p - np.roll(p, -1, axis=2), axis=-1).mean(axis=(1, 2))
    order = np.argsort(e)
    print(f"  {label}: {len(offs)} all-valid windows, best mean edge {e[order[0]]:.4f}, median {np.median(e):.4f}")
    out = []
    for i in order[:topk]:
        tri = W[i].astype(np.int64)
        deg = int((tri[:, 0] == tri[:, 1]).sum() + (tri[:, 1] == tri[:, 2]).sum() + (tri[:, 0] == tri[:, 2]).sum())
        b, mx, nc, nuniq = comp_stats(tri, nv)
        out.append((b, -mx, par + 2 * int(offs[i]), deg, nc, mx, float(e[i])))
    out.sort()
    for b, nmx, off, deg, nc, mx, em in out[:10]:
        print(f"     off={off:7d} L={L} b={b:.3f} maxcomp={mx:5d} ({100.0*mx/(L//3):5.1f}%) "
              f"comps={nc} deg={deg} meanedge={em:.4f}")
    return out


def main(name, Ls):
    idx = loader.index()
    v = [k for k in idx if k.endswith("/" + name + ".uasset")][0]
    blobs = loader.load_blobs(v)
    buf = blobs["uasset"] + (blobs.get("uexp") or b"")
    m = M.load_mesh_from_blobs(v, blobs)
    lod0 = m.lods[0]
    pos = np.asarray(lod0.positions, dtype=np.float64)
    nv = len(pos)
    print(f"{name}: payload={len(buf)} nv0={nv} tris0={len(lod0.indices)//3}")
    # NOTE: virtual offsets are uasset_len + uexp_off, and uasset_len (4025) is
    # odd, so every aligned uexp u16 lands on an ODD virtual offset.  Scan both
    # byte parities, otherwise the real buffers are invisible.
    for par in (0, 1):
        arr = np.frombuffer(buf[par:], dtype="<u2", count=(len(buf) - par) // 2)
        total = len(arr)
        bad = (arr >= nv).astype(np.int32)
        cs = np.concatenate([[0], np.cumsum(bad)])
        for L in Ls:
            starts = np.arange(0, total - L + 1)
            ok = (cs[starts + L] - cs[starts]) == 0
            hits = starts[ok]
            stride = max(1, len(hits) // 4000)
            score_offsets(arr, hits[::stride], L, pos, nv, label=f"par={par} L={L}", par=par)


if __name__ == "__main__":
    name = sys.argv[1]
    Ls = [int(x) for x in sys.argv[2:]] or [14841, 14844, 14847]
    main(name, Ls)
