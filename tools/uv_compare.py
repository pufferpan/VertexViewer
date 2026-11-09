"""用 UV 调试贴图抓一张我们的渲染图（和 Blender 对照用）。

    python tools/uv_compare.py <资产名或vpath> <输出png> [uvdebug.png]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.main_window import VertexViewerWindow  # noqa: E402
from core import loader  # noqa: E402

VPATH = sys.argv[1] if len(sys.argv) > 1 else ""
OUT = sys.argv[2] if len(sys.argv) > 2 else r"G:\xmcl-fetch\work\uv_compare_gl.png"
TEX = sys.argv[3] if len(sys.argv) > 3 else r"G:\xmcl-fetch\work\uvdebug.png"

app = QApplication([])
win = VertexViewerWindow()
win.resize(1500, 940)
win.show()

state = {"tick": 0, "loaded": False, "saved": False}


def tick():
    state["tick"] += 1
    if not state["loaded"]:
        idx = loader.index()
        name = os.path.basename(VPATH)
        hits = [k for k in idx if k.endswith("/" + name)] if name else []
        target = hits[0] if hits else VPATH
        win.load_vpath(target)
        state["loaded"] = True
        print("loading", target)
        return
    tris = getattr(win.viewport, "triangle_count", 0)
    if not state["saved"] and tris > 0:
        arr = np.asarray(Image.open(TEX).convert("RGBA"))
        win.viewport.set_texture_override("base", arr)
        try:
            inner = win.viewport.inner if hasattr(win.viewport, "inner") else win.viewport
            st = getattr(inner, "_state", None) or getattr(getattr(inner, "renderer", None), "state", None)
            print("override keys:", list(getattr(st, "texture_override", {})))
            win.viewport.update()
        except Exception as exc:                              # noqa: BLE001
            print("probe failed", exc)
        state["saved"] = True
        QTimer.singleShot(1500, grab)
        return
    if state["tick"] > 400:
        print("timeout tris", tris)
        app.quit()


def grab():
    win.grab().save(OUT)
    print("saved", OUT)
    app.quit()


timer = QTimer()
timer.timeout.connect(tick)
timer.start(150)
app.exec()
