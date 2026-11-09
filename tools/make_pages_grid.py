"""宣传网页：浅蓝底 + 4 行 × 3 列 16:9 截图，打开时一行一行浮现（整屏可见，不用滚）。

用法： python tools/make_pages_grid.py
产物：
  work/promo_grid/site/index.html   网页（图片用 ../pages/… 相对路径）
  work/promo_grid/site/preview.png  整屏截图的图片版
"""
from __future__ import annotations

import os
import subprocess

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(ROOT, "work", "promo_grid", "pages")
SITE = os.path.join(ROOT, "work", "promo_grid", "site")
CHROME = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")

# (文件, 标题)　—— 12 张 = 4 行 × 3 列
ITEMS = [
    ("pg_gunsmith.png", "改枪台"),
    ("pg_library.png", "模型库"),
    ("pg_textures.png", "贴图"),
    ("pg_gunsmith2.png", "换枪 · HK416"),
    ("pg_materials.png", "材质"),
    ("pg_library_search.png", "中文名搜索"),
    ("pg_library_blueprint.png", "蓝图线框"),
    ("pg_hero_M4A1.png", "PBR 写实"),
    ("pg_settings.png", "设置"),
    ("pg_hero_AK12.png", "整枪渲染"),
    ("pg_hero_MP5A4.png", "换风格"),
    ("pg_hero_neon.png", "霓虹描边"),
]

COLS = 3
ROWS = 4
GAP = 18
ROW_DELAY = 0.30      # 每行延迟（秒）
FADE = 0.62           # 每行淡入时长（秒）


def build_html() -> str:
    rows: list[str] = []
    for i in range(0, len(ITEMS), COLS):
        chunk = ITEMS[i:i + COLS]
        cells = []
        for name, title in chunk:
            src = "../pages/" + name if os.path.exists(os.path.join(PAGES, name)) else ""
            cells.append(
                f'''      <figure class="card">
        <img src="{src}" alt="{title}">
        <figcaption>{title}</figcaption>
      </figure>'''
            )
        rows.append('    <section class="row">\n' + "\n".join(cells) + "\n    </section>")

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VertexViewer · 模型浏览器</title>
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; height: 100%; }}
  body {{
    height: 100vh; overflow: hidden;
    background:
      radial-gradient(1100px 620px at 12% 4%, #eaf6ff 0%, rgba(234,246,255,0) 62%),
      radial-gradient(900px 560px at 88% 96%, #dcefff 0%, rgba(220,239,255,0) 60%),
      linear-gradient(165deg, #d9edfc 0%, #c8e2f7 48%, #bcdbf4 100%);
    font-family: "Microsoft YaHei", system-ui, -apple-system, sans-serif;
    color: #123049;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 20px;
  }}
  /* 一行卡片的宽度由可用高度反推：4 行刚好塞满一屏，不出现滚动条 */
  :root {{
    --gap: {GAP}px;
    --ch: clamp(120px, calc((100vh - 168px - {ROWS - 1} * var(--gap)) / {ROWS}), 268px);
  }}
  header {{
    width: min(1560px, 94vw); display: flex; align-items: flex-end; justify-content: space-between;
    gap: 24px; padding: 0 4px; animation: fadeUp .6s cubic-bezier(.22,.8,.3,1) both;
  }}
  header h1 {{ margin: 0; font-size: 40px; letter-spacing: -.5px; font-weight: 800; line-height: 1; }}
  header p {{ margin: 9px 0 0; font-size: 15px; color: #1d4a6b; opacity: .84; }}
  header .tag {{
    font-size: 13px; padding: 8px 15px; border-radius: 999px; white-space: nowrap;
    background: rgba(255,255,255,.75); border: 1px solid rgba(255,255,255,.95);
    box-shadow: 0 8px 22px rgba(23,58,92,.10);
  }}
  .grid {{ display: flex; flex-direction: column; gap: var(--gap); align-items: center; }}
  .row {{
    display: grid; grid-auto-flow: column; grid-auto-columns: calc(var(--ch) * 16 / 9);
    gap: var(--gap);
    opacity: 0; transform: translateY(42px);
    transition: opacity {FADE}s cubic-bezier(.22,.8,.3,1), transform {FADE}s cubic-bezier(.22,.8,.3,1);
  }}
  .row.in {{ opacity: 1; transform: none; }}
  html.still .row, html.still header {{ transition: none !important; animation: none !important; }}
  .card {{
    position: relative; margin: 0; height: var(--ch); border-radius: 14px; overflow: hidden;
    background: #fff; border: 1px solid rgba(255,255,255,.95);
    box-shadow: 0 16px 34px rgba(23,58,92,.18), 0 2px 0 rgba(255,255,255,.7) inset;
    transition: transform .25s ease, box-shadow .25s ease;
  }}
  .card:hover {{ transform: translateY(-5px) scale(1.015); box-shadow: 0 24px 46px rgba(23,58,92,.26); }}
  .card img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
  figcaption {{
    position: absolute; left: 9px; bottom: 9px; padding: 5px 11px; border-radius: 999px;
    font-size: 12.5px; font-weight: 700; color: #12314c;
    background: rgba(255,255,255,.82); backdrop-filter: blur(4px);
    border: 1px solid rgba(255,255,255,.9); box-shadow: 0 4px 12px rgba(23,58,92,.14);
  }}
  @keyframes fadeUp {{ from {{ opacity: 0; transform: translateY(14px); }} to {{ opacity: 1; transform: none; }} }}
  /* 窄屏/矮屏退化：允许滚动，卡片按宽度铺 */
  @media (max-width: 1100px) {{
    body {{ height: auto; min-height: 100vh; overflow: auto; padding: 28px 0; justify-content: flex-start; }}
    :root {{ --ch: auto; }}
    .row {{ grid-auto-columns: auto; grid-template-columns: repeat(2, minmax(0, 1fr)); grid-auto-flow: row; }}
    .card {{ height: auto; aspect-ratio: 16 / 9; }}
  }}
</style>
</head>
<body>
  <header>
    <div>
      <h1>VertexViewer</h1>
      <p>模型浏览器 ｜ 模型库 / 贴图 / 材质 / 改枪 / 导出，一个窗口全看完</p>
    </div>
    <div class="tag">1.0+2026-10-30.1450</div>
  </header>
  <main class="grid">
{chr(10).join(rows)}
  </main>
<script>
  // 一行一行出现：第 n 行在 {int(160)}ms + n*{int(ROW_DELAY * 1000)}ms 时浮上来
  (function () {{
    var rows = Array.prototype.slice.call(document.querySelectorAll('.row'));
    if (location.hash === '#still') {{                    // 截图/静态用：一次全出来
      document.documentElement.classList.add('still');
      rows.forEach(function (row) {{ row.classList.add('in'); }});
      return;
    }}
    rows.forEach(function (row, i) {{
      setTimeout(function () {{ row.classList.add('in'); }}, 160 + i * {int(ROW_DELAY * 1000)});
    }});
  }})();
</script>
</body>
</html>
"""


def shoot(html_path: str, out_png: str, w: int = 1700, h: int = 1000) -> None:
    url = "file:///" + html_path.replace("\\", "/") + "#still"
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           "--force-device-scale-factor=1", f"--window-size={w},{h}",
           f"--screenshot={out_png}", "--virtual-time-budget=6000", url]
    subprocess.run(cmd, capture_output=True, timeout=180)
    if not os.path.exists(out_png):
        raise SystemExit("截图失败")
    print("[site] preview", out_png, Image.open(out_png).size)


def main() -> None:
    os.makedirs(SITE, exist_ok=True)
    path = os.path.join(SITE, "index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(build_html())
    print("[site] html ->", path)
    missing = [n for n, _ in ITEMS if not os.path.exists(os.path.join(PAGES, n))]
    if missing:
        print("[site] 缺图:", missing)
    shoot(path, os.path.join(SITE, "preview.png"))


if __name__ == "__main__":
    main()
