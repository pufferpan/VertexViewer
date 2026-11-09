"""改枪台「官方配件」真实路径截图：走界面自己的按钮逻辑。

用法：
  python tools/gunsmith_page_shot.py <主件关键字> <输出png>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.main_window import VertexViewerWindow  # noqa: E402
from core import loader  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else "Rec_AR_M4A1-Std_001_3P"
OUT = sys.argv[2] if len(sys.argv) > 2 else r"work/gs_page.png"


def pick(key: str) -> str:
    hits = [p for p in loader.index() if key.lower() in p.lower() and p.lower().endswith(".uasset")]
    hits.sort(key=lambda p: (0 if p.lower().endswith("_3p.uasset") else 1, len(p)))
    return hits[0] if hits else ""


app = QApplication([])
win = VertexViewerWindow()
win.resize(1500, 940)
win.show()
app.processEvents()

page = win.gunsmith_page
base = pick(KEY)
print("[shot] base", base)


def step():
    win.switchTo(page)
    page._set_base(base)
    QTimer.singleShot(1200, step2)


def step2():
    page._apply_official()
    QTimer.singleShot(1800, shoot)


def shoot():
    win.grab().save(OUT)
    print("[shot] saved", OUT)
    print("[shot] status", page.status.text())
    QTimer.singleShot(150, app.quit)


QTimer.singleShot(800, step)
app.exec()
