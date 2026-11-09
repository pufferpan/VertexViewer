"""宣传图（网页版）：浅蓝底 + 多行斜置手机卡，整张铺满。

生成两样东西：
  work/promo_grid/index.html   —— 可直接双击打开的网页
  work/promo_grid/preview.png  —— 用 Chrome 无头截出来的同款图片

用法： python tools/make_poster_grid.py [宽 高]
"""
from __future__ import annotations

import glob
import os
import random
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTER = os.path.join(ROOT, "work", "poster")
OUTDIR = os.path.join(ROOT, "work", "promo_grid")
W = int(sys.argv[1]) if len(sys.argv) > 1 else 2083
H = int(sys.argv[2]) if len(sys.argv) > 2 else 1220

CHROME = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")

# 素材：work/promo_grid/tiles/ 下的竖版瓦片（界面裁屏 + 整枪渲染 + 渲染风格）
TILE_DIR = os.path.join(ROOT, "work", "promo_grid", "tiles")

CARD_W, CARD_H = 238, 488
GAP_X, GAP_Y = 320, 292
ANGLE = -19.0


def build_html() -> str:
    rng = random.Random(2026)
    tiles = sorted(
        os.path.relpath(p, os.path.join(ROOT, "work", "promo_grid"))
        for p in glob.glob(os.path.join(TILE_DIR, "tile_*.png"))
    )
    if not tiles:
        raise SystemExit("没有瓦片，先跑 tools/make_tiles.py 和 tools/poster_portrait.py")

    # 竖版瓦片按「界面 / 枪械 / 风格」轮流铺，避免同一屏连续出现
    ui = [t for t in tiles if any(k in t for k in ("gs_", "lib_", "tex_", "mat_"))]
    guns = [t for t in tiles if "tile_gun_" in t]
    styles = [t for t in tiles if "tile_style_" in t]
    pool = []
    while ui or guns or styles:
        for group in (guns, ui, styles, ui, guns, ui):
            if group:
                pool.append(group.pop(0))

    cards = []
    row = 0
    y = -150.0
    while y < H + 200:
        offset = (row % 2) * (GAP_X / 2)
        x = -170.0 - offset
        col = 0
        while x < W + 200:
            src = pool[(row * 3 + col) % len(pool)]
            cards.append({
                "src": src,
                "x": round(x + rng.uniform(-14, 14), 1),
                "y": round(y + rng.uniform(-12, 12), 1),
                "angle": round(ANGLE + rng.uniform(-2.6, 2.6), 2),
            })
            x += GAP_X
            col += 1
        y += GAP_Y
        row += 1

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>VertexViewer · 模型浏览器</title>
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{
    width: {W}px; height: {H}px; overflow: hidden;
    background:
      radial-gradient(1200px 700px at 18% 12%, #e8f4ff 0%, rgba(232,244,255,0) 60%),
      radial-gradient(1000px 620px at 82% 88%, #dcefff 0%, rgba(220,239,255,0) 62%),
      linear-gradient(160deg, #d7ecfb 0%, #c4e0f6 46%, #b9d9f3 100%);
    font-family: "Microsoft YaHei", system-ui, sans-serif;
  }}
  .stage {{ position: relative; width: {W}px; height: {H}px; }}
  .card {{
    position: absolute; width: {CARD_W}px; height: {CARD_H}px;
    border-radius: 34px; overflow: hidden;
    border: 7px solid rgba(255,255,255,.92);
    box-shadow: 0 22px 46px rgba(23,58,92,.26), 0 3px 0 rgba(255,255,255,.5) inset;
    background: #0f1216;
    transform-origin: 50% 50%;
  }}
  .card img {{ width: 100%; height: 100%; object-fit: cover; display: block;
               transform: scale(1.14); transform-origin: 50% 45%; }}
  .brand {{
    position: absolute; left: 54px; bottom: 46px; z-index: 40;
    padding: 26px 34px 22px; border-radius: 28px;
    background: rgba(240,249,255,.78);
    backdrop-filter: blur(6px);
    box-shadow: 0 18px 44px rgba(23,58,92,.22);
    border: 2px solid rgba(255,255,255,.9);
  }}
  .brand b {{ display: block; font-size: 92px; letter-spacing: -1px; line-height: .95;
              font-weight: 800; color: #12314c; }}
  .brand span {{ display: block; margin-top: 14px; font-size: 30px; font-weight: 700;
                 color: #1d4a6b; opacity: .92; }}
</style>
</head>
<body>
<div class="stage">
{os.linesep.join(
    f'  <div class="card" style="left:{c["x"]}px; top:{c["y"]}px; transform: rotate({c["angle"]}deg)">'
    f'<img src="{c["src"]}"></div>'
    for c in cards)}
  <div class="brand"><b>VertexViewer</b><span>模型浏览器</span></div>
</div>
</body>
</html>
"""
    return html


def shoot(out_png: str) -> None:
    html_path = os.path.join(OUTDIR, "index.html")
    url = "file:///" + html_path.replace("\\", "/")
    cmd = [
        CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1", f"--window-size={W},{H}",
        f"--screenshot={out_png}", "--virtual-time-budget=4000", url,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if not os.path.exists(out_png):
        raise SystemExit(f"截图失败：{res.stderr[-800:]}")


def main() -> None:
    os.makedirs(OUTDIR, exist_ok=True)
    html = build_html()
    path = os.path.join(OUTDIR, "index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("[grid] html ->", path)
    png = os.path.join(OUTDIR, "preview.png")
    shoot(png)
    print("[grid] png  ->", png)


if __name__ == "__main__":
    main()
