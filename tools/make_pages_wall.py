"""宣传网页：纯浅蓝底 + 斜置截图墙，整行从屏幕外一条条拉进来铺满。

用法： python tools/make_pages_wall.py
产物：
  work/promo_grid/wall/index.html   网页（图片用 ../pages/… 相对路径）
  work/promo_grid/wall/preview.png  静态成品图（1700×1000）

网址参数：
  默认        每行从左侧整条滑入，上一行落位后下一行才动（严格串行）
  #alt        偶数行从左、奇数行从右，交替进入
  #still      所有行瞬间到位（截图用）
  #loop       每行无限往左流（传送带式，一直动）
"""
from __future__ import annotations

import os
import subprocess

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(ROOT, "work", "promo_grid", "pages")
OUT = os.path.join(ROOT, "work", "promo_grid", "wall")
CHROME = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")

BG = "#cfe6fb"          # 纯浅蓝
TILT = -14              # 整墙倾斜角
ROWS = 7
PER_ROW = 7
CARD_W = 340            # 16:9 → 高 191
GAP = 14
SLIDE = 400             # 单行拉进来的时长（ms）
STAGGER = 420           # 行与行的间隔（ms，略大于 SLIDE → 严格一行接一行）
DIST = 106              # 起始位置：屏宽的多少倍以外（vw）
MARQUEE = 34            # 循环模式：一行跑完一圈的秒数

ITEMS = [
    "pg_gunsmith.png", "pg_library.png", "pg_textures.png", "pg_gunsmith2.png",
    "pg_materials.png", "pg_library_search.png", "pg_hero_M4A1.png", "pg_settings.png",
    "pg_library_blueprint.png", "pg_hero_AK12.png", "pg_hero_MP5A4.png", "pg_hero_neon.png",
]
TITLES = {
    "pg_gunsmith.png": "改枪台", "pg_library.png": "模型库", "pg_textures.png": "贴图",
    "pg_gunsmith2.png": "换枪 · HK416", "pg_materials.png": "材质",
    "pg_library_search.png": "中文名搜索", "pg_library_blueprint.png": "蓝图线框",
    "pg_hero_M4A1.png": "PBR 写实", "pg_settings.png": "设置",
    "pg_hero_AK12.png": "整枪渲染", "pg_hero_MP5A4.png": "换风格",
    "pg_hero_neon.png": "霓虹描边",
}


def build_html() -> str:
    tracks: list[str] = []
    for r in range(ROWS):
        cells = []
        for c in range(PER_ROW):
            name = ITEMS[(r * PER_ROW + c + r * 3) % len(ITEMS)]
            src = "../pages/" + name if os.path.exists(os.path.join(PAGES, name)) else ""
            cells.append(
                f'''        <figure class="card"><img src="{src}" alt="{TITLES.get(name, "")}">'''
                f'''<figcaption>{TITLES.get(name, "")}</figcaption></figure>'''
            )
        # 每行横向错开半张卡，墙才不呆板
        ox = -18 if r % 2 == 0 else -196
        body = "\n".join(cells)
        tracks.append(
            f'      <div class="track" style="--i:{r}; --ox:{ox}px">\n'
            f'        <div class="run">\n{body}\n        </div>\n'
            f'        <div class="run copy" aria-hidden="true">\n{body}\n        </div>\n'
            '      </div>'
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VertexViewer · 模型浏览器</title>
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; height: 100%; }}
  body {{ background: {BG}; overflow: hidden; font-family: "Microsoft YaHei", system-ui, sans-serif; }}

  .stage {{
    position: fixed; inset: -30vh -26vw;                     /* 转完不留边 */
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: {GAP}px;
    transform: rotate({TILT}deg);
    transform-origin: 50% 50%;
  }}

  /* 一条 = 一整行，整体平移，绝不拆开 */
  .track {{
    display: flex; width: max-content;
    animation: pullIn {SLIDE}ms cubic-bezier(.22,.9,.26,1) both;
    animation-delay: calc(var(--i) * {STAGGER}ms);
    will-change: transform;
  }}
  .run {{ display: flex; gap: {GAP}px; padding-right: {GAP}px; }}
  .run.copy {{ display: none; }}
  @keyframes pullIn {{
    from {{ transform: translateX(calc(var(--ox) - {DIST}vw)); }}
    to   {{ transform: translateX(var(--ox)); }}
  }}
  /* 交替模式：奇数行改从右边进来 */
  html.alt .track:nth-child(even) {{ animation-name: pullInRight; }}
  @keyframes pullInRight {{
    from {{ transform: translateX(calc(var(--ox) + {DIST}vw)); }}
    to   {{ transform: translateX(var(--ox)); }}
  }}
  html.still .track {{ animation: none !important; }}

  /* 循环模式：一行接一行无限往左流（像传送带） */
  html.loop .track {{ animation: none !important; }}
  html.loop .run {{ animation: marquee {MARQUEE}s linear infinite; }}
  html.loop .run.copy {{ display: flex; }}
  @keyframes marquee {{ from {{ transform: translateX(0) }} to {{ transform: translateX(-100%) }} }}

  .card {{
    position: relative; margin: 0; flex: 0 0 auto;
    width: {CARD_W}px; aspect-ratio: 16 / 9;
    border-radius: 14px; overflow: hidden; background: #fff;
    border: 5px solid #fff;
    box-shadow: 0 14px 28px rgba(19,58,92,.18), 0 2px 0 rgba(255,255,255,.8) inset;
  }}
  .card img {{ width: 100%; height: 100%; object-fit: cover; display: block; border-radius: 9px; }}
  figcaption {{
    position: absolute; left: 7px; bottom: 7px; padding: 3px 9px; border-radius: 999px;
    font-size: 11.5px; font-weight: 700; color: #12314c;
    background: rgba(255,255,255,.88); border: 1px solid rgba(255,255,255,.95);
  }}
</style>
</head>
<body>
  <div class="stage">
{chr(10).join(tracks)}
  </div>
<script>
  (function () {{
    var h = location.hash;
    if (h === '#still') document.documentElement.classList.add('still');
    if (h === '#alt') document.documentElement.classList.add('alt');
    if (h === '#loop') document.documentElement.classList.add('loop');
  }})();
</script>
</body>
</html>
"""


def shoot(html_path: str, out_png: str, w: int = 1700, h: int = 1000, hash_: str = "#still") -> None:
    url = "file:///" + html_path.replace("\\", "/") + hash_
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", f"--window-size={w},{h}",
                    f"--screenshot={out_png}", "--virtual-time-budget=6000", url],
                   capture_output=True, timeout=180)
    if not os.path.exists(out_png):
        raise SystemExit("截图失败")
    print("[wall] preview", out_png, Image.open(out_png).size)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(build_html())
    print("[wall] html ->", path)
    shoot(path, os.path.join(OUT, "preview.png"))


if __name__ == "__main__":
    main()
