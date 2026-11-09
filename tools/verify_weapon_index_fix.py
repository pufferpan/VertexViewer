"""Compare real affected components against the preserved pre-fix parser."""
import ast
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtWidgets import QApplication
from core import loader, mesh
from render.viewer import OffscreenViewer, SceneState, mesh_bounds

out = ROOT / 'work/features-20261101/index-fix'
out.mkdir(parents=True, exist_ok=True)
baseline = ROOT / 'work/features-20261101/baseline-source/core/mesh.py'
source = baseline.read_text(encoding='utf-8-sig')
node = next(n for n in ast.parse(source).body
            if isinstance(n, ast.FunctionDef) and n.name == '_locate_leading_container')
namespace = dict(mesh.__dict__)
exec(ast.get_source_segment(source, node), namespace)
before_locator = namespace['_locate_leading_container']
app = QApplication.instance() or QApplication([])
viewer = OffscreenViewer()
report = {'baseline_sha256': hashlib.sha256(baseline.read_bytes()).hexdigest(), 'models': []}

def consistency(lod):
    tri = lod.positions[lod.indices.reshape(-1, 3)].astype(np.float64)
    cross = np.cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0])
    length = np.linalg.norm(cross, axis=1)
    normals = lod.normals[lod.indices.reshape(-1, 3)].mean(axis=1)
    normals /= np.maximum(np.linalg.norm(normals, axis=1)[:, None], 1e-9)
    valid = length > 1e-10
    dots = (cross[valid]/length[valid, None] * normals[valid]).sum(axis=1)
    return {'triangles': lod.triangle_count, 'vertices': lod.vertex_count,
            'median_face_normal_dot': float(np.median(dots)),
            'bad_face_normal_fraction': float((np.abs(dots)<.3).mean())}

for number, stem in enumerate(('FroG_Pic_Mag-AFG_003', 'Other_KACrailcover3_068',
                               'Sto_A_CoreCP_023')):
    vp = next(p for p in loader.index() if p.endswith('/'+stem+'_3P.uasset'))
    blobs = loader.load_blobs(vp)
    with patch.object(mesh, '_locate_leading_container', before_locator):
        before = mesh.load_mesh_from_blobs(vp, blobs)
    after = mesh.load_mesh_from_blobs(vp, blobs)
    row = {'path': vp, 'before': consistency(before.lods[0]), 'after': consistency(after.lods[0])}
    assert row['after']['median_face_normal_dot'] > .9, row
    center, radius = mesh_bounds(after)
    for i, (label, model) in enumerate((('before', before), ('after', after))):
        state = SceneState(mesh=model, style='clay', mesh_version=number*2+i+1)
        state.camera.frame(center, radius, aspect=1.4)
        state.camera.yaw, state.camera.pitch = 35, 15
        state.camera.distance *= .85
        viewer.state = state
        viewer.capture(str(out/(stem+'-'+label+'.png')), 980, 700)
    report['models'].append(row)
    print(json.dumps(row), flush=True)
viewer.release()
(out/'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
