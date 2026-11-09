"""测开屏窗口的首帧/首次改写尺寸耗时，定位「展开动画看不见」的卡顿源。

用法： python tools/bench_splash.py
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QRect, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import splash as S  # noqa: E402

app = QApplication([])
area = app.primaryScreen().availableGeometry()
SMALL = QRect(area.center().x() - 150, area.center().y() - 84, 300, 168)
BIG = QRect(area.center().x() - 750, area.center().y() - 470, 1500, 940)


def bench(label, pre_accent, use_accent):
    w = S.SplashWindow()
    w.set_status("bench")
    t0 = time.monotonic()
    w.setGeometry(SMALL)
    w.show()
    first = time.monotonic() - t0
    for _ in range(20):
        app.processEvents()
        time.sleep(0.005)
    t1 = time.monotonic()
    if pre_accent:
        S._enable_acrylic(w)
        for _ in range(10):
            app.processEvents()
            time.sleep(0.005)
        t2 = time.monotonic()
    else:
        t2 = t1
    if not use_accent:
        S._disable_acrylic(w)
    t3 = time.monotonic()
    w.setGeometry(BIG)
    app.processEvents()
    t4 = time.monotonic()
    for _ in range(40):
        app.processEvents()
        time.sleep(0.005)
        w.setGeometry(SMALL if False else w.geometry())
    t5 = time.monotonic()
    print(f"{label}: show={first*1000:.0f}ms accent_toggle={(t2-t1)*1000:.0f}ms "
          f"disable={(t3-t2)*1000:.0f}ms first_resize={(t4-t3)*1000:.0f}ms "
          f"settle={(t5-t4)*1000:.0f}ms", flush=True)
    w.hide()
    w.deleteLater()
    for _ in range(10):
        app.processEvents()


bench("A 有毛玻璃 + 保持", pre_accent=True, use_accent=True)
bench("B 有毛玻璃 + 关掉", pre_accent=True, use_accent=False)
bench("C 从不开毛玻璃", pre_accent=False, use_accent=False)
QTimer.singleShot(300, app.quit)
app.exec()
