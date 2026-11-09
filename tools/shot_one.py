"""单资产离屏渲染（用和 selfcheck 一样的 MeshViewer 路径）。

用法： python tools/shot_one.py <资产名> <输出png>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from core import loader  # noqa: E402
import render  # noqa: E402

NAME = sys.argv[1] if len(sys.argv) > 1 else "Boss_C501_CellPhone_3P.uasset"
OUT = sys.argv[2] if len(sys.argv) > 2 else r"G:\xmcl-fetch\work\shot_one.png"

app = QApplication([])
hits = [k for k in loader.index() if k.endswith(NAME)]
assert hits, f"index 里没有 {NAME}"
b = loader.load_model(hits[0], lod=0, want_textures=True)
print("mats:", [(m.name, bool(m.base_color_texture), m.blend_mode, m.is_untextured_overlay)
                for m in b.materials])
print("texs:", [getattr(t, "name", "")[-12:] for t in b.textures])
mode = os.environ.get("VERTEXVIEWER_TEST_TEX", "").strip()
if mode and b.textures:
    import numpy as np
    arr = np.array(b.textures[0].rgba, copy=True)
    if mode == "black":
        arr[..., :3] = 0
        arr[..., 3] = 255
    elif mode == "red":
        arr[..., 0] = 255
        arr[..., 1] = 0
        arr[..., 2] = 0
        arr[..., 3] = 255
    print("test texture:", mode, arr.shape, float(arr[..., :3].mean()))
    b.textures[0].rgba = arr
w = render.MeshViewer()
w.resize(760, 760)
w.set_mesh(b.mesh, b.materials, b.textures)
w.frame_all()
w.capture(OUT)
print("saved", OUT)
print("draws:", len(getattr(w, "_draws", [])))
print("gl textures:", {k: v for k, v in (getattr(w, "_gl_textures", {}) or {}).items()})
