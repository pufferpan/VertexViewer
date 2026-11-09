"""把宣传长页打成可直接双击打开的 zip（自带 pages/ 图片，路径改成本地相对路径）。

图片会顺手压一遍：PNG → JPEG（默认宽 1280、质量 72），页面里的引用也一起改成 .jpg。

用法： python tools/make_site_zip.py [--width 1280] [--quality 72]
产物： work/VertexViewer-宣传页.zip
      work/promo_grid/release/VertexViewer-宣传页/{index.html, pages/*.jpg, 使用说明.txt}
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import zipfile

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "work", "promo_grid", "scroll", "index.html")
PAGES = os.path.join(ROOT, "work", "promo_grid", "pages")
RELEASE = os.path.join(ROOT, "work", "promo_grid", "release", "VertexViewer-宣传页")
ZIP_PATH = os.path.join(ROOT, "work", "VertexViewer-宣传页-压缩版.zip")

README = """VertexViewer · 模型浏览器 —— 宣传页
========================================

打开方式
  双击 index.html（Chrome / Edge / Firefox 都行，不需要联网、不需要装任何东西）。

页面上有什么
  1. 首屏：7 行截图同时从左右屏幕外推进来，落位后继续缓慢无限滚动。
  2. 往下滚：「把整座兵工厂装进一个窗口」+ 四个数字卡，逐块上浮淡入。
  3. 功能卡：模型库 / 搜索 / 贴图三通道 / 材质继承 / 改枪挂点 / 六种渲染风格。
  4. 藏品：钥匙卡、藏品两张大图。

小提示
  · 整页底色是 #2060A0，图片都在 pages/ 里，改样式直接编辑 index.html 顶部的 <style>。
  · 截图是压过的 JPEG（宽 {width}px、质量 {quality}），想换高清版就把原图放回去、把 .jpg 改回 .png。
  · 想静态看落位效果：在地址后面加 #still
  · 想定格在某一毫秒：加 #freeze=40000（40 秒那一刻）

文件
  index.html      页面本体（样式和脚本都内联在里面）
  pages/*.jpg     页面用到的 16:9 截图（JPEG，已压缩）
"""


def _compress(src: str, dst: str, width: int, quality: int) -> None:
    """PNG 截图 → 指定宽度的 JPEG（等比缩放，Lanczos）。"""
    with Image.open(src) as im:
        im = im.convert("RGB")
        if width and im.width > width:
            height = round(im.height * width / im.width)
            im = im.resize((width, height), Image.LANCZOS)
        im.save(dst, "JPEG", quality=quality, optimize=True, progressive=True)


def main() -> None:
    global ZIP_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, default=1280, help="JPEG 目标宽度（0 = 不缩放）")
    ap.add_argument("--quality", type=int, default=72, help="JPEG 质量 1~95")
    args = ap.parse_args()

    if not os.path.exists(SRC):
        raise SystemExit(f"缺少页面：{SRC}")

    html = open(SRC, encoding="utf-8").read()
    used = sorted(set(re.findall(r"pages/([A-Za-z0-9_\-]+)\.png", html)))
    html = html.replace("../pages/", "pages/")
    for name in used:                                    # 引用改成 .jpg
        html = html.replace(f"pages/{name}.png", f"pages/{name}.jpg")

    if os.path.isdir(RELEASE):
        shutil.rmtree(RELEASE)
    os.makedirs(os.path.join(RELEASE, "pages"), exist_ok=True)

    with open(os.path.join(RELEASE, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)
    with open(os.path.join(RELEASE, "使用说明.txt"), "w", encoding="utf-8") as fh:
        fh.write(README.format(width=args.width or "原始", quality=args.quality))

    missing = []
    raw_total = jpg_total = 0
    for name in used:
        src = os.path.join(PAGES, f"{name}.png")
        if not os.path.exists(src):
            missing.append(name)
            continue
        dst = os.path.join(RELEASE, "pages", f"{name}.jpg")
        _compress(src, dst, args.width, args.quality)
        raw_total += os.path.getsize(src)
        jpg_total += os.path.getsize(dst)

    if missing:
        print("[zip] 缺图:", ", ".join(missing))

    if os.path.exists(ZIP_PATH):
        try:
            os.remove(ZIP_PATH)
        except PermissionError:                       # 旧包被别的程序占着
            ZIP_PATH = ZIP_PATH.replace(".zip", "-lite.zip")
            print("[zip] 旧包被占用，改写到", os.path.basename(ZIP_PATH))
            if os.path.exists(ZIP_PATH):
                os.remove(ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for base, _dirs, files in os.walk(RELEASE):
            for f in sorted(files):
                full = os.path.join(base, f)
                rel = os.path.relpath(full, os.path.dirname(RELEASE))
                zf.write(full, rel)

    size = os.path.getsize(ZIP_PATH) / 1024 / 1024
    print(f"[zip] 页面用图 {len(used)} 张：{raw_total / 1048576:.2f} MB PNG "
          f"→ {jpg_total / 1048576:.2f} MB JPEG（宽 {args.width} / 质量 {args.quality}）")
    print(f"[zip] {ZIP_PATH}  ({size:.1f} MB)")


if __name__ == "__main__":
    main()
