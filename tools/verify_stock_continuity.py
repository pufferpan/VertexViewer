"""Measure and capture actual M4 fixed-tube and HK416 compound-stock joins."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from core import gunsmith as gs, loader, weapon_skins as ws
from core.types import Material, ModelBundle
from render.viewer import OffscreenViewer, SceneState, mesh_bounds


out = Path(__file__).resolve().parents[1] / "work/features-20261101/stock-continuity"
out.mkdir(parents=True, exist_ok=True)
app = QApplication.instance() or QApplication([])
viewer = OffscreenViewer()
report = {}


def bundle(path):
    mesh = loader.load_mesh(path)
    assert mesh and mesh.lods
    return ModelBundle(mesh=mesh, materials=[Material(name="Gray") for _ in mesh.lods[0].sections])


def capture(name, base_path, base, parts):
    with patch.object(gs, "_bbox_fallback", wraps=gs._bbox_fallback) as fallback:
        combined = gs.assemble(base, parts, base_vpath=base_path)
    assert fallback.call_count == 0
    state = SceneState(mesh=combined.mesh, materials=combined.materials, style="game",
                       mesh_version=len(report) + 1, texture_version=len(report) + 1)
    center, radius = mesh_bounds(combined.mesh)
    state.camera.frame(center, radius, aspect=1280 / 720)
    state.camera.yaw, state.camera.pitch = 20, 10
    state.camera.distance *= .8
    viewer.state = state
    path = out / (name + ".png")
    viewer.capture(str(path), 1280, 720)
    return str(path)


def placed(spec, data, matrix):
    world = matrix @ gs._trs(translate=gs.part_offset(spec.vpath))
    return gs._apply_matrix(data.mesh.lods[0], world).positions, world


m4_path = next(p for p in ws._model_paths() if p.endswith("/Rec_AR_M4A1-Std_001_3P.uasset"))
stock_path = next(p for p in ws._model_paths() if p.endswith("/Sto_A_M4A1-Std_001_3P.uasset"))
m4, stock = bundle(m4_path), bundle(stock_path)
spec = gs.PartSpec(stock_path, "stock", socket="Sto_point")
plan = gs.resolve_placements(m4_path, m4.mesh.lods[0], [(spec, stock.mesh.lods[0])])
vertices, world = placed(spec, stock, plan[id(spec)])
gap = float(m4.mesh.lods[0].positions[:, 0].min() - vertices[:, 0].max())
assert np.allclose(gs.part_offset(stock_path), 0)
assert abs(gap) < .002, gap
report["M4A1"] = dict(stock=stock_path, offset=gs.part_offset(stock_path).tolist(),
                       stock_matrix=world.tolist(), receiver_join_gap_m=gap,
                       screenshot=capture("M4A1-stock", m4_path, m4, [(spec, stock)]))

base_path = next(p for p in ws._model_paths() if p.endswith("/Rec_AR_HK416_021_3P.uasset"))
skin = next(s for s in ws.list_skins(base_path) if s.name == "RecordAction_6b")
applied = ws.official_parts(gs.Recipe(base=skin.base, skin_id=skin.id, skin_base=base_path))
specs = [p for p in applied.recipe.parts
         if ws.part_identity(p.vpath) in ("sto_a_hk416c_041", "sto_a_hk416c-b_089")]
assert len(specs) == 2
base = bundle(skin.base)
pairs = [(spec, bundle(spec.vpath)) for spec in specs]
plan = gs.resolve_placements(skin.base, base.mesh.lods[0], [(s, b.mesh.lods[0]) for s, b in pairs])
body_spec, body = next((s, b) for s, b in pairs if ws.part_identity(s.vpath) == "sto_a_hk416c_041")
rods_spec, rods = next((s, b) for s, b in pairs if ws.part_identity(s.vpath) == "sto_a_hk416c-b_089")
body_vertices, body_matrix = placed(body_spec, body, plan[id(body_spec)])
rod_vertices, rod_matrix = placed(rods_spec, rods, plan[id(rods_spec)])
rear_delta = abs(float(body_vertices[:, 0].min() - rod_vertices[:, 0].min()))
front_gap = float(base.mesh.lods[0].positions[:, 0].min() - rod_vertices[:, 0].max())
assert rear_delta < .005 and front_gap < .003, (rear_delta, front_gap)
report["HK416"] = dict(body=body_spec.vpath, rods=rods_spec.vpath,
                         body_matrix=body_matrix.tolist(), rods_matrix=rod_matrix.tolist(),
                         body_offset=gs.part_offset(body_spec.vpath).tolist(),
                         rear_bounds_difference_m=rear_delta, receiver_overlap_m=-front_gap,
                         screenshot=capture("HK416-stock", skin.base, base, pairs))
viewer.release()
(out / "continuity-verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2), flush=True)
