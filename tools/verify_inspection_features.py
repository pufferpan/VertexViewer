"""Real game animation deformation, native input precision, and portable custom parts."""
from pathlib import Path
import json
import os
import sys
import tempfile
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np


def run(out):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from fluentpy import widgets as W
    from core import loader, gunsmith, custom_parts
    from core.inspection import decode_animation, related_animations, SkinPlayer
    from app.gunsmith_page import GunsmithPage
    from app.inspection_page import InspectionPage
    from render.viewer import SceneState, OffscreenViewer, mesh_bounds
    from PIL import Image
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    from app.fluent_api import apply_dark_palette, apply_fluent_theme
    apply_fluent_theme(True)
    apply_dark_palette(app, True)
    catalog=loader.catalog()
    path=next(p for p,c in catalog.items() if 'AnaisCaseEX_1693/' in p and 'Mesh' in c)
    bundle=loader.load_model(path)
    assert bundle.mesh.reference_pose is not None
    lod=bundle.mesh.lods[0]
    assert lod.bone_indices is not None and np.allclose(lod.bone_weights.sum(axis=1),1)
    rows=related_animations(path)
    asset=next(r[0] for r in rows if r[0].endswith('_Open.uasset'))
    clips=decode_animation(asset, force_decoder=True)
    mesh=deepcopy(bundle.mesh)
    player=SkinPlayer(mesh,clips[0])
    player.sample(0)
    first=mesh.lods[0].positions.copy()
    player.sample(player.clip.duration*.7)
    displacement=np.linalg.norm(mesh.lods[0].positions-first,axis=1)
    assert displacement.max()>.01, 'No real bone deformation'
    assert np.isfinite(mesh.lods[0].positions).all()
    assert np.array_equal(bundle.mesh.lods[0].positions,lod.positions)
    state=SceneState(mesh=mesh,materials=bundle.materials,textures=bundle.textures,style='game')
    center,radius=mesh_bounds(mesh)
    state.camera.frame(center,radius,aspect=1.5)
    state.camera.yaw,state.camera.pitch=30,20
    renderer=OffscreenViewer(state)
    player.sample(0)
    a=renderer.render(900,600)
    Image.fromarray(a).save(out/'inspection-start.png')
    player.sample(player.clip.duration*.7)
    state.geometry_version+=1
    b=renderer.render(900,600)
    Image.fromarray(b).save(out/'inspection-open.png')
    assert not np.array_equal(np.asarray(a),np.asarray(b))
    devices=[r for r in gunsmith.parts('tactical') if '/Dev/' in r[0]]
    assert devices, 'Tactical devices missing'
    assert any('Laser' in r[0] for r in devices)
    os.environ['VERTEXVIEWER_VIEWER']='fallback'
    page=GunsmithPage()
    page.setAttribute(Qt.WA_DontShowOnScreen)
    basepath=next(p for p in loader.index() if p.endswith('/Rec_AR_M4A1-Std_001_3P.uasset'))
    base=loader.load_model(basepath)
    page.use_current(base,basepath)
    page._append_part(devices[0][0],'tactical')
    assert page._selected
    assert type(page._values['px']) is W.DoubleSpinBox
    page._values['px'].setValue(2.1234)
    page._values['sc'].setValue(.0123)
    assert page._selected.offset[0]==2.1234 and page._selected.scale==.0123
    page._sync_sliders()
    assert page._values['px'].value()==2.1234
    page._append_part(devices[1][0],'tactical')
    assert len([s for s in page.recipe.parts if s.slot=='tactical'])==2
    with tempfile.TemporaryDirectory() as directory:
        directory=Path(directory)
        obj=directory/'custom.obj'
        obj.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\nf 1/1 2/2 3/3\n')
        from unittest.mock import patch
        with patch.object(custom_parts,'library_dir',return_value=directory/'library'):
            local,imported=custom_parts.import_file(str(obj),'测试导入配件','tactical',.01,'Z')
            obj.unlink()
            loaded=custom_parts.load(local)
            assert np.array_equal(imported.mesh.lods[0].positions,loaded.mesh.lods[0].positions)
            assert custom_parts.rows()[0][1]=='测试导入配件'
            import trimesh
            from trimesh.visual.texture import TextureVisuals
            from trimesh.visual.material import SimpleMaterial
            geo=trimesh.Trimesh(vertices=[[0,0,0],[1,0,0],[0,1,0]],faces=[[0,1,2]],process=False)
            texture=Image.new('RGBA',(4,4),(180,20,50,255))
            geo.visual=TextureVisuals(uv=[[0,0],[1,0],[0,1]],material=SimpleMaterial(image=texture))
            glb=directory/'textured.glb'
            geo.export(glb)
            local_glb,glb_bundle=custom_parts.import_file(str(glb),'GLB贴图测试','other')
            assert glb_bundle.textures and glb_bundle.materials[0].base_color_texture
            assert np.array_equal(glb_bundle.textures[0].rgba,custom_parts.load(local_glb).textures[0].rgba)
            page._part_bundles[local]=loaded
            page._append_part(local,'tactical')
            recipe=gunsmith.Recipe.from_dict(page.recipe.to_dict())
            assert recipe.parts[-1].vpath==local
            page._rebuild()
    inspection=InspectionPage()
    inspection.setAttribute(Qt.WA_DontShowOnScreen)
    inspection.resize(1400,900)
    inspection.set_bundle(bundle,path,autoplay=False)
    inspection.show()
    app.processEvents()
    inspection.clips=clips
    inspection.segment.addItem(clips[0].name)
    inspection._activate_clip(0)
    assert inspection.player is not None,inspection.status.text()
    inspection._pause()
    inspection._seek(clips[0].duration*.7)
    inspection.show(); app.processEvents()
    inspection.grab().save(str(out/'inspection-page.png'))
    page.resize(1500,960); page.show(); app.processEvents()
    assert page._values['px'].lineEdit().width()>50
    page.grab().save(str(out/'gunsmith-inputs.png'))
    inspection.shutdown()
    page.close(); inspection.close()
    result=dict(animation=asset,frames=len(clips[0].poses),max_displacement_m=float(displacement.max()),
                bones=lod.bones,tactical_devices=len(devices),numeric_precision=True,local_import=True)
    (out/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    return result


if __name__=='__main__': run(sys.argv[1] if len(sys.argv)>1 else 'work/inspection-validation')
