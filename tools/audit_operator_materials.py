"""Check actual material references for the complete operator skin catalog."""
import json
import sys
import time
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
from core import loader

OUT=BASE/'work/operators-20261101'
catalog=json.loads((OUT/'operator-audit.json').read_text())
checked={}
errors=[]
started=time.monotonic()
for i,row in enumerate(catalog['models'],1):
    path=row['path']
    try:
        bundle=loader.load_model(path,want_textures=False)
        assert bundle.mesh and bundle.mesh.material_paths,path
        for mat in bundle.materials:
            if mat.pak_path in checked:
                continue
            declared={k:v for k,v in mat.texture_params.items() if str(k).replace('_','').lower()
                      in ('basecolormap','basecolor','basemap','diffusemap','albedomap') and v}
            result={'material':mat.pak_path,'base':mat.base_color_texture,'declared':declared}
            if declared and not mat.base_color_texture:
                result['unresolved_base']=True
            checked[mat.pak_path]=result
    except Exception as exc:
        errors.append({'model':path,'error':repr(exc)})
    if i%25==0 or i==len(catalog['models']):
        print(i,len(catalog['models']),'unique materials',len(checked),'errors',len(errors),flush=True)
        (OUT/'operator-material-audit.json').write_text(json.dumps({'complete':i==len(catalog['models']),
            'models':i,'seconds':time.monotonic()-started,'errors':errors,
            'materials':list(checked.values())},indent=2),encoding='utf-8')
