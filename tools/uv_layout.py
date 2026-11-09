"""把每套 UV 的排布画成 PNG，并叠在 BaseColor 贴图上看对位。

    python tools/uv_layout.py <vpath> [通道数上限]

输出：uv_layout_<stem>_ch<N>.png —— 左：UV 线框叠贴图；右：纯线框。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from core import loader  # noqa: E402

OUT_DIR = r"G:\xmcl-fetch\work"
SIZE = 768


def draw_channel(lod, ch, bg=None):
    n = int(lod.positions.shape[0])
    uv = lod.uv(ch) if callable(getattr(lod, "uv", None)) else getattr(lod, "uvs", None)
    if uv is None:
        return None, 0.0
    uv = np.asarray(uv, np.float32).reshape(n, -1)[:, :2]
    idx = np.asarray(lod.indices).reshape(-1, 3)
    idx = idx[(idx < n).all(axis=1)]
    img = bg.copy() if bg is not None else Image.new("RGB", (SIZE, SIZE), (24, 26, 30))
    dr = ImageDraw.Draw(img)

    def to_px(u, v):
        x = u * (SIZE - 1)
        y = (1.0 - v) * (SIZE - 1)          # 图像坐标上 v 向上
        return x, y

    # 重叠度：把三角形画到粗网格上数覆盖次数
    grid = np.zeros((64, 64), np.int32)
    step = max(1, idx.shape[0] // 4000)
    for tri in idx[::step]:
        pts = [to_px(*uv[i]) for i in tri]
        dr.line([pts[0], pts[1], pts[2], pts[0]], fill=(0, 255, 120), width=1)
        cu = ((uv[tri, 0] % 1.0) * 63).astype(int)
        cv = ((uv[tri, 1] % 1.0) * 63).astype(int)
        for x, y in zip(cu, cv):
            grid[y, x] += 1
    covered = grid[grid > 0]
    overlap = float((covered > 1).mean()) if covered.size else 0.0
    return img, overlap


def main(argv):
    vp = argv[1]
    bnd = loader.load_model(vp, want_cn=False)
    if not bnd.mesh:
        print("no mesh")
        return
    lod = bnd.mesh.lods[0]
    base = None
    for tex in bnd.textures or []:
        if tex is getattr(bnd.materials[0], "base_color_texture", None):
            pass
        if tex.name and tex.name.endswith("BC"):
            arr = np.asarray(tex.rgba)[:, :, :3].astype(np.uint8)
            base = Image.fromarray(arr).resize((SIZE, SIZE))
            print("bg 用贴图", tex.name, arr.shape)
            break
    stem = os.path.splitext(os.path.basename(vp))[0]
    count = int(argv[2]) if len(argv) > 2 else 4
    real = 0
    for ch in range(count):
        img, overlap = draw_channel(lod, ch, base)
        if img is None:
            break
        real += 1
        out = os.path.join(OUT_DIR, f"uv_layout_{stem}_ch{ch}.png")
        img.save(out)
        print(f"ch{ch}: 重叠率 {overlap*100:.1f}%  -> {out}")
    if base is not None:
        base.save(os.path.join(OUT_DIR, f"uv_layout_{stem}_bg.png"))
    print("实际通道数", getattr(lod, "uv_channel_count", 1))


if __name__ == "__main__":
    main(sys.argv)
