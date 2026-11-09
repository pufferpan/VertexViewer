"""真实平台 + 真实 OpenGL 的端到端集成测试（主控用）。

用法：
    python tools/itest_gl.py            # 自动挑一个 Models 下的模型
    python tools/itest_gl.py <vpath>    # 指定资产

产出：work/itest_<stem>_<style>.png + 控制台统计。
"""
from __future__ import annotations

import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

WORK = r"G:\xmcl-fetch\work"
os.makedirs(WORK, exist_ok=True)


def main(argv):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from app.main_window import VertexViewerWindow

    win = VertexViewerWindow(auto_build=True)
    win.resize(1500, 940)
    win.show()
    app.processEvents()

    # 等模型索引建好
    def _val(obj, name, default=None):
        v = getattr(obj, name, default)
        return v() if callable(v) else v

    t0 = time.time()
    while time.time() - t0 < 120:
        app.processEvents()
        try:
            if _val(win.browser, "is_ready", False) and _val(win.browser, "count", 0):
                break
        except Exception:
            pass
        time.sleep(0.05)

    print("index ready:", _val(win.browser, "is_ready", None),
          "count:", _val(win.browser, "count", 0), f"({time.time()-t0:.1f}s)")

    vpath = argv[0] if argv else None
    if not vpath:
        vpath = win.browser.select_first_model()
        print("picked:", vpath)
    if not vpath:
        print("!! no model")
        return 2

    win.load_vpath(vpath)
    t0 = time.time()
    bundle = None
    while time.time() - t0 < 180:
        app.processEvents()
        bundle = getattr(win, "_bundle", None) or getattr(win, "bundle", None)
        if bundle is not None:
            break
        time.sleep(0.05)
    print(f"bundle after {time.time()-t0:.1f}s:", type(bundle).__name__ if bundle else None)
    if bundle is not None:
        m = bundle.mesh
        print("  mesh:", m.name, "lods:", [l.triangle_count for l in m.lods],
              "fmt:", m.source_format)
        print("  materials:", len(bundle.materials), "textures:", len(bundle.textures),
              "cn:", getattr(bundle, "display_name_cn", None))
        for t in bundle.textures[:6]:
            print("   tex:", t.name, f"{t.width}x{t.height}", t.source_format)

    vp = win.viewport
    print("backend:", "gl" if _val(vp, "is_gl", False) else "software",
          "tris:", _val(vp, "triangle_count", 0))

    stem = os.path.splitext(os.path.basename(vpath))[0][:40]
    for style in ("pbr", "toon", "posterize", "neon", "blueprint"):
        try:
            vp.set_style(style)
            app.processEvents()
            out = os.path.join(WORK, f"itest_{stem}_{style}.png")
            t = time.time()
            ok = win.capture_view() if style == "pbr" else vp.capture(out)
            print(f"  style {style}: capture={ok} {time.time()-t:.2f}s")
        except Exception as exc:  # noqa: BLE001
            print(f"  style {style} FAILED: {exc}")

    # 窗口级截图（验证 Fluent 布局 + GL 合成）
    try:
        app.processEvents()
        shot = os.path.join(WORK, f"itest_{stem}_window.png")
        win.grab().save(shot)
        print("window shot:", shot)
    except Exception:
        traceback.print_exc()

    QTimer.singleShot(600, win.close)
    QTimer.singleShot(900, app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
