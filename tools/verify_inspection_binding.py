"""Exercise actual selection signals, async stale results and per-item association."""
from pathlib import Path
from unittest.mock import patch
from threading import Event
import json
import os
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def run(out):
    from PySide6.QtCore import Qt, QEventLoop, QThread, QTimer, Signal
    from PySide6.QtWidgets import QApplication
    from fluentpy import widgets as W
    from core import loader
    from core.inspection import related_animations, decode_animation, belongs_to_model
    from app.inspection_page import InspectionPage
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    os.environ['VERTEXVIEWER_VIEWER']='fallback'

    def wait_until(check, timeout=20):
        deadline=time.monotonic()+timeout
        while not check() and time.monotonic()<deadline:
            loop=QEventLoop()
            QTimer.singleShot(15,loop.quit)
            loop.exec()
        assert check(), 'Selection/animation update timed out'

    shared='../../../DeltaForce/Content/Models/Props/Shared/'
    items={shared+'Prop_Case_1001_UI.uasset':'StaticMesh',
           shared+'Prop_Case_1002_UI.uasset':'StaticMesh',
           shared+'Animation/Prop_Case_1001_Open.uasset':'AnimSequence',
           shared+'Animation/Prop_Case_1002_Open.uasset':'AnimSequence'}
    matches=related_animations(shared+'Prop_Case_1001_UI.uasset',items)
    assert len(matches)==1 and '1001_Open' in matches[0][0]
    assert not belongs_to_model(shared+'SM_PhoneA_UI.uasset',shared+'Ani/PhoneB_Inspect.uasset')
    assert belongs_to_model(shared+'Prop_Case_1001_UI.uasset',shared+'Animation/1001/Open.uasset')
    assert not belongs_to_model(shared+'Prop_Case_1001_UI.uasset',shared+'Animation/1002/Open.uasset')
    assert belongs_to_model(shared+'Prop_Case_1001/Model/SK_Body.uasset',
                            shared+'Prop_Case_1001/Animation/Open.uasset')
    paths=loader.catalog()
    first=next(p for p,c in paths.items() if 'AnaisCaseEX_1693/' in p and 'Mesh' in c)
    second=next(p for p,c in paths.items() if 'Nest_01egg/' in p and 'Mesh' in c)
    bundles={p:loader.load_model(p) for p in (first,second)}
    animations={p:next(r[0] for r in related_animations(p) if '_Open.uasset' in r[0]) for p in bundles}
    clips={p:decode_animation(animations[p]) for p in bundles}

    # Real decoder and actual deformation automatically start on page selection.
    page=InspectionPage()
    page.setAttribute(Qt.WA_DontShowOnScreen)
    page.resize(1400,900)
    page.show()
    page.set_bundle(bundles[first],first)
    wait_until(lambda:page.player is not None and page._worker is None)
    assert page._playing and page.selection_vpath==first
    page.set_bundle(bundles[second],second)
    assert page.player is None and page.segment.count()==0
    wait_until(lambda:page.player is not None and page._worker is None)
    assert page._playing and page.selection_vpath==second
    assert all('Nest_01egg/' in row[0] for row in page._rows)
    assert not any('1693' in page.segment.itemText(i) for i in range(page.segment.count()))
    page.grab().save(str(out/'selected-model-animation.png'))
    page.shutdown();page.close()

    # A codec can complete just as a new model is clicked. Deliver an old result
    # deliberately after cancellation, then verify that only the new result wins.
    entered,release=Event(),Event()
    class DelayedAnimation(QThread):
        ready=Signal(object,str)
        def __init__(self,path,model=False,parent=None,**kwargs):
            super().__init__(parent)
            self.path=path;self.cancel=Event();self.source=kwargs['model_path']
        def run(self):
            if self.source==first:
                entered.set();release.wait(8)
            self.ready.emit(dict(clips=clips[self.source],bundle=None,path=self.source,
                                 animation=animations[self.source]),'')

    with patch('app.inspection_page._Worker',DelayedAnimation):
        page=InspectionPage()
        page.setAttribute(Qt.WA_DontShowOnScreen);page.show()
        page.set_bundle(bundles[first],first)
        wait_until(entered.is_set)
        page.set_bundle(bundles[second],second)
        assert page.player is None and page.selection_vpath==second
        release.set()
        wait_until(lambda:page._worker is None and page.player is not None)
        assert page.player.clip.name==clips[second][0].name
        page.set_bundle(bundles[first],shared+'NoAnimation_9999_UI.uasset')
        app.processEvents()
        assert page.player is None and page.segment.count()==0 and page.table.rowCount()==0
        page.shutdown();page.close()

    # Exercise the application's real model-activation and bundleChanged wiring.
    entered,release=Event(),Event()
    class DelayedModel(QThread):
        done=Signal(str,object,str)
        def __init__(self,cache,vpath,parent=None):
            super().__init__(parent);self.vpath=vpath
        def run(self):
            if self.vpath==first: entered.set();release.wait(8)
            self.done.emit(self.vpath,bundles[self.vpath],'')

    from app.main_window import VertexViewerWindow
    with patch('app.main_window._LoadWorker',DelayedModel):
        window=VertexViewerWindow(auto_build=False,viewer='fallback')
        window.setAttribute(Qt.WA_DontShowOnScreen)
        seen=[]
        window.bundleChanged.connect(lambda _:seen.append(window.current_vpath))
        window.browser.modelActivated.emit(first)
        wait_until(entered.is_set)
        window.browser.modelActivated.emit(second)
        release.set()
        wait_until(lambda:window._loader is None and window.current_vpath==second)
        assert seen==[second],seen
        assert window.inspection_page.selection_vpath==second
        assert all('Nest_01egg/' in row[0] for row in window.inspection_page._rows)
        assert type(window.inspector.inspect_btn) is W.Button
        assert window.inspector.inspect_btn.isEnabled()
        window.show();app.processEvents()
        window.inspector.inspect_btn.click()
        wait_until(lambda:window.inspection_page.player is not None)
        assert window.inspection_page.selection_vpath==second
        with patch.object(window.cache,'purge'):
            window.close()
        app.processEvents()

    result=dict(automatic_animation=True,selection_follows_library=True,latest_click_wins=True,
                stale_animation_ignored=True,unrelated_items_excluded=True,no_animation_clears_previous=True)
    (out/'binding-report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)
    return result


if __name__=='__main__':run(sys.argv[1] if len(sys.argv)>1 else 'work/inspection-binding-validation')
