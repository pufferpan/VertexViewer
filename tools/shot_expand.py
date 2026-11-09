"""拍开屏「展开过程」的中间帧，用于验收（直接抓窗口自身，不是整屏）。

用法： python tools/shot_expand.py [输出前缀]
产物： <前缀>_a.png … <前缀>_d.png
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QRect, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import fluent_api as F  # noqa: E402
from app.splash import SplashWindow  # noqa: E402

PREFIX = sys.argv[1] if len(sys.argv) > 1 else r"G:\xmcl-fetch\work\exp"

app = QApplication([])
F.apply_fluent_theme(True)
F.apply_dark_palette(app, True)

s = SplashWindow()
s.set_status("正在装载资产索引 · 340000/937088 个资产")
s.set_fraction(0.36)
s.center_on_screen()

area = app.primaryScreen().availableGeometry()
TARGET = QRect(area.center().x() - 758, area.center().y() - 489, 1516, 979)

shots = {"a": 90, "b": 220, "c": 380, "d": 560}


def go():
    s.expand_to(TARGET, done=lambda: None)
    for tag, ms in shots.items():
        QTimer.singleShot(ms, lambda t=tag: s.grab().save(f"{PREFIX}_{t}.png"))
    QTimer.singleShot(max(shots.values()) + 400, finish)


def finish():
    print("[shot_expand] done")
    app.quit()


QTimer.singleShot(400, go)
app.exec()
