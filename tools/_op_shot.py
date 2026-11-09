"""把任意模型渲染成 PNG，用来肉眼验收（干员/皮肤）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from core import loader  # noqa: E402
import render  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work")
W, H = 1400, 900

target = sys.argv[1]
name = sys.argv[2] if len(sys.argv) > 2 else "shot"
style = sys.argv[3] if len(sys.argv) > 3 else "pbr"

idx = loader.index()
vpath = target if target.startswith("..") else ""
if not vpath:
    hits = [k for k in idx if k.lower().endswith(target.lower())]
    if not hits:
        hits = [k for k in idx if target.lower() in k.lower()]
    if not hits:
        raise SystemExit(f"找不到 {target}")
    vpath = hits[0]

print("[shot] loading", vpath.split("Content/")[-1], flush=True)
bundle = loader.load_model(vpath, lod=0, want_textures=True)
if not getattr(bundle, "mesh", None):
    raise SystemExit("没有网格")

app = QApplication([])
viewer = render.MeshViewer()
viewer.resize(W, H)
viewer.set_background("studio")
viewer.set_style(style)
viewer.set_mesh(bundle.mesh, bundle.materials, bundle.textures)
viewer.frame_all()
cam = viewer._state.camera                                     # noqa: SLF001
cam.yaw, cam.pitch = 32.0, 12.0
viewer.frame_all()
cam.distance *= 0.95
path = os.path.join(OUT, f"op_{name}.png")
viewer.capture(path, width=W, height=H)
print("[shot]", path)
