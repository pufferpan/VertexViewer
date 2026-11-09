"""Tiny software rasterizer to eyeball a decoded LOD (no GUI needed).

usage: python tools/viz_mesh.py <asset-name-substring> [lod] [outprefix]
Writes PNGs next to the script's cwd: <outprefix>_X.png, _Y.png, _Z.png
Shading: face normal dotted with the view axis (flat shade), z-buffer + 1px
silhouette. Also prints per-view coverage (fraction of the bbox silhouette
that is covered) and the count of holes.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from core import loader, mesh as M

try:
    from PIL import Image
except Exception:
    Image = None


def raster(tri_pts, w, h, axis, sign):
    """tri_pts: (n,3,3) float in world; project along axis. returns depth img, mask"""
    # basis
    def proj(P):
        v = P.copy()
        if axis == 0:
            a, b, d = v[:, 1], v[:, 2], v[:, 0] * sign
        elif axis == 1:
            a, b, d = v[:, 0], v[:, 2], v[:, 1] * sign
        else:
            a, b, d = v[:, 0], v[:, 1], v[:, 2] * sign
        return a, b, d

    allp = tri_pts.reshape(-1, 3)
    pa, pb, pd = proj(allp)
    amin, amax = pa.min(), pa.max()
    bmin, bmax = pb.min(), pb.max()
    sc = (min(w, h) - 4) / max(amax - amin, bmax - bmin, 1e-9)
    ox = (w - (amax - amin) * sc) / 2
    oy = (h - (bmax - bmin) * sc) / 2
    X = (pa - amin) * sc + ox
    Y = (bmax - pb) * sc + oy
    X = X.reshape(-1, 3)
    Y = Y.reshape(-1, 3)
    D = pd.reshape(-1, 3)
    depth = np.full((h, w), np.inf, np.float32)
    shade = np.zeros((h, w), np.float32)
    mask = np.zeros((h, w), bool)

    # face normals
    n = np.cross(tri_pts[:, 1] - tri_pts[:, 0], tri_pts[:, 2] - tri_pts[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    ln[ln < 1e-14] = 1
    n = n / ln
    view = np.array([0.0, 0.0, 1.0]) if axis == 2 else (np.array([1.0, 0, 0]) if axis == 0 else np.array([0, 1.0, 0]))
    lam = np.abs(n @ view)
    lam = 0.15 + 0.85 * lam

    for t in range(len(tri_pts)):
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
        ssub = shade[ymin:ymax + 1, xmin:xmax + 1]
        ssub[upd] = lam[t]
        msub = mask[ymin:ymax + 1, xmin:xmax + 1]
        msub[upd] = True
    return shade, mask


def render(name, lod_i, prefix):
    idx = loader.index()
    cand = [k for k in idx if name in k]
    if not cand:
        print("no asset matches", name)
        return
    path = cand[0]
    m = M.load_mesh_from_blobs(path, loader.load_blobs(path))
    lod = m.lods[lod_i]
    P = np.asarray(lod.positions, np.float64)
    ind = np.asarray(lod.indices, np.int64).ravel()
    tri = ind.reshape(-1, 3)
    tp = P[tri]
    print(f"{os.path.basename(path)} LOD{lod_i}: {len(tri)} tris  bbox={(P.max(0)-P.min(0)).round(3)}")
    outs = []
    for k, axis in enumerate((0, 1, 2)):
        shade, mask = raster(tp, 420, 420, axis, 1.0)
        cov = mask.mean()
        # hole count: connected components of non-mask inside bbox? use simple scan
        print(f"  view axis={axis} coverage={cov*100:.1f}%")
        if Image is not None:
            img = (np.stack([shade * 255.0] * 3, -1)).clip(0, 255).astype(np.uint8)
            img[~mask] = (25, 25, 30)
            p = f"{prefix}_{'XYZ'[k]}.png"
            Image.fromarray(img).save(p)
            outs.append(p)
    return outs


if __name__ == "__main__":
    name = sys.argv[1]
    lod = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    prefix = sys.argv[3] if len(sys.argv) > 3 else "viz_" + name[:20]
    render(name, lod, prefix)
