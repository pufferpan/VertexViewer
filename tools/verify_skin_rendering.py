"""Capture real skin geometry after the exact selected-parent socket fix."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from core import gunsmith as gs, loader, weapon_skins as ws
from render.viewer import OffscreenViewer, SceneState, mesh_bounds


project = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path,
                    default=project / "work/features-20261101/skin-mounts-current")
parser.add_argument("--receiver", action="append", default=[])
args = parser.parse_args()
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=True)
app = QApplication.instance() or QApplication([])
viewer = OffscreenViewer()
report = []
for number, (receiver, name) in enumerate((
        ("Rec_AR_M4A1-Std_001", "HavvkTech_p9"),
        ("Rec_AR_HK416_021", "RecordAction_6b"),
        ("Rec_AR_ScarH_045", "Obsidian_uc")), 1):
    if args.receiver and receiver not in args.receiver:
        continue
    base = next(p for p in ws._model_paths()
                if p.endswith("/" + receiver + "_3P.uasset"))
    skin = next(s for s in ws.list_skins(base) if s.name == name)
    applied = ws.official_parts(gs.Recipe(base=skin.base, skin_base=base, skin_id=skin.id))
    bundle = loader.load_model(skin.base)
    pairs = []
    for part in applied.recipe.parts:
        print(receiver, Path(part.vpath).name, flush=True)
        data = loader.load_model(part.vpath)
        assert data.mesh and data.mesh.lods
        pairs.append((part, data))
    with patch.object(gs, "_bbox_fallback", wraps=gs._bbox_fallback) as fallback:
        combined = gs.assemble(bundle, pairs, base_vpath=skin.base)
    assert fallback.call_count == 0
    lod = combined.mesh.lods[0]
    assert np.isfinite(lod.positions).all()
    assert lod.indices.max() < lod.vertex_count
    state = SceneState(mesh=combined.mesh, materials=combined.materials,
                       textures=combined.textures, style="game",
                       mesh_version=number, texture_version=number)
    center, radius = mesh_bounds(combined.mesh)
    state.camera.frame(center, radius, aspect=1280 / 720)
    state.camera.yaw, state.camera.pitch = 0, 8
    state.camera.distance *= .66
    viewer.state = state
    path = out / (receiver + ".png")
    viewer.capture(str(path), 1280, 720)
    angles = {}
    for label, yaw, pitch in (("perspective", 35, 15), ("opposite", 180, 8)):
        state.camera.yaw, state.camera.pitch = yaw, pitch
        image_path = out / (receiver + "-" + label + ".png")
        viewer.capture(str(image_path), 1280, 720)
        angles[label] = str(image_path)
    row = dict(receiver=receiver, skin=name, parts=len(pairs),
               triangles=lod.triangle_count, fallback_count=fallback.call_count,
               omitted=list(applied.omitted), screenshot=str(path), angles=angles,
               positions_min=lod.positions.min(axis=0).tolist(),
               positions_max=lod.positions.max(axis=0).tolist())
    report.append(row)
    print(json.dumps(row), flush=True)
viewer.release()
sources = {name: hashlib.sha256((project / name).read_bytes()).hexdigest()
           for name in ("core/mesh.py", "core/gunsmith.py", "core/weapon_skins.py",
                        "core/material.py", "render/shaders/scene.frag")
           if (project / name).is_file()}
(out / "rendering-verification.json").write_text(
    json.dumps({"source_sha256": sources, "assemblies": report}, indent=2), encoding="utf-8")
print(f"Verified real geometry and screenshots for {len(report)} skin assemblies", flush=True)
