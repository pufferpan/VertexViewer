"""在真机启动流程里抓整屏，证明展开过程确实在动。

用法： python tools/probe_expand_shots.py [输出前缀]
产物： <前缀>_t<ms>.png（按毫秒序号）
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PREFIX = sys.argv[1] if len(sys.argv) > 1 else r"G:\xmcl-fetch\work\eshot"

import app.splash as S  # noqa: E402

_orig_expand = S.SplashWindow.expand_to


def expand_to(self, target, done=None, duration=760):
    ret = _orig_expand(self, target, done, duration)
    try:
        from PySide6.QtCore import QTimer
        from PIL import ImageGrab

        t0 = time.monotonic()
        state = {"n": 0}

        def _grab():
            el = (time.monotonic() - t0) * 1000
            if el > duration + 260:
                timer.stop()
                return
            geom = self.geometry()
            shot = ImageGrab.grab(bbox=(geom.x(), geom.y(),
                                        geom.x() + geom.width(),
                                        geom.y() + geom.height()))
            path = f"{PREFIX}_t{int(el):03d}.png"
            shot.save(path)
            state["n"] += 1
            print(f"[shot] {int(el)}ms geom={geom.getRect()} -> {os.path.basename(path)}",
                  flush=True)

        timer = QTimer(self)
        timer.setInterval(55)
        timer.timeout.connect(_grab)
        timer.start()
        self._shot_timer = timer
    except Exception as exc:                                      # noqa: BLE001
        print(f"[shot] setup failed: {exc}", flush=True)
    return ret


S.SplashWindow.expand_to = expand_to


def main() -> int:
    from app.__main__ import main as real_main
    return real_main([])


if __name__ == "__main__":
    raise SystemExit(main())
