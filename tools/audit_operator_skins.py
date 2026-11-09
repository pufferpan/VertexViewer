"""Validate every installed operator mesh's native sections and LOD buffers."""
import json,re,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import loader,uasset
from core.skeletal import decode

out=Path(__file__).resolve().parents[1]/'work/operators-20261101'
cat=json.loads(Path(loader.data_file('mesh_catalog.json')).read_text(encoding='utf-8'))
idx=loader.index()
def operator(p):
 return any(t in p for t in ('/Hero/','/Hero_HD/','/CharAppear/'))
paths={p for p,c in cat.items() if p in idx and c=='SkeletalMesh' and operator(p)}
paths.update(p for p in idx if p.endswith('.uasset') and operator(p)
             and re.search(r'_(?:Body|Face|Lower|Upper|Hair|Head|Arms|Legs)_(?:3P|1P|UI|LAY)(?:_HD)?\.uasset$',p,re.I))
rows=[];started=time.monotonic()
for number,path in enumerate(sorted(paths),1):
 print(number,len(paths),Path(path).name,flush=True)
 row={'path':path}
 try:
  b=loader.load_blobs(path);p=uasset.Package(b['uasset'],b.get('uexp'),b.get('ubulk'),path)
  exports=p.find_exports('SkeletalMesh')
  if not exports:continue
  r=p.export_reader(exports[0]);props=p.read_properties(r)
  mesh=decode(p,exports[0],props,r.pos)
  row.update(material_slots=len(mesh.material_paths),lods=[{'vertices':l.vertex_count,'triangles':l.triangle_count,'sections':len(l.sections)} for l in mesh.lods],
             missing_materials=[p for p in mesh.material_paths if p not in idx and not p.startswith('vertexviewer://')],
             null_source_slots=[p for p in mesh.material_paths if p.startswith('vertexviewer://')])
 except Exception as exc:
  row['error']=str(exc);print('  ERROR',type(exc).__name__,str(exc),flush=True)
 rows.append(row)
 if number%10==0 or number==len(paths):
  (out/'operator-audit.json').write_text(json.dumps({'total':len(rows),'elapsed':time.monotonic()-started,'models':rows},indent=2),encoding='utf-8')
print('COMPLETE',len(rows),'errors',sum('error'in r for r in rows),flush=True)
