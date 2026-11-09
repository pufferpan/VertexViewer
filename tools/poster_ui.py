"""宣传图素材（真窗口 + 真 GL）：模型库 / 贴图 / 材质 / 改枪 四个页面各出一张。

用法： python tools/poster_ui.py <输出目录>
产物： <out>/ui_library.png / ui_texture.png / ui_material.png / ui_gunsmith.png
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.main_window import VertexViewerWindow  # noqa: E402
from core import loader  # noqa: E402

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else r"work\poster")
os.makedirs(OUT, exist_ok=True)

GUN = "Rec_AR_M4A1-Std_001_3P.uasset"
MODEL = "Boss_C501_CellPhone_3P.uasset"

app = QApplication([])
win = VertexViewerWindow()
win.resize(1500, 940)
win.show()
app.processEvents()


def pick(suffix: str) -> str:
    hits = [k for k in loader.index() if k.endswith(suffix)]
    return hits[0] if hits else ""


def save(name: str) -> None:
    path = os.path.join(OUT, name)
    win.grab().save(path)
    print("[poster-ui] saved", path)


steps = []


def main() -> None:
    gun = pick(GUN)
    win.switchTo(win.library_page)
    win.load_vpath(gun)
    steps.append((1400, lambda: save("ui_library.png")))

    def to_tex() -> None:
        win.switchTo(win.textures_page)
    steps.append((300, to_tex))
    steps.append((1600, lambda: save("ui_texture.png")))

    def to_mat() -> None:
        win.switchTo(win.materials_page)
    steps.append((300, to_mat))
    steps.append((1600, lambda: save("ui_material.png")))

    def to_gs() -> None:
        page = win.gunsmith_page
        win.switchTo(page)
        page._set_base(gun)
    steps.append((300, to_gs))

    def official() -> None:
        win.gunsmith_page._apply_official()
    steps.append((1500, official))
    steps.append((2500, lambda: save("ui_gunsmith.png")))

    steps.append((300, app.quit))


def run(i: int = 0) -> None:
    if i >= len(steps):
        return
    delay, fn = steps[i]
    def go() -> None:
        try:
            fn()
        except Exception as exc:                                # noqa: BLE001
            print("[poster-ui] step failed", exc)
        run(i + 1)
    QTimer.singleShot(delay, go)


QTimer.singleShot(900, lambda: (main(), run()))
app.exec()
print("[poster-ui] done", OUT)
