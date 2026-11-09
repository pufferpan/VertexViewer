"""验证「卡片右键自定义图标」是否生效：配一张图 → 卡片上应该看到它。

用法： python tools/shot_icon.py [关键词]
输出： work/lib_icon_custom.png
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.fluent_api import QApplication, apply_dark_palette, apply_fluent_theme  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv[:1])
apply_fluent_theme(True)
apply_dark_palette(app, True)

from app.main_window import VertexViewerWindow  # noqa: E402
from core import loader, usertable  # noqa: E402

KEYWORD = sys.argv[1] if len(sys.argv) > 1 else "AK74"
OUT = r"G:\xmcl-fetch\work\lib_icon_custom.png"

# 找一个搜得出来的资产，给它配图标（用背包的 BaseColor 当图，肉眼一眼能认出来）
hits = [k for k in loader.index() if k.endswith("_1P.uasset") and "AK74" in k]
target = hits[0] if hits else None
src = r"G:\xmcl-fetch\work\dec_boatkey_bc.png"
if target and os.path.exists(src):
    print("set icon for", target.split("/")[-1], "->", usertable.set_override(target, src))

w = VertexViewerWindow()
w.resize(1500, 940)
w.show()
deadline = time.time() + 150
while time.time() < deadline and not w.browser.is_ready:
    app.processEvents()
print("index ready", w.browser.is_ready, w.browser.count, flush=True)

w.browser.search.setText(KEYWORD)


def settle(seconds: float = 1.6) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


settle(2.0)
cards = w.browser.grid.findChildren(type(w.browser.grid).__mro__[0]) if False else []
print("saved", w.grab().save(OUT), "cards", len(getattr(w.browser, "_card_items", [])))
