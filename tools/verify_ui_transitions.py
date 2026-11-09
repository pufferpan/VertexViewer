"""Exercise startup/wizard animations without changing the user's settings."""
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.splash import SplashWindow
from app.wizard import WizardWindow, _Backdrop, BG

OUT = Path(__file__).resolve().parents[1] / "work/fix-20261101"
OUT.mkdir(parents=True, exist_ok=True)
app = QApplication.instance() or QApplication([])
app.setQuitOnLastWindowClosed(False)
errors = []
sys.excepthook = lambda typ, value, tb: errors.append(f"{typ.__name__}: {value}")
gaps = []
last = time.perf_counter()


def tick():
    global last
    now = time.perf_counter()
    gaps.append((now - last) * 1000)
    last = now


timer = QTimer()
timer.setTimerType(Qt.PreciseTimer)
timer.setInterval(16)
timer.timeout.connect(tick)
timer.start()
splash = SplashWindow()
splash.setAttribute(Qt.WA_DontShowOnScreen)
splash.center_on_screen()
splash.set_fraction(.6)
QTest.qWait(780)
splash.grab().save(str(OUT / "splash.png"))
done = []
area = app.primaryScreen().availableGeometry()
target = QRect(area.center().x() - 550, area.center().y() - 350, 1100, 700)
splash.expand_to(target, done=lambda: done.append(True))
native = QRect(splash.geometry())
QTest.qWait(300)
assert splash.geometry() == native
assert 560 < splash.surfaceRect.width() < 1100
splash.grab().save(str(OUT / "splash-expanding.png"))
QTest.qWait(600)
assert done == [True] and not splash.isVisible()

wizard = WizardWindow()
wizard.setAttribute(Qt.WA_DontShowOnScreen)
wizard.start()
native = QRect(wizard.geometry())
QTest.qWait(1450)
assert wizard.geometry() == native
assert wizard.surfaceRect.width() <= native.width()
QTest.qWait(1900)
assert not wizard._intro
assert wizard.surfaceRect == wizard.rect()
assert wizard.bg.row_count() == 3
assert not wizard.bg._rows_animating
assert all(row["alpha"] == 1.0 for row in wizard.bg._rows)
wizard.grab().save(str(OUT / "wizard.png"))
# Static steps keep the complete wall even if an old animation changes a row.
wizard.bg._glow.stop()
wall_before = wizard.bg.grab().toImage()
for i in range(3):
    wizard.bg.set_row(i, dx=5000, alpha=0.0)
assert wizard.bg.grab().toImage() == wall_before
wizard.bg.reset_rows()
# A missing layer manifest must show the original composed screenshot instead.
with patch("app.wizard.ROWS_JSON", str(OUT / "missing-rows.json")):
    fallback = _Backdrop(BG)
fallback.setAttribute(Qt.WA_DontShowOnScreen)
fallback.resize(1280, 720)
fallback.show()
assert fallback.row_count() == 0
fallback.grab().save(str(OUT / "wizard-fallback.png"))
assert fallback.grab().toImage().pixelColor(1100, 380) != fallback.grab().toImage().pixelColor(100, 380)
fallback.hide()
# Rapid page switches used to leave delayed animations running on old positions.
wizard._show_step(1)
QTest.qWait(70)
wizard._show_step(2)
QTest.qWait(70)
wizard._show_step(0)
QTest.qWait(800)
for widget in (wizard.panel.title, wizard.panel.body, wizard.panel.extra):
    assert widget.graphicsEffect().opacity() == 1.0
    assert wizard.panel.rect().contains(widget.geometry())
finished = []
wizard.finished.connect(finished.append)
with patch("app.wizard.mark_done"):
    wizard._finish(False)
    QTest.qWait(650)
assert finished == [False] and not wizard.isVisible()

early = WizardWindow()
early.setAttribute(Qt.WA_DontShowOnScreen)
early.start()
with patch("app.wizard.mark_done"):
    early._finish(False)
    QTest.qWait(1400)
assert not early.isVisible() and not early._intro_delay.isActive()
assert not errors, errors
timer.stop()
gaps.sort()
report = dict(errors=errors, frames=len(gaps),
              timer_p95_ms=round(gaps[int(len(gaps) * .95)], 2),
              timer_max_ms=round(max(gaps), 2),
              splash_native_geometry_fixed=True, wizard_native_geometry_fixed=True,
              fast_page_switch=True, finish=True, close_during_intro=True)
(OUT / "ui-verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
