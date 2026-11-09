"""补两张分类截图：模型库的「钥匙卡」「藏品」两栏（16:9）。

用法： python tools/shot_cards.py [输出目录]
产物： <out>/pg_keycard.png、<out>/pg_collectible.png
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.browser import ModelBrowser, _ModelCard  # noqa: E402
from app.main_window import VertexViewerWindow  # noqa: E402

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else r"work\promo_grid\pages")
os.makedirs(OUT, exist_ok=True)
W, HH = 1500, 844

app = QApplication([])
win = VertexViewerWindow()
win.resize(1500, 940)
win.show()
app.processEvents()


def grab(name: str) -> None:
    tmp = os.path.join(OUT, f"_raw_{name}.png")
    win.grab().save(tmp)
    im = Image.open(tmp).convert("RGB")
    top = max(0, min((im.height - HH) // 2 + 20, im.height - HH))
    im.crop((0, top, min(W, im.width), top + HH)).resize((W, HH), Image.LANCZOS).save(
        os.path.join(OUT, f"pg_{name}.png"))
    os.remove(tmp)
    print("[cards] saved", name)


STEPS: list = []


def add(delay: int, fn) -> None:
    STEPS.append((delay, fn))


def browser() -> ModelBrowser:
    return win.library_page if isinstance(win.library_page, ModelBrowser)         else win.findChildren(ModelBrowser)[0]


def set_cat(key: str) -> None:
    print("[cards] page =", type(win.library_page).__name__, "chips =", len(browser()._chips))
    browser()._set_category(key)


# 等启动时的「恢复上次模型」跑完，再切分类
add(9000, lambda: win.switchTo(win.library_page))
def load_first_3p() -> None:
    cards = browser().grid.findChildren(_ModelCard)
    print("[cards] cards =", len(cards))
    # 优先挑看起来像“实物”的（电池 / 主板 / 收音机），别用平铺的衣服
    want = ("电池", "主板", "收音机", "相机", "雕像")
    pick = next((c for c in cards if any(w in c.toolTip() for w in want)), None)
    if pick is None:
        pick = next((c for c in cards if "_3P" in c._vpath), cards[0] if cards else None)
    if pick is not None:
        print("[cards] load", pick._vpath.split("/")[-1])
        win.load_vpath(pick._vpath)


for cat, name in (("钥匙卡", "keycard"), ("藏品", "collectible")):
    add(400, lambda c=cat: set_cat(c))
    add(3000, load_first_3p)
    add(4200, lambda n=name: grab(n))
add(300, app.quit)


def run(i: int = 0) -> None:
    if i >= len(STEPS):
        return
    delay, fn = STEPS[i]

    def go() -> None:
        try:
            fn()
        except Exception as exc:                              # noqa: BLE001
            print("[cards] step failed", exc)
        run(i + 1)

    QTimer.singleShot(delay, go)


QTimer.singleShot(1200, lambda: run())
app.exec()
print("[cards] done", OUT)
