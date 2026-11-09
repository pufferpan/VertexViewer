"""宣传图素材补拍：模型库卡片页（等缩略图渲染完再抓）。

用法： python tools/poster_ui2.py <输出目录>
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

app = QApplication([])
win = VertexViewerWindow()
win.resize(1500, 940)
win.show()
app.processEvents()


def pick(suffix: str) -> str:
    hits = [k for k in loader.index() if k.endswith(suffix)]
    return hits[0] if hits else ""


def shots() -> None:
    gun = pick("Rec_AR_HK416_021_3P.uasset")
    page = win.library_page
    win.switchTo(page)
    win.load_vpath(gun)
    QTimer.singleShot(9000, lambda: after(gun))


def after(gun: str) -> None:
    path = os.path.join(OUT, "ui_library.png")
    win.grab().save(path)
    print("[poster-ui2] saved", path)
    # 再补一张：搜索框里打 M4A1，展示中文名搜索
    try:
        box = getattr(win.library_page, "search", None) or getattr(win.library_page, "search_box", None)
        if box is not None:
            box.setText("M4A1")
    except Exception as exc:                                    # noqa: BLE001
        print("[poster-ui2] search set failed", exc)
    QTimer.singleShot(6000, lambda: (win.grab().save(os.path.join(OUT, "ui_search.png")),
                                     print("[poster-ui2] saved ui_search"),
                                     app.quit()))


QTimer.singleShot(1200, shots)
app.exec()
