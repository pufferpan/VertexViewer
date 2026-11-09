"""看一眼「官方配件」装出来的样子：侧视/俯视各一张，用来核对瞄具/贴腮高度。

用法：python tools/_look_official.py "Rec_AR_M4A1-Std_001_3P" [--out work/_look]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "Rec_AR_M4A1-Std_001_3P"
    out = "work/_look"
    style = "pbr"
    ev = 0.0
    for i, a in enumerate(sys.argv):
        if a == "--out" and i + 1 < len(sys.argv):
            out = sys.argv[i + 1]
        if a == "--style" and i + 1 < len(sys.argv):
            style = sys.argv[i + 1]
        if a == "--ev" and i + 1 < len(sys.argv):
            ev = float(sys.argv[i + 1])

    from PySide6.QtWidgets import QApplication

    from core import gunsmith as gs, loader
    from core.mesh import Mesh
    from render.viewer import MeshViewer

    app = QApplication.instance() or QApplication([])
    vp = next(k for k in loader.index() if k.endswith(name + ".uasset"))
    bundle = loader.load_model(vp, want_textures=True)
    specs = gs.official_loadout(vp)
    pairs = []
    for sp in specs:
        pairs.append((sp, loader.load_model(sp.vpath, want_textures=True)))
        print(f"  {sp.slot:8} {os.path.basename(sp.vpath):44} socket={sp.socket}")
    combo = gs.assemble(bundle, pairs, base_vpath=vp)

    v = MeshViewer()
    v.set_style(style)
    v.set_exposure(ev)
    v.set_mesh(combo.mesh, combo.materials, combo.textures)
    v.resize(1280, 720)
    v.show()
    app.processEvents()

    cam = v._state.camera  # noqa: SLF001
    for tag, yaw, pitch, zoom in (("side", 0.0, 0.0, 0.42),
                                  ("top", 0.0, 89.0, 0.5),
                                  ("iso", -6.0, 12.0, 0.5)):
        cam.yaw, cam.pitch = yaw, pitch
        v.frame_all()
        cam.distance *= zoom
        app.processEvents()
        path = f"{out}_{tag}.png"
        v.grab().save(path)
        print("   ->", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
