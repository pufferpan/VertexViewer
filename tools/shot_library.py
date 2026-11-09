"""模型库 UI 验收：卡片视图 / 分类筛选 / 中文名搜索 各出一张图。

用法：
  python tools/shot_library.py            # 出 3 张到 work/lib_*.png
  python tools/shot_library.py "背包"      # 换成自己的搜索词
"""
from __future__ import annotations

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

OUT = r"G:\xmcl-fetch\work"
KEYWORD = sys.argv[1] if len(sys.argv) > 1 else "背包"

w = VertexViewerWindow()
w.resize(1500, 940)
w.show()

vp = ("../../../DeltaForce/Content/Models/Weapons/Parts/Mag/"
      "Mag_AK74_545x39-30R-Std_004/SM_Mag_AK74_545x39-30R-Std_004_3P.uasset")
deadline = time.time() + 120
while time.time() < deadline and not w.browser.is_ready:
    app.processEvents()
print("index ready", w.browser.is_ready, w.browser.count, flush=True)

w.load_vpath(vp)
deadline = time.time() + 120
while time.time() < deadline and w.bundle is None:
    app.processEvents()
print("loaded", w.bundle.display_name if w.bundle else None, flush=True)


def settle(frames: int = 40) -> None:
    for _ in range(frames):
        app.processEvents()
        time.sleep(0.02)


def shot(name: str) -> None:
    settle()
    path = os.path.join(OUT, name)
    print("saved", path, w.grab().save(path), flush=True)


# 1) 默认卡片视图
w.switchTo(w.library_page)
settle(60)
shot("lib_cards.png")

# 2) 分类筛选：装备
w.browser._set_category("装备")
shot("lib_cat_equip.png")
w.browser._set_category("all")

# 3) 中文名搜索
w.browser.search.setText(KEYWORD)
shot("lib_search_cn.png")
w.browser.search.setText("")

# 4) 目录视图
w.browser._toggle_view()
shot("lib_tree.png")
print("done")
