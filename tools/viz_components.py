"""Colour every connected component of a decoded LOD with its own hue.

The point is to answer "is this mesh shattered, or is it a mesh made of many
unwrap patches / net strips?"  Patches that tile the surface show up as a clean
mosaic; interpenetrating shards show up as chaotic overlapping colours.

usage: python tools/viz_components.py <asset-name-substring> [lod] [outprefix]
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from core import loader, mesh as M

try:
    from PIL import Image
except Exception:
    Image = None


def components(tri, nv):
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
    uniq, comp = np.unique(roots, return_inverse=True)
    return comp, len(uniq)


def raster_color(tp, comp, ncomp, w, h, axis, sign=1.0):
    def proj(P):
        if axis == 0:
            return P[:, 1], P[:, 2], P[:, 0] * sign
        if axis == 1:
            return P[:, 0], P[:, 2], P[:, 1] * sign
        return P[:, 0], P[:, 1], P[:, 2] * sign

    allp = tp.reshape(-1, 3)
    pa, pb, pd = proj(allp)
    amin, amax, bmin, bmax = pa.min(), pa.max(), pb.min(), pb.max()
    sc = (min(w, h) - 4) / max(amax - amin, bmax - bmin, 1e-9)
    X = ((pa - amin) * sc + (w - (amax - amin) * sc) / 2).reshape(-1, 3)
    Y = ((bmax - pb) * sc + (h - (bmax - bmin) * sc) / 2).reshape(-1, 3)
    D = pd.reshape(-1, 3)

    rng = np.random.default_rng(12345)
    pal = rng.integers(60, 255, size=(max(ncomp, 1), 3)).astype(np.float32)

    depth = np.full((h, w), np.inf, np.float32)
    img = np.zeros((h, w, 3), np.float32)
    mask = np.zeros((h, w), bool)
    for t in range(len(tp)):
        x0, x1, x2 = X[t]
        y0, y1, y2 = Y[t]
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-9:
            continue
        xmin = max(int(np.floor(min(x0, x1, x2))), 0)
        xmax = min(int(np.ceil(max(x0, x1, x2))), w - 1)
        ymin = max(int(np.floor(min(y0, y1, y2))), 0)
        ymax = min(int(np.ceil(max(y0, y1, y2))), h - 1)
        if xmin > xmax or ymin > ymax:
            continue
        xs = np.arange(xmin, xmax + 1) + 0.5
        ys = np.arange(ymin, ymax + 1) + 0.5
        gx, gy = np.meshgrid(xs, ys)
        w0 = ((x1 - gx) * (y2 - gy) - (x2 - gx) * (y1 - gy)) / area
        w1 = ((x2 - gx) * (y0 - gy) - (x0 - gx) * (y2 - gy)) / area
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any():
            continue
        d = w0 * D[t, 0] + w1 * D[t, 1] + w2 * D[t, 2]
        sub = depth[ymin:ymax + 1, xmin:xmax + 1]
        upd = inside & (d < sub)
        sub[upd] = d[upd]
        img[ymin:ymax + 1, xmin:xmax + 1][upd] = pal[comp[t] % ncomp]
        mask[ymin:ymax + 1, xmin:xmax + 1][upd] = True
    return img, mask


def main(name, lod_i, prefix):
    idx = loader.index()
    cand = [k for k in idx if name in k]
    cand = [k for k in cand if "/Materials/" not in k]
    if not cand:
        print("no asset matches", name)
        return
    path = cand[0]
    m = M.load_mesh_from_blobs(path, loader.load_blobs(path))
    lod = m.lods[lod_i]
    P = np.asarray(lod.positions, np.float64)
    tri = np.asarray(lod.indices, np.int64).ravel().reshape(-1, 3)
    comp, ncomp = components(tri, len(P))
    sizes = np.bincount(comp)
    area = 0.5 * np.linalg.norm(np.cross(P[tri[:, 1]] - P[tri[:, 0]], P[tri[:, 2]] - P[tri[:, 0]]), axis=1)
    print(f"{os.path.basename(path)} LOD{lod_i}: {len(tri)} tris {ncomp} comps")
    small = sizes <= 4
    print(f"  comps with <=4 tris: {small.sum()}  ({small.mean()*100:.0f}% of comps, "
          f"{sizes[small].sum()} tris = {sizes[small].sum()/len(tri)*100:.1f}% of tris)")
    print(f"  total area={area.sum():.5f} m^2  largest comp area="
          f"{area[comp == int(np.argmax(sizes))].sum():.5f} m^2")
    for k, axis in enumerate((0, 1, 2)):
        img, mask = raster_color(P[tri], comp, max(ncomp, 1), 420, 420, axis)
        print(f"  view axis={axis} coverage={mask.mean()*100:.1f}%")
        if Image is not None:
            out = img.clip(0, 255).astype(np.uint8)
            out[~mask] = (20, 20, 24)
            p = f"{prefix}_{'XYZ'[k]}.png"
            Image.fromarray(out).save(p)


if __name__ == "__main__":
    nm = sys.argv[1]
    li = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    pre = sys.argv[3] if len(sys.argv) > 3 else "comp_" + nm[:18]
    main(nm, li, pre)
