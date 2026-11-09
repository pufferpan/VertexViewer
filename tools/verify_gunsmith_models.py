"""Load real default loadouts, audit assembly and capture actual OpenGL output."""
import gc
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from core import gunsmith as gs, loader, ueformat
from render.viewer import OffscreenViewer, SceneState, mesh_bounds

OUT = Path(__file__).resolve().parents[1] / "work/fix-20261101"
OUT.mkdir(parents=True, exist_ok=True)
app = QApplication.instance() or QApplication([])
viewer = OffscreenViewer()
report = []
for number, name in enumerate(("Rec_AR_M4A1-Std_001_3P", "Rec_AR_HK416_021_3P",
                               "Rec_AR_ScarH_045_3P"), 1):
    vp = next(p for p in loader.index() if p.endswith(name + ".uasset"))
    print(f"Loading {name}", flush=True)
    base = loader.load_model(vp)
    assert gs._lod0(base) is not None
    specs = gs.official_loadout(vp)
    pairs = []
    cache_differences = []
    for spec in specs:
        print(f"  {spec.slot}: {Path(spec.vpath).name}", flush=True)
        part = loader.load_model(spec.vpath)
        assert gs._lod0(part) is not None, spec.vpath
        pairs.append((spec, part))
    for source_vp, source in [(vp, base)] + [(sp.vpath, part) for sp, part in pairs]:
        cache = Path(os.environ["LOCALAPPDATA"]) / "VertexViewer/uemodel" / (Path(source_vp).stem + ".uemodel")
        if cache.exists():
            old, _, _ = ueformat.read_uemodel(str(cache))
            a, b = old.lods[0], source.mesh.lods[0]
            if not np.array_equal(a.indices, b.indices) or not np.array_equal(a.positions, b.positions):
                cache_differences.append(Path(source_vp).name)
    combo = gs.assemble(base, pairs, base_vpath=vp)
    lod = combo.mesh.lods[0]
    expected = sum(gs._lod0(b).triangle_count for b in [base] + [p for _, p in pairs])
    assert lod.triangle_count == expected
    assert np.isfinite(lod.positions).all()
    assert lod.indices.max() < lod.vertex_count
    assert len(lod.sections) == len(combo.materials)
    assert len({s.material_path for s in lod.sections}) == len(lod.sections)
    assert lod.uv_channel_count == max(gs._lod0(b).uv_channel_count
                                      for b in [base] + [p for _, p in pairs])
    state = SceneState(mesh=combo.mesh, materials=combo.materials, textures=combo.textures,
                       mesh_version=number, texture_version=number, style="game")
    center, radius = mesh_bounds(combo.mesh)
    state.camera.frame(center, radius, aspect=1280 / 720)
    state.camera.yaw, state.camera.pitch = 0.0, 8.0
    state.camera.distance *= .66
    viewer.state = state
    viewer.capture(str(OUT / f"{name}.png"), 1280, 720)
    # Mesh upload replacement must delete the old VAO/VBO/EBO.
    from OpenGL import GL
    old_gpu = dict(viewer.renderer._gpu_mesh)
    state.mesh_version += 1
    # GL can reuse the just-deleted numeric IDs on the next upload.
    with patch.object(GL, "glDeleteVertexArrays", wraps=GL.glDeleteVertexArrays) as vaos, \
         patch.object(GL, "glDeleteBuffers", wraps=GL.glDeleteBuffers) as buffers:
        viewer.render(256, 144)
        vaos.assert_called_once_with(1, [old_gpu["vao"]])
        buffers.assert_called_once_with(2, [old_gpu["vbo"], old_gpu["ebo"]])
    row = dict(model=name, parts=len(pairs), triangles=lod.triangle_count,
               uv_channels=lod.uv_channel_count, materials=len(combo.materials),
               stale_cache_geometry=cache_differences, gpu_buffers_released=True)
    report.append(row)
    print(json.dumps(row), flush=True)
    del base, pairs, combo, lod
    gc.collect()
viewer.release()
(OUT / "model-verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print("Verified all loadouts", flush=True)
