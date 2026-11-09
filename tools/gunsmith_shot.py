"""改枪台验证截图：加载主件 + 配件，合并后渲染成 PNG。

用法：
  python tools/gunsmith_shot.py <主件关键字> <输出png> [配件关键字 ...]

例：python tools/gunsmith_shot.py M4A1 work/gs_m4a1.png Muz AR-470 Acl
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.main_window import VertexViewerWindow  # noqa: E402
from core import loader  # noqa: E402
from core import gunsmith as gs  # noqa: E402

BASE_KEY = sys.argv[1] if len(sys.argv) > 1 else "M4A1"
OUT = sys.argv[2] if len(sys.argv) > 2 else r"G:\xmcl-fetch\work\gs_shot.png"
PART_KEYS = sys.argv[3:]


def pick_model(key: str, prefer_3p: bool = True) -> str:
    from app.browser import is_model_asset

    idx = loader.index()
    hits = []
    for path in idx:
        if key.lower() not in path.lower():
            continue
        if not is_model_asset(path):
            continue
        hits.append(path)
    if prefer_3p:
        hits.sort(key=lambda p: 0 if "_3P" in p else (1 if "_1P" in p else 2))
    return hits[0] if hits else ""


base_vpath = pick_model(BASE_KEY)
print("[gs] base", base_vpath)
base = loader.load_model(base_vpath)
if not getattr(base, "mesh", None):
    print("[gs] base has no mesh"); raise SystemExit(2)

recipe = gs.Recipe(base=base_vpath, base_name=os.path.basename(base_vpath))
if os.environ.get("VERTEXVIEWER_OFFICIAL"):
    # 按官方命名规则自动配一套（同型号码 + 同皮肤优先）
    for spec in gs.official_loadout(base_vpath):
        bundle = loader.load_model(spec.vpath)
        if not getattr(bundle, "mesh", None):
            continue
        recipe.parts.append((spec, bundle))
        print("[gs] official", spec.slot, os.path.basename(spec.vpath))
for key in PART_KEYS:
    vpath = pick_model(key)
    if not vpath:
        print("[gs] part miss", key); continue
    bundle = loader.load_model(vpath)
    if not getattr(bundle, "mesh", None):
        print("[gs] part no mesh", vpath); continue
    spec = gs.PartSpec(vpath=vpath, name=os.path.basename(vpath), slot=gs.guess_slot(vpath))
    recipe.parts.append((spec, bundle))
    print("[gs] part", spec.slot, os.path.basename(vpath))

combo = gs.assemble(base, recipe.parts, base_vpath=base_vpath)
tris = combo.mesh.lods[0].triangle_count if combo.mesh and combo.mesh.lods else 0
print("[gs] assembled tris", tris, "materials", len(combo.materials))

app = QApplication([])
win = VertexViewerWindow()
win.resize(1500, 940)
win.show()
app.processEvents()


def show():
    try:
        win.viewport.set_mesh(combo.mesh, combo.materials, combo.textures)
        win.viewport.frame_all()
    except Exception as exc:                                # noqa: BLE001
        print("[gs] viewport error", exc)
    QTimer.singleShot(900, shoot)


def shoot():
    win.grab().save(OUT)
    print("[gs] saved", OUT)
    QTimer.singleShot(150, app.quit)


QTimer.singleShot(700, show)
app.exec()
