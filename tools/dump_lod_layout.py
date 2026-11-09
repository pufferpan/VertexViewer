"""Print the cooked LOD layout of an asset: position headers + index containers.

usage: python tools/dump_lod_layout.py <asset-name> [<asset-name> ...]
For every position vertex buffer header (stride,num,stride,num) we search
backwards for the matching (elem_size,count) index container that ends exactly
at the header, and report quality metrics for that pair.
"""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from core import loader, mesh as M
from tools.diag_index import boundary_and_stats


def max_component(tri):
    n = len(tri)
    E = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]], 0)
    k = np.sort(E, axis=1).astype(np.int64)
    key = k[:, 0] * 1000000 + k[:, 1]
    o = np.argsort(key, kind="stable")
    key = key[o]
    to = np.tile(np.arange(n), 3)[o]
    st = np.nonzero(np.r_[True, key[1:] != key[:-1]])[0]
    en = np.r_[st[1:], len(key)]
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
    return len(u), int(c.max()), c.max() / n


def analyse(name):
    idx = loader.index()
    v = [k for k in idx if k.endswith("/" + name + ".uasset")][0]
    blobs = loader.load_blobs(v)
    buf = blobs["uasset"] + (blobs.get("uexp") or b"")
    print(f"\n{name}  uasset={len(blobs['uasset'])} uexp={len(blobs.get('uexp') or b'')} ubulk={len(blobs.get('ubulk') or b'')}")
    heads = M._find_position_headers(buf, 4025, len(buf))
    print("  position headers:", heads)
    for ho, nv in heads[:6]:
        # look for (2,count) or (4,count) ending exactly at ho
        found = []
        for elem in (2, 4):
            # direct: count such that off + count*elem == ho, scan possible counts
            for cnt in range(300, 20000):
                off = ho - cnt * elem
                if off < 0:
                    break
                if struct.unpack_from("<I", buf, off - 8)[0] == elem and \
                   struct.unpack_from("<I", buf, off - 4)[0] == cnt:
                    found.append((elem, cnt, off))
        if found:
            for elem, cnt, off in found[:3]:
                dt = "<u2" if elem == 2 else "<u4"
                ind = np.frombuffer(buf, dtype=dt, count=cnt, offset=off).astype(np.int64)
                if ind.max() >= nv:
                    print(f"   pos@{ho} nv={nv}: container @{off} {cnt} idx -> max {ind.max()} (reject)")
                    continue
                st = boundary_and_stats(ind, nv)
                nc, mx, ratio = max_component(ind.reshape(-1, 3))
                print(f"   pos@{ho} nv={nv}: idx@{off} elem={elem} count={cnt} tris={st['tris']} "
                      f"b={st['boundary_ratio']:.3f} comps={nc} maxcomp={mx} ratio={ratio*100:.1f}%")
        else:
            print(f"   pos@{ho} nv={nv}: no inline container ends at header")


if __name__ == "__main__":
    for nm in sys.argv[1:]:
        analyse(nm)
