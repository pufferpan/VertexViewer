"""生成 UV 调试贴图：R=U、G=V，带 1/8 网格 + 方位标记（TOP/BOT/LEFT/RIGHT）。

    python tools/make_uvdebug.py [输出png]

两侧对照都喂这张图：我们的 GL 渲染（tools/uv_compare.py）与 Blender
（tools/blender_render_obj.py 第三个参数）—— 对不上就说明 UV 链路有问题。
"""
import sys

from PIL import Image, ImageDraw

SIZE = 512
OUT = sys.argv[1] if len(sys.argv) > 1 else r"G:\xmcl-fetch\work\uvdebug.png"


def main():
    img = Image.new("RGB", (SIZE, SIZE))
    px = img.load()
    for y in range(SIZE):
        v = y / (SIZE - 1)                    # 行序自上而下 = v 从 0 到 1（UE 口径）
        for x in range(SIZE):
            u = x / (SIZE - 1)
            px[x, y] = (int(u * 255), int(v * 255), 64)
    dr = ImageDraw.Draw(img)
    step = SIZE / 8
    for i in range(9):
        p = i * step
        dr.line([(p, 0), (p, SIZE)], fill=(0, 0, 0), width=2)
        dr.line([(0, p), (SIZE, p)], fill=(0, 0, 0), width=2)
    # 方位标记：v≈0 一侧是贴图的「上」
    dr.rectangle([8, 8, 120, 40], fill=(255, 255, 255))
    dr.text((20, 16), "TOP v=0", fill=(0, 0, 0))
    dr.rectangle([8, SIZE - 40, 120, SIZE - 8], fill=(0, 0, 0))
    dr.text((20, SIZE - 32), "BOT v=1", fill=(255, 255, 255))
    dr.rectangle([SIZE - 130, SIZE // 2 - 16, SIZE - 8, SIZE // 2 + 16], fill=(255, 255, 255))
    dr.text((SIZE - 120, SIZE // 2 - 8), "RIGHT u=1", fill=(0, 0, 0))
    dr.rectangle([8, SIZE // 2 - 16, 130, SIZE // 2 + 16], fill=(0, 0, 0))
    dr.text((20, SIZE // 2 - 8), "LEFT u=0", fill=(255, 255, 255))
    img.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
