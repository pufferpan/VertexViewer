"""探针：记录开屏窗口每帧的 grow / 窗口几何 / 时间，确认「展开动画」到底有没有画出来。

用法： python tools/probe_splash.py [秒数]
输出： work/splash_probe.txt
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OUT = os.path.join(ROOT, "work", "splash_probe.txt")
RUN_S = float(sys.argv[1]) if len(sys.argv) > 1 else 16.0

import app.splash as splash_mod  # noqa: E402

LOG = []
T0 = time.monotonic()

_orig_paint = splash_mod.SplashWindow.paintEvent
_orig_setter = splash_mod.SplashWindow.set_expand_t
_orig_expand = splash_mod.SplashWindow.expand_to
_orig_center = splash_mod.SplashWindow.center_on_screen


def _log(kind, grow, geom, glass):
    LOG.append((round(time.monotonic() - T0, 3), kind, round(grow, 3), geom, glass))


def paint(self, event):
    _log("paint", getattr(self, "_grow", -1), self.geometry().getRect(),
         bool(getattr(self, "_glass", False)))
    return _orig_paint(self, event)


def set_expand_t(self, value):
    _log("tick", float(value), self.geometry().getRect(), None)
    return _orig_setter(self, value)


def expand_to(self, target, done=None, duration=660):
    _log("expand_to", getattr(self, "_grow", -1), target.getRect(), None)
    return _orig_expand(self, target, done, duration)


def center_on_screen(self):
    ret = _orig_center(self)
    # 此时 QApplication 一定已经存在，才能挂定时器
    from PySide6.QtCore import QTimer
    QTimer.singleShot(int(RUN_S * 1000), _dump)

    def _beat():
        _log("beat", -1.0, (0, 0, 0, 0), None)

    beat = QTimer()
    beat.setInterval(50)
    beat.timeout.connect(_beat)
    beat.start()
    self._beat = beat
    return ret


def _dump():
    lines = [f"{t}\t{kind}\tgrow={g}\tgeom={geom}\tglass={glass}"
             for t, kind, g, geom, glass in LOG]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(f"# {len(lines)} 帧 / {RUN_S}s\n")
        fh.write("\n".join(lines))
    print(f"[probe] wrote {OUT}（{len(lines)} 行）", flush=True)
    from PySide6.QtWidgets import QApplication
    QApplication.quit()


splash_mod.SplashWindow.paintEvent = paint
splash_mod.SplashWindow.set_expand_t = set_expand_t
splash_mod.SplashWindow.expand_to = expand_to
splash_mod.SplashWindow.center_on_screen = center_on_screen


def main() -> int:
    from app.__main__ import main as real_main
    return real_main([])


if __name__ == "__main__":
    raise SystemExit(main())
