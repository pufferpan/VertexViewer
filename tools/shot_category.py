"""按分类打开模型库并出一张验收图（真窗口，GL 渲染）。

用法： python tools/shot_category.py <分类名> [资产名] [输出png]
例：   python tools/shot_category.py 角色技能 Boss_C501_CellPhone_3P.uasset work/skill.png
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.main_window import VertexViewerWindow  # noqa: E402
from core import loader  # noqa: E402

CAT = sys.argv[1] if len(sys.argv) > 1 else "角色技能"
if CAT in ("全部", "all", ""):
    CAT = "all"
NAME = sys.argv[2] if len(sys.argv) > 2 else ""
OUT = sys.argv[3] if len(sys.argv) > 3 else r"G:\xmcl-fetch\work\shot_category.png"

app = QApplication([])
win = VertexViewerWindow()
win.resize(1500, 940)
win.show()

S = {"ticks": 0, "phase": "boot", "base_tris": -1, "stable": 0}


def tick():
    S["ticks"] += 1
    tris = getattr(win.viewport, "triangle_count", 0)
    if S["phase"] == "boot":
        if win.browser.is_ready:
            win.browser._set_category(CAT)
        if NAME:
            hits = [k for k in loader.index() if k.endswith(NAME)]
            if hits:
                win.load_vpath(hits[0])
                S["base_tris"] = tris
                S["phase"] = "wait"
                print("category", CAT, "loading", hits[0])
                return
        S["phase"] = "settle"
        S["stable"] = 26
        return
    if S["phase"] == "wait":
        if tris > 0 and tris != S["base_tris"]:
            S["stable"] += 1
            if S["stable"] >= 12:
                S["phase"] = "settle"
        return
    if S["phase"] == "settle":
        S["stable"] -= 1
        if S["stable"] <= 0 or S["ticks"] > 400:
            win.grab().save(OUT)
            print("saved", OUT, "tris", tris, "cat", CAT)
            QTimer.singleShot(200, app.quit)


timer = QTimer()
timer.timeout.connect(tick)
timer.start(150)
app.exec()
