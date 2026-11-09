"""宣传图合成：暖黄底 + 斜置圆角卡片网格（参考手机主题宣传图的排版语言）。

用法： python tools/make_poster.py [输出png] [宽 高]
素材： work/poster/ui_*.png、gun_*.png、style_*.png
"""
from __future__ import annotations

import os
import random
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTER = os.path.join(ROOT, "work", "poster")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "work", "promo_vertexviewer.png")
W = int(sys.argv[2]) if len(sys.argv) > 2 else 2083
H = int(sys.argv[3]) if len(sys.argv) > 3 else 1220

AMBER_TOP = (249, 206, 128)
AMBER_BOT = (231, 160, 62)
INK = (44, 27, 12)
CREAM = (255, 247, 228)

FONT_CN = r"C:\Windows\Fonts\msyhbd.ttc"
FONT_CN_R = r"C:\Windows\Fonts\msyh.ttc"
FONT_EN = os.path.join(ROOT, "assets", "fonts", "VertexViewer-MiSans-Bold.ttf")


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def background() -> Image.Image:
    base = Image.new("RGB", (W, H), AMBER_TOP)
    grad = Image.new("L", (1, H))
    for y in range(H):
        grad.putpixel((0, y), int(255 * ((y / max(1, H - 1)) ** 0.9)))
    base = Image.composite(Image.new("RGB", (W, H), AMBER_BOT), base, grad.resize((W, H)))

    glow = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-W * 0.20, -H * 0.40, W * 0.70, H * 0.70), fill=120)
    gd.ellipse((W * 0.30, H * 0.20, W * 1.45, H * 1.45), fill=95)
    glow = glow.filter(ImageFilter.GaussianBlur(W * 0.10))
    base = Image.composite(Image.new("RGB", (W, H), CREAM), base, glow.point(lambda v: int(v * 0.50)))

    vig = Image.new("L", (W, H), 0)
    vd = ImageDraw.Draw(vig)
    vd.ellipse((-W * 0.22, -H * 0.32, W * 1.22, H * 1.32), fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(W * 0.05)).point(lambda v: 255 - v)
    base = Image.composite(Image.new("RGB", (W, H), (146, 92, 26)), base, vig.point(lambda v: int(v * 0.32)))
    return base.convert("RGBA")


def rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def warm(img: Image.Image, amount: float = 0.07) -> Image.Image:
    """给冷色底素材刷一层暖光，和暖黄背景统一。"""
    tint = Image.new("RGB", img.size, (255, 206, 150))
    blended = Image.blend(img.convert("RGB"), tint, amount)
    out = blended.convert("RGBA")
    out.putalpha(img.getchannel("A"))
    return out


def card(path: str, w: int, h: int, radius: int = 24, border: int = 5,
         zoom: float = 1.0, focus: tuple[float, float] = (0.5, 0.5)) -> Image.Image:
    img = Image.open(path).convert("RGB")
    if zoom != 1.0:
        cw, ch = img.width / zoom, img.height / zoom
        cx, cy = img.width * focus[0], img.height * focus[1]
        left = min(max(0, int(cx - cw / 2)), max(0, img.width - int(cw)))
        top = min(max(0, int(cy - ch / 2)), max(0, img.height - int(ch)))
        img = img.crop((left, top, left + int(cw), top + int(ch)))
    scale = max(w / img.width, h / img.height)
    img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
    left = (img.width - w) // 2
    top = (img.height - h) // 2
    img = img.crop((left, top, left + w, top + h))
    body = rounded(img, radius)
    ring = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(ring).rounded_rectangle((0, 0, w - 1, h - 1), radius,
                                           outline=(255, 251, 240, 238), width=border)
    return Image.alpha_composite(body, ring)


def drop_shadow(tile: Image.Image, blur: int = 24, opacity: int = 120) -> Image.Image:
    pad = blur * 3
    sh = Image.new("RGBA", (tile.width + pad * 2, tile.height + pad * 2), (0, 0, 0, 0))
    alpha = tile.getchannel("A")
    solid = Image.new("RGBA", tile.size, (58, 32, 8, opacity))
    solid.putalpha(alpha.point(lambda v: int(v * opacity / 255)))
    sh.paste(solid, (pad, pad), solid)
    return sh.filter(ImageFilter.GaussianBlur(blur))


def place(canvas: Image.Image, tile: Image.Image, cx: int, cy: int, angle: float,
          blur: int = 24, opacity: int = 105) -> None:
    rot = tile.rotate(angle, resample=Image.BICUBIC, expand=True)
    sh = drop_shadow(rot, blur, opacity)
    canvas.alpha_composite(sh, (int(cx - sh.width / 2), int(cy - sh.height / 2 + blur * 0.45)))
    canvas.alpha_composite(rot, (int(cx - rot.width / 2), int(cy - rot.height / 2)))


def main() -> None:
    canvas = background()
    rng = random.Random(11)

    def p(name: str) -> str:
        return os.path.join(POSTER, name)

    # (文件, cx, cy, 宽, 高, 角度, zoom, focus)
    plan = [
        # 后排（出血、压边）
        (p("gun_HK416.png"), int(W * 0.15), int(H * 0.13), 470, 300, -8.5, 2.15, (0.5, 0.5)),
        (p("style_blueprint.png"), int(W * 0.99), int(H * 0.13), 430, 268, -10.0, 2.05, (0.5, 0.5)),
        (p("ui_texture.png"), int(W * 0.115), int(H * 0.32), 430, 266, 8.0, 1.75, (0.70, 0.50)),
        (p("style_neon.png"), int(W * 0.085), int(H * 0.60), 400, 250, 12.0, 2.05, (0.5, 0.5)),
        (p("style_clay.png"), int(W * 0.99), int(H * 0.92), 430, 268, 9.0, 2.05, (0.5, 0.5)),
        # 中间层
        (p("gun_AK12.png"), int(W * 0.35), int(H * 0.13), 470, 292, 5.0, 2.15, (0.5, 0.5)),
        (p("gun_SCAR-H.png"), int(W * 0.93), int(H * 0.30), 470, 292, 6.0, 2.15, (0.5, 0.5)),
        (p("gun_M4A1.png"), int(W * 0.97), int(H * 0.62), 460, 286, 7.5, 2.15, (0.5, 0.5)),
        (p("gun_MP5A4.png"), int(W * 0.47), int(H * 0.90), 480, 296, -6.0, 2.1, (0.5, 0.5)),
        (p("gun_SG553.png"), int(W * 0.74), int(H * 0.86), 470, 292, 5.0, 2.15, (0.5, 0.5)),
        # 主角
        (p("ui_gunsmith.png"), int(W * 0.60), int(H * 0.42), 980, 612, -2.5, 1.0, (0.50, 0.47)),
    ]

    for i, (path, cx, cy, w, h, ang, zoom, focus) in enumerate(plan):
        if not os.path.exists(path):
            continue
        tile = card(path, w, h, radius=24, border=5, zoom=zoom, focus=focus)
        if not os.path.basename(path).startswith("ui_"):
            tile = warm(tile, 0.05)
        place(canvas, tile, cx, cy, ang + rng.uniform(-0.7, 0.7),
              blur=30 if i == len(plan) - 1 else 22,
              opacity=118 if i == len(plan) - 1 else 92)

    draw = ImageDraw.Draw(canvas)
    title_f = font(FONT_EN, 104)
    sub_f = font(FONT_CN, 36)
    tag_f = font(FONT_CN, 27)
    x0, y0 = int(W * 0.045), int(H * 0.775)

    # 左下角加一层奶油色柔光，保证字压得住底
    halo = Image.new("L", (W, H), 0)
    ImageDraw.Draw(halo).ellipse((x0 - W * 0.10, y0 - H * 0.16, x0 + W * 0.34, y0 + H * 0.30), fill=150)
    halo = halo.filter(ImageFilter.GaussianBlur(W * 0.045))
    canvas = Image.composite(Image.new("RGBA", (W, H), CREAM + (255,)), canvas, halo.point(lambda v: int(v * 0.72)))
    draw = ImageDraw.Draw(canvas)

    draw.text((x0 + 4, y0 + 8), "VertexViewer", font=title_f, fill=(126, 72, 16, 80))
    draw.text((x0, y0), "VertexViewer", font=title_f, fill=INK)
    draw.text((x0 + 8, y0 + 124), "模型浏览器", font=sub_f, fill=(66, 40, 14, 240))

    badges = ["改枪台 · 官方挂点装配", "937,088 个资产", "PBR 写实渲染", "OBJ 导出"]
    bx, by = x0 + 8, y0 + 184
    for text in badges:
        tw = draw.textlength(text, font=tag_f)
        w_card, h_card = int(tw) + 36, 48
        chip = Image.new("RGBA", (w_card, h_card), (0, 0, 0, 0))
        cd = ImageDraw.Draw(chip)
        cd.rounded_rectangle((0, 0, w_card - 1, h_card - 1), 24, fill=(40, 25, 10, 212))
        cd.rounded_rectangle((0, 0, w_card - 1, h_card - 1), 24, outline=(255, 236, 200, 110), width=2)
        cd.text((18, 8), text, font=tag_f, fill=(255, 241, 216, 255))
        canvas.alpha_composite(chip, (bx, by))
        bx += w_card + 14

    side_f = font(FONT_CN_R, 22)
    strip = Image.new("RGBA", (int(H * 0.26), 26), (0, 0, 0, 0))
    ImageDraw.Draw(strip).text((2, 0), "MODEL · TEXTURE · GUNSMITH", font=side_f,
                               fill=(70, 42, 12, 145))
    strip = strip.rotate(-90, expand=True)
    canvas.alpha_composite(strip, (int(W * 0.972), int(H * 0.34)))

    noise = Image.effect_noise((W, H), 12).convert("L").point(lambda v: int(abs(v - 128) * 0.30))
    canvas.alpha_composite(Image.merge("RGBA", (noise, noise, noise, noise.point(lambda v: int(v * 0.45)))))

    canvas.convert("RGB").save(OUT, quality=95)
    print("[poster] saved", OUT, canvas.size)


if __name__ == "__main__":
    main()
