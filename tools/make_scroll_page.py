"""宣传长页 v2：深蓝 #2060A0 + 所有行「同时」从屏幕外推进来 + 向下滚动逐块浮现。

用法： python tools/make_scroll_page.py
产物：
  work/promo_grid/scroll/index.html      网页
  work/promo_grid/scroll/preview_*.png   整页切段的静态图
  work/promo_grid/scroll/preview.png     所有段拼起来的长图

网址参数：
  #still  首屏墙不飞入、所有内容直接显形（截图用）
  #cap    首屏固定 1000px 高，方便一次拍整页
"""
from __future__ import annotations

import os
import subprocess

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(ROOT, "work", "promo_grid", "pages")
OUT = os.path.join(ROOT, "work", "promo_grid", "scroll")
CHROME = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")

BG = "#2060A0"
INK = "#f2f8ff"
TILT = -14
ROWS = 7
PER_ROW = 7
CARD_W = 340
GAP = 14
SLIDE = 1150         # 整墙飞入时长（所有行同一时刻开始）
DIST = 168           # 从屏幕外多远处开始（vw），保证整行完全在屏外
MARQUEE = 118        # 落位后每行缓慢平移一圈的秒数（越大越慢）
HERO_FADE = "min(24vh, 260px)"   # 首屏上下两端渐隐的高度（长图截图时也稳定）

HERO = [
    "pg_gunsmith.png", "pg_library.png", "pg_textures.png", "pg_gunsmith2.png",
    "pg_materials.png", "pg_library_search.png", "pg_hero_M4A1.png", "pg_settings.png",
    "pg_library_blueprint.png", "pg_hero_AK12.png", "pg_hero_MP5A4.png", "pg_hero_neon.png",
    "pg_keycard.png", "pg_collectible.png",
]

FEATURES = [
    ("pg_library.png", "937,088 个资产", "模型库按中文名、资产名或路径搜，卡片直接点开看，不用记 UE 那一长串路径。"),
    ("pg_library_search.png", "一个框搜全部", "搜「M4A1」「护木」「背包」都行；13 个分类一键筛，钥匙卡、藏品、容器都在里面。"),
    ("pg_textures.png", "贴图三通道", "BaseColor / Normal / MRA 逐张拆出来，2048 起步的原图，右键就能存。"),
    ("pg_materials.png", "材质继承链", "父材质、金属度、粗糙度、贴图槽位一屏看完，还能整体覆盖后重渲染。"),
    ("pg_gunsmith.png", "改枪台 · 官方挂点", "读游戏里的挂点表和预设树，配件插哪个 socket 就摆哪里，和游戏内一致。"),
    ("pg_library_blueprint.png", "六种渲染风格", "PBR 写实、蓝图线框、霓虹描边、粘土、卡通、海报化，一键切换。"),
]

SHOWCASE = [
    ("pg_keycard.png", "钥匙卡", "卡面、条形码、磁条，连卡套的皮革纹理都能放大看清——11 张全在这里。"),
    ("pg_collectible.png", "藏品", "电子元件、电池、主板、手办摆设，240 个藏品模型，摆在桌上是什么样就是什么样。"),
]


def cards_for_row(r: int) -> str:
    """一整行卡片，内容复制 3 份（后两份 aria-hidden）；滚过一个副本宽度后无缝接回。"""
    cells = []
    for copy_index in range(3):
        hide = ' aria-hidden="true"' if copy_index else ""
        for c in range(PER_ROW):
            name = HERO[(r * PER_ROW + c + r * 3) % len(HERO)]
            if not os.path.exists(os.path.join(PAGES, name)):
                continue
            cells.append(f'<figure class="card"{hide}><img src="../pages/{name}" alt=""></figure>')
    return "\n".join(cells)


def build_html() -> str:
    tracks = []
    for r in range(ROWS):
        ox = -18 if r % 2 == 0 else -196
        side = "fromLeft" if r % 2 == 0 else "fromRight"
        crawler = "crawlLeft" if r % 2 == 0 else "crawlRight"
        dur = MARQUEE + (r % 3) * 9          # 每行速度略不同，避免一起动像机器
        tracks.append(
            f'''      <div class="track {side}" style="--ox:{ox}px">
        <div class="run {crawler}" style="--dur:{dur}s">
        {cards_for_row(r)}
        </div>
      </div>'''
        )

    feats = "\n".join(
        f'''      <article class="tile reveal" style="--i:{i}">
        <div class="shot"><img src="../pages/{src}" alt=""></div>
        <h3>{title}</h3>
        <p>{text}</p>
      </article>'''
        for i, (src, title, text) in enumerate(FEATURES)
    )

    show = "\n".join(
        f'''      <figure class="show reveal" style="--i:{i}">
        <img src="../pages/{src}" alt="">
        <figcaption><b>{title}</b><span>{text}</span></figcaption>
      </figure>'''
        for i, (src, title, text) in enumerate(SHOWCASE)
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VertexViewer · 模型浏览器</title>
<style>
  * {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; background: {BG}; }}
  html.still {{ scroll-behavior: auto; }}
  html.cap .hero {{ height: 1000px; }}
  body {{
    margin: 0; color: {INK};
    background: {BG};
    font-family: "Microsoft YaHei", system-ui, -apple-system, sans-serif;
    -webkit-font-smoothing: antialiased;
  }}

  /* ---------------- 首屏：整墙同时推入 ---------------- */
  .hero {{ position: relative; height: 100vh; overflow: hidden; background: {BG}; }}
  .stage {{
    position: absolute; inset: -320px -30vw;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: {GAP}px; transform: rotate({TILT}deg) scale(1.04);
  }}
  .track {{
    display: flex; width: max-content;
    animation-duration: {SLIDE}ms;
    animation-timing-function: cubic-bezier(.42,.06,.18,1);
    animation-fill-mode: both;
    will-change: transform, opacity;
  }}
  .track.fromLeft  {{ animation-name: fromLeft; }}
  .track.fromRight {{ animation-name: fromRight; }}
  @keyframes fromLeft {{
    0%   {{ transform: translateX(calc(var(--ox) - {DIST}vw)); opacity: 0 }}
    12%  {{ opacity: 1 }}
    100% {{ transform: translateX(var(--ox)); opacity: 1 }}
  }}
  @keyframes fromRight {{
    0%   {{ transform: translateX(calc(var(--ox) + {DIST}vw)); opacity: 0 }}
    12%  {{ opacity: 1 }}
    100% {{ transform: translateX(var(--ox)); opacity: 1 }}
  }}
  /* 落位后继续缓慢平移：两份内容滚动 -50% 正好接回开头 */
  .run {{ display: flex; gap: 0; will-change: transform; }}
  .run.crawlLeft  {{ animation: crawlLeft  var(--dur, 120s) linear infinite; }}
  .run.crawlRight {{ animation: crawlRight var(--dur, 120s) linear infinite; }}
  @keyframes crawlLeft  {{ from {{ transform: translateX(0) }} to {{ transform: translateX(calc(-{PER_ROW} * ({CARD_W}px + {GAP}px))) }} }}
  @keyframes crawlRight {{ from {{ transform: translateX(calc(-{PER_ROW} * ({CARD_W}px + {GAP}px))) }} to {{ transform: translateX(0) }} }}
  html.still .track, html.still .run {{ animation: none !important; }}

  /* 首屏上下两端渐隐：进出画面都是渐变，不是硬切 */
  .hero::before, .hero::after {{
    content: ""; position: absolute; left: 0; right: 0; z-index: 3; pointer-events: none;
  }}
  .hero::before {{
    top: 0; height: {HERO_FADE};
    background: linear-gradient(to bottom, {BG} 6%, rgba(32,96,160,.72) 52%, rgba(32,96,160,0) 100%);
  }}
  .hero::after {{
    bottom: 0; height: {HERO_FADE};
    background: linear-gradient(to top, {BG} 8%, rgba(32,96,160,.72) 54%, rgba(32,96,160,0) 100%);
  }}
  .hero-side {{ position: absolute; inset: 0; z-index: 3; pointer-events: none;
    background:
      linear-gradient(to right, {BG} 0%, rgba(32,96,160,0) 12%),
      linear-gradient(to left, {BG} 0%, rgba(32,96,160,0) 12%); }}

  .card {{ margin: 0 {GAP}px 0 0; flex: 0 0 auto; width: {CARD_W}px; aspect-ratio: 16/9;
           border-radius: 14px; overflow: hidden; background: #fff; border: 5px solid #fff;
           box-shadow: 0 14px 30px rgba(6,28,52,.34); }}
  .card img {{ width: 100%; height: 100%; object-fit: cover; display: block; border-radius: 9px; }}

  .hero-brand {{
    position: absolute; left: 46px; bottom: 44px; z-index: 6;
    padding: 18px 26px; border-radius: 22px;
    background: rgba(255,255,255,.14); backdrop-filter: blur(12px);
    border: 1px solid rgba(255,255,255,.28);
    box-shadow: 0 18px 44px rgba(4,24,46,.36);
  }}
  .hero-brand h1 {{ margin: 0; font-size: 34px; letter-spacing: -.4px; color: #fff; }}
  .hero-brand p {{ margin: 6px 0 0; font-size: 14px; color: rgba(255,255,255,.82); }}
  .scroll-hint {{
    position: absolute; left: 50%; bottom: 24px; transform: translateX(-50%); z-index: 6;
    font-size: 13px; letter-spacing: .12em; color: rgba(255,255,255,.7);
    animation: bounce 1.9s ease-in-out infinite;
  }}
  @keyframes bounce {{ 0%,100% {{ transform: translate(-50%, 0) }} 50% {{ transform: translate(-50%, 9px) }} }}

  /* ---------------- 内容区 ---------------- */
  main {{ position: relative; z-index: 2; }}
  section {{ padding: 118px 46px; }}
  .wrap {{ max-width: 1180px; margin: 0 auto; }}

  .kicker {{ font-size: 13px; letter-spacing: .22em; text-transform: uppercase;
             color: rgba(226,240,255,.62); }}
  .lead {{ font-size: clamp(30px, 4.4vw, 56px); line-height: 1.16; letter-spacing: -1px;
           margin: 18px 0 0; font-weight: 800; color: #fff; }}
  .lead em {{ font-style: normal; color: #8ec6f6; }}
  .sub {{ font-size: 18px; line-height: 1.72; margin: 22px 0 0; max-width: 780px;
          color: rgba(232,243,255,.84); }}

  .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 22px; margin-top: 60px; }}
  .stat {{ background: rgba(255,255,255,.10); border: 1px solid rgba(255,255,255,.20);
           border-radius: 20px; padding: 26px 24px; backdrop-filter: blur(6px); }}
  .stat b {{ display: block; font-size: 40px; letter-spacing: -1px; line-height: 1; color: #fff; }}
  .stat span {{ display: block; margin-top: 10px; font-size: 14px; color: rgba(226,240,255,.7); }}

  .tiles {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 26px; margin-top: 54px; }}
  .tile {{ margin: 0; background: rgba(255,255,255,.96); border-radius: 22px; padding: 14px;
           box-shadow: 0 22px 44px rgba(4,24,46,.34); }}
  .tile .shot {{ border-radius: 14px; overflow: hidden; aspect-ratio: 16/9; background: #fff; }}
  .tile img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
  .tile h3 {{ margin: 16px 6px 0; font-size: 19px; color: #12314c; }}
  .tile p {{ margin: 8px 6px 8px; font-size: 14px; line-height: 1.62; color: #33526c; }}

  .shows {{ display: grid; grid-template-columns: 1fr 1fr; gap: 30px; margin-top: 54px; }}
  .show {{ margin: 0; background: rgba(255,255,255,.96); border-radius: 24px; padding: 14px;
           box-shadow: 0 22px 46px rgba(4,24,46,.36); }}
  .show img {{ width: 100%; border-radius: 16px; display: block; }}
  .show figcaption {{ padding: 18px 8px 8px; display: flex; flex-direction: column; gap: 8px; }}
  .show b {{ font-size: 21px; color: #12314c; }}
  .show span {{ font-size: 14.5px; line-height: 1.62; color: #33526c; }}

  footer {{ padding: 66px 46px 90px; text-align: center; font-size: 13px;
            color: rgba(226,240,255,.6); }}

  /* 向下滚：逐块上浮淡入 */
  .reveal {{ opacity: 0; transform: translateY(52px);
             transition: opacity .9s cubic-bezier(.22,.8,.3,1), transform .9s cubic-bezier(.22,.8,.3,1);
             transition-delay: calc(var(--i, 0) * 90ms); }}
  .reveal.in {{ opacity: 1; transform: none; }}
  html.still .reveal {{ opacity: 1 !important; transform: none !important; transition: none !important; }}
</style>
</head>
<body>
  <div class="hero">
    <div class="stage">
{chr(10).join(tracks)}
    </div>
    <div class="hero-side"></div>
    <div class="hero-brand">
      <h1>VertexViewer</h1>
      <p>模型浏览器 ｜ 1.0+2026-10-30.1450</p>
    </div>
    <div class="scroll-hint">向下滚动</div>
  </div>

  <main>
    <section>
      <div class="wrap">
        <div class="kicker reveal">Asset Viewer</div>
        <h2 class="lead reveal" style="--i:1">把整座兵工厂<br><em>装进一个窗口</em></h2>
        <p class="sub reveal" style="--i:2">
          解包、索引、渲染、改枪、导出，全都在这一个软件里。不用装虚幻引擎，不用记路径，
          打开就能看见游戏里的每一个模型长什么样。
        </p>
        <div class="stats">
          <div class="stat reveal" style="--i:0"><b>937,088</b><span>已索引资产</span></div>
          <div class="stat reveal" style="--i:1"><b>6,212</b><span>可加载模型</span></div>
          <div class="stat reveal" style="--i:2"><b>13</b><span>资产分类</span></div>
          <div class="stat reveal" style="--i:3"><b>0</b><span>额外依赖安装</span></div>
        </div>
      </div>
    </section>

    <section>
      <div class="wrap">
        <div class="kicker reveal">Features</div>
        <h2 class="lead reveal" style="--i:1">你想看的，<em>一屏就能翻完</em></h2>
        <div class="tiles">
{feats}
        </div>
      </div>
    </section>

    <section>
      <div class="wrap">
        <div class="kicker reveal">Collection</div>
        <h2 class="lead reveal" style="--i:1">不只是枪，<em>钥匙卡和藏品也都在</em></h2>
        <div class="shows">
{show}
        </div>
      </div>
    </section>

    <footer>VertexViewer · 模型浏览器 ｜ 版本 1.0+2026-10-30.1450 ｜ 模型库 / 贴图 / 材质 / 改枪 / 导出</footer>
  </main>

<script>
  (function () {{
    var hash = location.hash || '';
    if (hash.indexOf('still') > -1 || hash.indexOf('cap') > -1) {{
      document.documentElement.classList.add('still');
    }}
    if (hash.indexOf('cap') > -1) {{ document.documentElement.classList.add('cap'); }}
    if (hash) {{ history.replaceState(null, '', location.pathname + location.search); }}

    var items = Array.prototype.slice.call(document.querySelectorAll('.reveal'));
    if ('IntersectionObserver' in window && !document.documentElement.classList.contains('still')) {{
      var io = new IntersectionObserver(function (entries) {{
        entries.forEach(function (e) {{
          if (e.isIntersecting) {{ e.target.classList.add('in'); io.unobserve(e.target); }}
        }});
      }}, {{ threshold: 0.16, rootMargin: '0px 0px -10% 0px' }});
      items.forEach(function (el) {{ io.observe(el); }});
    }} else {{
      items.forEach(function (el) {{ el.classList.add('in'); }});
    }}

    // 调试/截图用：#freeze=毫秒 把整墙定格在第 N 毫秒（负延迟 + 暂停）
    var fz = /freeze=(\d+)/.exec(hash);
    if (fz) {{
      Array.prototype.forEach.call(document.querySelectorAll('.track, .run'), function (t) {{
        t.style.animationPlayState = 'paused';
        t.style.animationDelay = '-' + fz[1] + 'ms';
      }});
    }}

    // 上滑时首屏整墙淡出，滚到一屏时基本透明（渐变过渡，不是硬切）
    var hero = document.querySelector('.hero');
    if (hero) {{
      window.addEventListener('scroll', function () {{
        var y = window.scrollY || 0;
        var h = window.innerHeight || 1;
        var p = Math.min(1, y / h);
        hero.style.opacity = String(1 - p * 0.96);
      }}, {{ passive: true }});
    }}
  }})();
</script>
</body>
</html>
"""


def shoot(html_path: str, out_png: str, hash_: str, w: int = 1700, h: int = 1000) -> None:
    url = "file:///" + html_path.replace("\\", "/") + hash_
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", f"--window-size={w},{h}",
                    f"--screenshot={out_png}", "--virtual-time-budget=6000", url],
                   capture_output=True, timeout=180)
    print("[scroll]", out_png, Image.open(out_png).size if os.path.exists(out_png) else "FAILED")


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(build_html())
    print("[scroll] html ->", path)

    for old in os.listdir(OUT):
        if old.startswith("preview_"):
            os.remove(os.path.join(OUT, old))

    full = os.path.join(OUT, "_full.png")
    shoot(path, full, "#cap", w=1700, h=3900)
    shots = []
    if os.path.exists(full):
        im = Image.open(full).convert("RGB")
        for i, top in enumerate(range(0, im.height, 1000)):
            seg = im.crop((0, top, im.width, min(im.height, top + 1000)))
            if seg.height < 40:
                continue
            p = os.path.join(OUT, f"preview_{i}.png")
            seg.save(p)
            shots.append(p)
        os.remove(full)
    if shots:
        ims = [Image.open(p).convert("RGB") for p in shots]
        scale = 0.62
        ims = [im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS) for im in ims]
        canvas = Image.new("RGB", (ims[0].width, sum(i.height for i in ims)), BG)
        y = 0
        for im in ims:
            canvas.paste(im, (0, y))
            y += im.height
        canvas.save(os.path.join(OUT, "preview.png"))
        print("[scroll] preview.png", canvas.size)


if __name__ == "__main__":
    main()
