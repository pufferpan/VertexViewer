"""单资产离屏 GL 渲染 + 着色器绑定体检（排查「有贴图却渲成纯白」）。

用法： python tools/gl_probe.py <资产名> <输出png>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import loader  # noqa: E402
import render  # noqa: E402

NAME = sys.argv[1] if len(sys.argv) > 1 else "Boss_C501_CellPhone_3P.uasset"
OUT = sys.argv[2] if len(sys.argv) > 2 else r"G:\xmcl-fetch\work\gl_probe.png"

app = QApplication([])

fmt = QSurfaceFormat()
fmt.setVersion(3, 3)
fmt.setProfile(QSurfaceFormat.CoreProfile)
fmt.setDepthBufferSize(24)
fmt.setSamples(0)
surf = QOffscreenSurface()
surf.setFormat(fmt)
surf.create()
ctx = QOpenGLContext()
ctx.setFormat(fmt)
assert ctx.create() and ctx.makeCurrent(surf), "GL 上下文起不来"

hits = [k for k in loader.index() if k.endswith(NAME)]
assert hits, f"index 里没有 {NAME}"
vp = hits[0]
bundle = loader.load_model(vp, lod=0, want_textures=True, want_cn=True)
mesh, mats, texs = bundle.mesh, bundle.materials, bundle.textures
print("vpath :", vp.split("/")[-1])
print("mesh  : lods", len(mesh.lods), "| sections", getattr(mesh, "sections", None))
print("mats  :", len(mats), [(m.name, bool(m.base_color_texture), m.blend_mode,
                              m.is_untextured_overlay) for m in mats])
print("texs  :", len(texs), [getattr(t, "name", "")[-18:] for t in texs])

from render.viewer import SceneState, SceneRenderer
state = SceneState(mesh=mesh, materials=mats, textures=texs)
w, h = 760, 760
state.camera.frame(mesh.lods[0].positions.reshape(-1, 3), 1.25)
v = SceneRenderer()
img = v.render(state, w, h, readback=True)
print("render:", None if img is None else (img.shape, img.min(), img.max()))
if img is not None:
    from PIL import Image as _Im
    _Im.fromarray(img).save(OUT)
    print("saved", OUT)

v.capture(OUT)
print("saved", OUT)
draws = getattr(v, "_draws", [])
print("draws :", len(draws))
for i, d in enumerate(draws):
    m = d.material
    print(f"   [{i}] tris={d.count // 3} mat={getattr(m, 'name', None)} "
          f"base={(getattr(m, 'base_color_texture', '') or '-').split('/')[-1][:40]}")
bound = getattr(v, "_texture_cache", {})
print("bound textures:", len(bound), [str(k).split('/')[-1][:38] for k in list(bound)[:4]])
