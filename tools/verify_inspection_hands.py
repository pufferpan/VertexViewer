"""Bounded real-resource/UI smoke check; no full-library or HD-character loads."""
from pathlib import Path
import json
import os
import sys
import time
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def run(out):
    import numpy as np
    from PySide6.QtCore import QEventLoop,QTimer,Qt
    from PySide6.QtWidgets import QApplication
    from fluentpy import widgets as W
    from app.inspection_page import InspectionPage
    from core import loader
    from core.inspection_scene import companion_candidates
    from core.inspection_catalog import inspection_catalog
    from core.version import stamp

    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    os.environ['VERTEXVIEWER_VIEWER']='fallback'
    def wait_until(check,timeout=90):
        end=time.monotonic()+timeout
        while not check() and time.monotonic()<end:
            loop=QEventLoop();QTimer.singleShot(20,loop.quit);loop.exec()
        assert check(),'检视界面验证超时'

    cat=loader.catalog()
    path=next(p for p,c in cat.items() if c=='SkeletalMesh' and p.endswith('Geiger_1471_C_1P_Skin.uasset'))
    asset=next(p for p in cat if '/Porps_Tactical_Geiger_1471/Weapon/' in p and '_1P_Loop.' in p)
    source=loader.load_model(path)
    before=source.mesh.lods[0].positions.copy()
    page=InspectionPage();page.setAttribute(Qt.WA_DontShowOnScreen)
    page.resize(1450,900);page.set_bundle(source,path,autoplay=False);page.show()
    page._start(asset,candidates=[asset])
    wait_until(lambda:page._worker is None)
    assert page.player is not None,page.status.text()
    assert page.player.body is not None,page.status.text()
    assert page.view_mode.currentIndex()==0 and page.player.camera_pose() is not None
    assert page._playing
    assert type(page.show_hands) is W.CheckBox and type(page.export_button) is W.AccentButton
    page._pause();page._seek(0)
    bind=page.player.display.mesh.lods[0].positions.copy()
    page._seek(.5)
    assert np.max(np.linalg.norm(page.player.display.mesh.lods[0].positions-bind,axis=1))>.001
    page.grab().save(str(out/'inspection-hands-ui.png'))
    paired=page.player
    target=out/'inspection-with-hands.glb'
    with patch('PySide6.QtWidgets.QFileDialog.getSaveFileName',return_value=(str(target),'GLB')):
        page.export_button.click()
        wait_until(lambda:page._export_worker is None)
    assert target.is_file() and target.stat().st_size>1000
    assert '导出成功' in page.export_notice.detail()
    page.show_hands.setChecked(False)
    assert page.player.body is None and page.player.display.mesh.lods[0].vertex_count==source.mesh.lods[0].vertex_count
    page.show_hands.setChecked(True)
    assert page.player.body is not None
    np.testing.assert_array_equal(source.mesh.lods[0].positions,before)
    page.begin_selection('different-model')
    assert page.player is None and not page.export_button.isEnabled() and page.segment.count()==0
    page.shutdown();page.close();app.processEvents()
    # Guns use shared body tracks outside the item's folder, including assets
    # omitted by the legacy catalog. Verify that actual pak discovery finds it.
    gun=next(p for p in cat if p.endswith('/Rec_AR_M4A1-Std_001_3P.uasset'))
    action=next(p for p in cat if '/Rec_AR_M4A1-Std_001/' in p and p.endswith('/AR_M_1P_Inspect.uasset'))
    candidates=companion_candidates(gun,action,inspection_catalog())
    assert any('/Guns/AR/' in p for p in candidates),candidates
    from core.inspection import decode_animation,SkinPlayer
    body=decode_animation(candidates[0])[0]
    assert not body.additive and abs(body.duration-5.4)<.01 and abs(body.fps-60)<.01
    SkinPlayer(paired.hands_source.mesh,body)
    from exporters.animation_glb import export_animation
    export_animation(source,paired.clip,out/'inspection-item-only.glb')
    report=dict(version=stamp(),paired_body_item=True,animated_hand_socket=True,native_controls=True,
                source_immutable=True,model_switch_clears_hands=True,ui_export=True,
                item_only_export=True,shared_weapon_body_found=True,resolved_additive_body=True,
                weapon_fps=body.fps,bytes=target.stat().st_size)
    (out/'inspection-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(run(sys.argv[1] if len(sys.argv)>1 else 'work/inspection-hands-source'))
