"""最终验收截图：真实事件循环里加载模型、等渲染完成再抓图。

用法： python tools/final_shot.py <资产名或vpath> <输出png>

环境变量（可选）：
  VERTEXVIEWER_TEX_OVERRIDE=<png>   把 base 贴图换成这张图（UV 对照用）
  VERTEXVIEWER_UVI=<n>              UV 通道
  VERTEXVIEWER_NO_VFLIP=1           不翻 V
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.main_window import VertexViewerWindow  # noqa: E402
from core import loader  # noqa: E402

VPATH = sys.argv[1] if len(sys.argv) > 1 else ""
OUT = sys.argv[2] if len(sys.argv) > 2 else r"G:\xmcl-fetch\work\final_shot.png"
TEX_OVERRIDE = os.environ.get("VERTEXVIEWER_TEX_OVERRIDE", "").strip()

app = QApplication([])
win = VertexViewerWindow()
win.resize(1500, 940)
win.show()

S = {"ticks": 0, "phase": "load", "wait": 0}


def save_and_quit(tag=""):
    win.grab().save(OUT)
    print("saved", OUT, tag, "tris", getattr(win.viewport, "triangle_count", 0),
          "gl", win.viewport.is_gl)
    QTimer.singleShot(200, app.quit)


def tick():
    S["ticks"] += 1
    tris = getattr(win.viewport, "triangle_count", 0)
    if S["phase"] == "load":
        idx = loader.index()
        name = os.path.basename(VPATH)
        hits = [k for k in idx if k.endswith("/" + name)] if name else []
        target = hits[0] if hits else VPATH
        if not target:
            print("no target")
            app.quit()
            return
        S["base_tris"] = tris
        win.load_vpath(target)
        S["target"] = target
        S["phase"] = "wait_tris"
        print("loading", target)
        return
    if S["phase"] == "wait_tris":
        cur = str(getattr(win, "current_vpath", "") or "")
        want = os.path.basename(S.get("target", ""))
        stem = want.rsplit(".", 1)[0]
        # 判据：目标资产名已经进了 current_vpath，而且三角形数连续几拍不再变化
        stable = tris == S.get("last_tris", -2) and tris > 0
        S["last_tris"] = tris
        S["stable"] = S.get("stable", 0) + 1 if stable else 0
        ready = bool(stem) and stem in cur and S["stable"] >= 6
        if ready:
            # load_vpath 只是把任务丢给线程，current_vpath 会先变；
            # 多等几拍让 worker 真正把 mesh 换上来（否则抓到的是上一个模型）
            S["settle"] = S.get("settle", 0) + 1
            if S["settle"] < 12:
                return
            if TEX_OVERRIDE:
                from PIL import Image
                win.viewport.set_texture_override(
                    "base", np.asarray(Image.open(TEX_OVERRIDE).convert("RGBA")))
                print("override base ->", TEX_OVERRIDE)
                S["phase"] = "wait_gl"
                S["wait"] = 4
            else:
                S["phase"] = "done"
                save_and_quit()
            return
    elif S["phase"] == "wait_gl":
        S["wait"] -= 1
        if S["wait"] <= 0:
            S["phase"] = "done"
            save_and_quit("override")
        return
    if S["ticks"] > 500:                       # 75s 上限
        if S["phase"] != "done":
            S["phase"] = "done"
            save_and_quit("timeout")
        return


timer = QTimer()
timer.timeout.connect(tick)
timer.start(150)
app.exec()
