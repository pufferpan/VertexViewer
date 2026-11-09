"""把截图/渲染图做成竖版「手机屏」瓦片（等比缩放 + 用自身底色补边，不裁内容）。

用法： python tools/make_tiles.py
产物： work/promo_grid/tiles/tile_*.png（560×1140，竖版）
"""
from __future__ import annotations

import glob
import os

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTER = os.path.join(ROOT, "work", "poster")
OUT = os.path.join(ROOT, "work", "promo_grid", "tiles")
TW, TH = 560, 1140

# 界面截图里「像一屏」的区域（源图 1500×940 像素坐标）
CROPS = [
    ("ui_gunsmith.png", (250, 60, 750, 900), "gs_panel"),
    ("ui_gunsmith.png", (1262, 78, 1500, 878), "gs_params"),
    ("ui_library.png", (255, 120, 635, 900), "lib_cards"),
    ("ui_texture.png", (255, 130, 588, 820), "tex_thumbs"),
    ("ui_texture.png", (790, 180, 1440, 830), "tex_preview"),
    ("ui_material.png", (255, 90, 850, 700), "mat_rows"),
]

# 整张渲染图（枪 / 风格），保留它们的深色底
RENDERS = ["gun_M4A1", "gun_HK416", "gun_AK12", "gun_SCAR-H", "gun_MP5A4",
           "gun_SG553", "gun_AK74", "style_neon", "style_blueprint",
           "style_clay", "style_toon", "style_posterize"]


def edge_color(img: Image.Image) -> tuple[int, int, int]:
    """取图片四条边的中位颜色，用来补边（看不出来接缝）。"""
    w, h = img.size
    px = []
    for x in range(0, w, max(1, w // 24)):
        px.append(img.getpixel((x, 0)))
        px.append(img.getpixel((x, h - 1)))
    for y in range(0, h, max(1, h // 24)):
        px.append(img.getpixel((0, y)))
        px.append(img.getpixel((w - 1, y)))
    px = [p[:3] for p in px if isinstance(p, tuple)]
    if not px:
        return (16, 18, 22)
    return tuple(sorted(c[i] for c in px)[len(px) // 2] for i in range(3))  # type: ignore[return-value]


def to_tile(img: Image.Image) -> Image.Image:
    w, h = img.size
    scale = min(TW / w, TH / h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    # 缩到刚好铺满一边后，再放大一点点填掉留白（最多 8%），避免大片死边
    grow = min(TW / nw, TH / nh, 1.08)
    nw, nh = int(nw * grow), int(nh * grow)
    small = img.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (TW, TH), edge_color(img))
    canvas.paste(small, ((TW - nw) // 2, (TH - nh) // 2))
    return canvas


def render_tile(img: Image.Image, angle: float = 24.0) -> Image.Image:
    """渲染图：先裁到枪身附近，再整体旋转，铺满竖卡（产品图那种斜着的构图）。"""
    w, h = img.size
    crop = img.crop((int(w * 0.08), int(h * 0.22), int(w * 0.92), int(h * 0.78)))
    canvas = Image.new("RGB", (TW, TH), edge_color(img))
    scale = (TW * 1.42) / crop.width
    crop = crop.resize((int(crop.width * scale), int(crop.height * scale)), Image.LANCZOS)
    rot = crop.rotate(angle, resample=Image.BICUBIC, expand=True)
    mask = Image.new("L", rot.size, 0)
    d = ImageDraw.Draw(mask)
    pad = int(min(rot.size) * 0.10)
    d.rounded_rectangle((pad, pad, rot.size[0] - pad, rot.size[1] - pad), 40, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(min(rot.size) * 0.05))
    canvas.paste(rot, ((TW - rot.width) // 2, (TH - rot.height) // 2), mask)
    return canvas


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    for name, rect, out in CROPS:
        src = os.path.join(POSTER, name)
        if not os.path.exists(src):
            print("[tiles] skip (missing)", name)
            continue
        img = Image.open(src).convert("RGB")
        left, top, right, bottom = rect
        crop = img.crop((max(0, left), max(0, top), min(img.width, right), min(img.height, bottom)))
        path = os.path.join(OUT, f"tile_{out}.png")
        to_tile(crop).save(path)
        print("[tiles] saved", path)

    for stem in RENDERS:
        src = os.path.join(POSTER, stem + ".png")
        if not os.path.exists(src):
            continue
        img = Image.open(src).convert("RGB")
        path = os.path.join(OUT, f"tile_{stem}.png")
        render_tile(img).save(path)
        print("[tiles] saved", path)

    print("[tiles] total", len(glob.glob(os.path.join(OUT, "tile_*.png"))))


if __name__ == "__main__":
    main()
