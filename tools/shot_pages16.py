"""宣传图素材：把软件每个页面各截一张 16:9 的图（等真渲染完成再抓）。

用法： python tools/shot_pages16.py <输出目录>
产物： <out>/pg_<名>.png（1500×844，16:9）
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.main_window import VertexViewerWindow  # noqa: E402
from core import loader  # noqa: E402

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else r"work\promo_grid\pages")
os.makedirs(OUT, exist_ok=True)
W, HH = 1500, 844

app = QApplication([])
win = VertexViewerWindow()
win.resize(1500, 940)
win.show()
app.processEvents()
IDX = loader.index()


def pick(suffix: str) -> str:
    hits = [k for k in IDX if k.endswith(suffix)]
    if not hits:
        hits = [k for k in IDX if k.lower().endswith(suffix.lower())]
    return hits[0] if hits else ""


def grab(name: str) -> None:
    shot = win.grab()
    tmp = os.path.join(OUT, f"_raw_{name}.png")
    shot.save(tmp)
    im = Image.open(tmp).convert("RGB")
    top = max(0, min((im.height - HH) // 2 + 20, im.height - HH))
    im.crop((0, top, min(W, im.width), top + HH)).resize((W, HH), Image.LANCZOS).save(
        os.path.join(OUT, f"pg_{name}.png"))
    os.remove(tmp)
    print("[pages] saved", name, "loaded =" + str(win.current_vpath)[-46:])


STEPS: list = []


def add(delay: int, fn, label: str = "") -> None:
    STEPS.append((delay, fn, label))


def search(text: str) -> None:
    box = getattr(win.library_page, "search", None)
    if box is not None:
        box.setText(text)


M4 = pick("Rec_AR_M4A1-Std_001_3P.uasset")
HK = pick("Rec_AR_HK416_021_3P.uasset")

# 等启动时的「恢复上次模型」跑完，否则 load_vpath 会被 isRunning 挡掉
add(9000, lambda: (win.switchTo(win.library_page), win.load_vpath(M4)), "等待启动加载")
add(6500, lambda: grab("library"))
add(400, lambda: search("M4A1"))
add(4500, lambda: grab("library_search"))
add(400, lambda: search(""))
add(300, lambda: (win.apply_style("blueprint"), win.apply_wireframe(True)))
add(3000, lambda: grab("library_blueprint"))
add(300, lambda: (win.apply_wireframe(False), win.apply_style("pbr")))
add(1200, lambda: win.switchTo(win.textures_page))
add(3000, lambda: grab("textures"))
add(300, lambda: win.switchTo(win.materials_page))
add(2500, lambda: grab("materials"))
add(300, lambda: (win.switchTo(win.gunsmith_page), win.gunsmith_page._set_base(M4)))
add(2500, lambda: win.gunsmith_page._apply_official())
add(5000, lambda: grab("gunsmith"))
add(300, lambda: win.gunsmith_page._set_base(HK))
add(3000, lambda: win.gunsmith_page._apply_official())
add(5000, lambda: grab("gunsmith2"))
add(300, lambda: win.switchTo(win.export_page))
add(2500, lambda: grab("export"))
add(300, lambda: win.switchTo(win.settings_page))
add(2500, lambda: grab("settings"))
add(300, lambda: win.switchTo(win.tutorial_page))
add(2500, lambda: grab("tutorial"))
add(300, app.quit)


def run(i: int = 0) -> None:
    if i >= len(STEPS):
        return
    delay, fn, label = STEPS[i]

    def go() -> None:
        try:
            fn()
        except Exception as exc:                              # noqa: BLE001
            print("[pages] step failed:", label or "", exc)
        run(i + 1)

    QTimer.singleShot(delay, go)


QTimer.singleShot(1500, lambda: run())
app.exec()
print("[pages] done", OUT)
