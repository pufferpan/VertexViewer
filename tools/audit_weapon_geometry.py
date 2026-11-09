"""Read actual weapon buffers and measure face/normal and edge consistency."""
import json
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import gunsmith as gs, loader

out = Path(__file__).resolve().parents[1] / 'work/features-20261101/geometry-audit.json'
names = ('M4A1-Std_001', 'HK416_021', 'ScarH_045', 'AKM', 'AK74',
         'M7', 'ASVAL', 'MP5', 'Vector', 'P90', 'M249', 'M870')
receivers = [row[0] for row in gs.catalog() if row[4] == 'base'
             and row[0].endswith('_3P.uasset') and '/WeaponAppear/' not in row[0]]
print('receivers', len(receivers), flush=True)
paths = []
for name in names:
    matches = [p for p in receivers if name.lower() in Path(p).stem.lower()]
    if not matches:
        continue
    base = min(matches, key=lambda p: (len(p), p))
    paths += [base] + [p.vpath for p in gs.official_loadout(base)]
if not paths:
    print(gs.catalog()[:3], flush=True)
    raise RuntimeError('No receiver matches')
report = []
for i, path in enumerate(dict.fromkeys(paths)):
    print(i, Path(path).name, flush=True)
    mesh = loader.load_mesh(path)
    if not mesh or not mesh.lods:
        report.append(dict(path=path, error='no mesh'))
        continue
    lod = mesh.lods[0]
    p = lod.positions.astype(np.float64)
    ix = lod.indices.reshape(-1, 3)
    tri = p[ix]
    cross = np.cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0])
    area2 = np.linalg.norm(cross, axis=1)
    valid = area2 > 1e-10
    edges = np.linalg.norm(tri-np.roll(tri, 1, axis=1), axis=2)
    row = dict(path=path, format=mesh.source_format, vertices=len(p),
               triangles=len(ix), degenerate=int((~valid).sum()),
               edge_percentiles=np.percentile(edges, [50, 95, 99, 100]).tolist())
    if lod.normals is not None:
        normals = lod.normals[ix].mean(axis=1)
        normals /= np.maximum(np.linalg.norm(normals, axis=1)[:, None], 1e-9)
        dots = (cross[valid]/area2[valid, None] * normals[valid]).sum(axis=1)
        row.update(normal_dot_percentiles=np.percentile(dots,[0,5,50,95,100]).tolist(),
                   normal_disagreement=float((np.abs(dots)<.3).mean()))
    report.append(row)
    out.write_text(json.dumps(report, indent=2), encoding='utf-8')
print('Done', len(report), flush=True)
