"""Focused first-person and full-assembly UI check on one real gun and chess prop."""
from pathlib import Path
import json,os,sys,time
from unittest.mock import patch
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def run(out):
    from PySide6.QtCore import Qt,QEventLoop,QTimer
    from PySide6.QtWidgets import QApplication
    from fluentpy import widgets as W
    from core import loader,gunsmith as gs
    from core.inspection_catalog import playable_animations,inspection_catalog
    from core.inspection import decode_animation,sample_pose,world_matrices
    from core.inspection_scene import load_companion,InspectionScene
    from app.gunsmith_page import GunsmithPage
    from render.viewer import SceneState,OffscreenViewer
    from PIL import Image
    from core.version import stamp
    import threading
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    app=QApplication.instance() or QApplication([]);app.setQuitOnLastWindowClosed(False)
    from app.fluent_api import apply_fluent_theme,apply_dark_palette
    apply_fluent_theme(True);apply_dark_palette(app,True)
    os.environ['VERTEXVIEWER_VIEWER']='fallback'
    def wait_until(check,timeout=150):
        deadline=time.monotonic()+timeout
        while not check() and time.monotonic()<deadline:
            loop=QEventLoop();QTimer.singleShot(20,loop.quit);loop.exec()
        assert check(),'检视验证超时'
    cat=loader.catalog()
    prop=next(p for p,c in cat.items() if 'Chess_1148/' in p and c=='SkeletalMesh' and '_1P_' in p)
    action=next(p for p in cat if 'Chess_1148/' in p and '/Weapon/' in p and p.endswith('_1P.uasset'))
    bundle=loader.load_model(prop)
    record=load_companion(dict(clips=decode_animation(action),bundle=bundle,path=prop,animation=action),prop,inspection_catalog(),threading.Event())
    hands=record['hands'];assert hands,record.get('hands_note')
    scene=InspectionScene(bundle,record['clips'][0],hands['bundle'],hands['tracks'][0])
    from exporters.animation_glb import export_animation
    export_animation(bundle,scene.clip,out/'chess-inspection.glb',hands=hands['bundle'],track=scene.track)
    expected={}
    for i,seconds in enumerate((.7,3.8)):
        scene.sample(seconds)
        socket=scene._body_world[scene.track['socket']]
        root=world_matrices(sample_pose(scene.clip,seconds),scene.clip.parents)[0]
        np.testing.assert_allclose(socket @ scene._mount_offset @ root,socket,atol=2e-4,
                                   err_msg='物品根骨骼朝向被重复叠加')
        positions=scene.display.mesh.lods[0].positions
        expected['frame'+str(i)]=positions[:,[0,2,1]]*[1,-1,1]
    np.savez_compressed(out/'chess-expected-blender.npz',**expected)
    scene.sample(2.5);first=scene.camera_pose();scene.sample(3.8);second=scene.camera_pose()
    assert first is not None and second is not None
    assert not np.allclose(first[1],second[1]),'相机未跟随检视动作'
    state=SceneState(mesh=scene.display.mesh,materials=scene.display.materials,textures=scene.display.textures,style='game')
    state.camera.set_first_person(second)
    renderer=OffscreenViewer(state)
    Image.fromarray(renderer.render(1200,800)).save(out/'chess-first-person.png')
    renderer.release()
    del renderer,state,scene,bundle,record,hands

    gun=next(p for p in cat if p.endswith('/Rec_AR_M4A1-Std_001_3P.uasset'))
    base=loader.load_model(gun,want_textures=False)
    before=base.mesh.lods[0].positions.copy()
    specs=gs.official_loadout(gun)
    assert len(specs)>=4
    page=GunsmithPage();page.setAttribute(Qt.WA_DontShowOnScreen)
    page.resize(1580,950);page.use_current(base,gun)
    page.recipe.parts=specs
    for spec in specs:page._part_bundles[spec.vpath]=loader.load_model(spec.vpath,want_textures=False)
    # Exercise custom position/scale as well as the exact official socket plan.
    specs[-1].offset=(.002,.001,-.003)
    page._refresh_labels();page._rebuild();page.show();app.processEvents()
    expected=gs.assemble(base,[(s,page._part_bundles[s.vpath]) for s in specs],base_vpath=gun)
    rows=playable_animations(gun)
    rows=[r for r in rows if r[0].endswith('/AR_M_1P_Inspect.uasset')]
    assert len(rows)==1
    assert type(page.btn_inspect) is W.AccentButton
    assert type(page.preview_stack) is W.AnimatedStackedWidget
    with patch('app.inspection_page.playable_animations',return_value=rows):
        page.btn_inspect.click()
        wait_until(lambda:page._inspection_worker is None)
        assert page._inspection_active,page.status.text()
        wait_until(lambda:page.inspection._worker is None)
    viewer=page.inspection
    assert viewer.player is not None,viewer.status.text()
    assert viewer.player.body is not None
    assert viewer.player.source.inspection_assembly
    assert len(viewer.player.source.inspection_parts)==len(specs)
    np.testing.assert_allclose(viewer.player.source.mesh.lods[0].positions,expected.mesh.lods[0].positions,atol=1e-6)
    assert viewer.player.camera_pose() is not None and viewer.view_mode.currentIndex()==0
    viewer._pause();viewer._seek(2.5)
    assert viewer.player.display.mesh.lods[0].vertex_count>expected.mesh.lods[0].vertex_count
    viewer.view_mode.setCurrentIndex(1)
    assert viewer.viewport.inner._first_person is None
    viewer.view_mode.setCurrentIndex(0)
    assert viewer.viewport.inner._first_person is not None
    page.grab().save(str(out/'gunsmith-inspection-ui.png'))
    target=out/'gunsmith-inspection.glb'
    pose=viewer.player.camera_pose()
    (out/'expected-camera.json').write_text(json.dumps(dict(seconds=2.5,eye=pose[0].tolist(),forward=pose[1].tolist(),up=pose[2].tolist())))
    with patch('PySide6.QtWidgets.QFileDialog.getSaveFileName',return_value=(str(target),'GLB')):
        viewer.export_button.click();wait_until(lambda:viewer._export_worker is None)
    assert target.is_file() and '导出成功' in viewer.export_notice.detail()
    assert any(s['slot']=='mag' and s['bone'].casefold()=='mag_point' for s in viewer.player.source.inspection_parts)
    # An edit invalidates prepared/playing animation, without altering the recipe.
    page._rebuild()
    assert page.preview_stack.currentIndex()==0 and not page._inspection_active and viewer.player is None
    np.testing.assert_array_equal(base.mesh.lods[0].positions,before)
    page.btn_inspect.click();page._rebuild()
    wait_until(lambda:page._inspection_worker is None)
    assert not page._inspection_active and page.preview_stack.currentIndex()==0 and viewer.player is None
    page.shutdown();page.close();app.processEvents()
    report=dict(version=stamp(),camera_follows_game_socket=True,first_person_default=True,
                item_root_frame_corrected=True,chess_body_socket_aligned=True,chess_animation_export=True,
                free_view_switch=True,gunsmith_real_ui_button=True,parts=len(specs),
                attachments_preserved=True,magazine_bound_to_animated_bone=True,
                custom_offsets_preserved=True,gunsmith_glb_export=True,edit_returns_to_assembly=True)
    (out/'first-person-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(run(sys.argv[1] if len(sys.argv)>1 else 'work/first-person-source'))
