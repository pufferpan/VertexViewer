"""Verify inspectable-only browsing, rig eligibility and decoded action filtering."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import hashlib
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(out):
    from PySide6.QtCore import Qt, QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    from fluentpy import widgets as W
    from core import loader
    from core.inspection import related_animations, decode_animation
    from core.inspection_catalog import InspectionCatalog, inspectable_paths, inspection_catalog
    from app.browser import ModelBrowser, is_model_asset
    from app.inspection_page import InspectionPage, _Worker

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    from app.fluent_api import apply_dark_palette, apply_fluent_theme
    apply_fluent_theme(True)
    apply_dark_palette(app, True)
    os.environ['VERTEXVIEWER_VIEWER'] = 'fallback'

    # Folder proximity must never admit another rig, an additive action, or a
    # single-frame pose. A skin with its own rig must keep that rig's actions.
    root = '../../../DeltaForce/Content/Models/Props/Case_1001/'
    mesh, other = root+'Case_1001_UI.uasset', root+'Case_1001_1P.uasset'
    names = ('Open', 'WrongRig', 'Additive', 'Pose', 'Unreadable')
    actions = [root+'Animation/Case_1001_'+name+'.uasset' for name in names]
    catalog = {mesh:'SkeletalMesh', other:'SkeletalMesh', **{p:'AnimSequence' for p in actions}}
    values = {p:dict(skeleton='case-rig', additive=False, frames=30, duration=1.) for p in catalog}
    values[other] = dict(values[other], skeleton='other-rig')
    values[actions[1]] = dict(values[actions[1]], skeleton='other-rig')
    values[actions[2]] = dict(values[actions[2]], additive=True)
    values[actions[3]] = dict(values[actions[3]], frames=1)
    values[actions[4]] = None
    with tempfile.TemporaryDirectory() as directory:
        with patch.dict(os.environ, {'LOCALAPPDATA':directory}):
            index = InspectionCatalog(catalog, directory)
            with patch.object(index, 'metadata', side_effect=values.get):
                assert [r[0] for r in index.animations(mesh)] == actions[:1]

    real_catalog = loader.catalog()
    first = next(p for p,c in real_catalog.items() if 'AnaisCaseEX_1693/' in p and 'Mesh' in c)
    second = next(p for p,c in real_catalog.items() if 'Nest_01egg/' in p and 'Mesh' in c)
    negative = next(p for p,c in real_catalog.items() if c in ('StaticMesh','SkeletalMesh')
                    and is_model_asset(p) and not related_animations(p))
    subset = [first, second, negative]
    non_mesh = related_animations(first)[0][0]
    progress = []
    eligible = inspectable_paths(subset+[non_mesh],progress=lambda i,n:progress.append((i,n)))
    assert eligible == {first,second}, eligible
    assert progress[-1][1] == len(subset), 'Non-mesh files entered the model eligibility scan'

    browser = ModelBrowser(auto_build=False)
    browser.setAttribute(Qt.WA_DontShowOnScreen)
    browser.resize(510,1000)
    browser._on_index(subset, '', eligible)
    assert type(browser.inspect_only) is W.CheckBox and browser.inspect_only.isChecked()
    assert {browser._rel_to_path[r] for r in browser._visible_rels()} == eligible
    assert {r['vpath'] for r in browser._card_items} == eligible
    selected = []
    browser.modelActivated.connect(selected.append)
    assert browser.select_first_model() in eligible and selected[-1] in eligible
    browser.search.setText(Path(negative).stem)
    assert not browser._card_items, 'Search exposed a non-inspectable model'
    browser.inspect_only.setChecked(False)
    assert {r['vpath'] for r in browser._card_items} == {negative}
    browser.search.clear()
    assert len(browser._visible_rels()) == 3
    browser.inspect_only.setChecked(True)
    browser._toggle_view()

    def tree_files(item):
        kind, path = item.data(0,Qt.UserRole)
        if kind == 'file': return {path}
        browser._on_expand(item)
        return set().union(*(tree_files(item.child(i)) for i in range(item.childCount())))

    leaves = set().union(*(tree_files(browser.tree.topLevelItem(i)) for i in range(browser.tree.topLevelItemCount())))
    assert leaves == eligible, leaves
    for category in {m['cat'] for m in browser._meta.values()}:
        browser._set_category(category)
        assert {browser._rel_to_path[r] for r in browser._visible_rels()} <= eligible
    browser._set_category('all')
    browser._toggle_view()
    browser.show()
    app.processEvents()
    browser.grab().save(str(out/'inspectable-library.png'))

    page = InspectionPage(SimpleNamespace(browser=browser))
    page.setAttribute(Qt.WA_DontShowOnScreen)
    with patch('app.inspection_page.asset_picker', return_value=SimpleNamespace(exec=lambda:False)) as picker:
        page._pick_model()
        assert {r[0] for r in picker.call_args.args[1]} == eligible

    # Exercise the actual SkinPlayer rejection of decoded clips; matching asset
    # metadata alone is insufficient to put an action in the visible list.
    bundle = loader.load_model(first)
    asset = inspection_catalog().animations(first)[0][0]
    clip = decode_animation(asset)[0]
    good2, additive, wrong, corrupt = [root+'Animation/'+name+'.uasset'
                                      for name in ('Second','Additive','WrongRig','Corrupt')]
    decoded = {asset:[clip], good2:[clip], additive:[replace(clip,additive=True)],
               wrong:[replace(clip,bones=['different-rig-'+str(i) for i in range(len(clip.bones))])]}

    def decode(path, cancel):
        if path == corrupt: raise ValueError('Invalid animation data')
        return decoded[path]

    worker = _Worker(asset,bundle=bundle,model_path=first,candidates=[asset,additive,wrong,corrupt,good2])
    responses = []
    worker.ready.connect(lambda result,error: responses.append((result,error)))
    with patch('app.inspection_page.decode_animation',side_effect=decode), \
         patch('app.inspection_page.related_models',return_value=[]):
        worker.run()
    result,error = responses[0]
    assert not error and {r['animation'] for r in result['playable']} == {asset,good2}
    page.set_bundle(bundle,first,autoplay=False)
    page._rows = [(p,Path(p).stem,'AnimSequence','','') for p in [asset,good2,additive,wrong,corrupt]]
    page._filter()
    assert page.table.rowCount() == 0, 'Unverified actions were exposed'
    availability = []
    page.availabilityChanged.connect(lambda p,n:availability.append((p,n)))
    page._ready(result,'',asset,False)
    page._pause()
    assert {r[0] for r in page._shown} == {asset,good2} and page.table.rowCount() == 2
    assert availability[-1] == (first,2)
    page.table.selectRow(1)
    page._load_selected()
    page._pause()
    assert page.player is not None
    browser.reject_inspection(second)
    assert second not in {browser._rel_to_path[r] for r in browser._visible_rels()}
    page.shutdown()
    page.close()
    browser.shutdown()
    browser.close()

    # Exercise the actual startup worker and its completion signal against the
    # full library, including the large number of non-mesh assets in list_models.
    library = ModelBrowser()
    library.setAttribute(Qt.WA_DontShowOnScreen)
    library.resize(680,1000)
    library.show()
    deadline = time.monotonic()+90
    try:
        while not library.is_ready and time.monotonic()<deadline:
            loop = QEventLoop()
            QTimer.singleShot(25,loop.quit)
            loop.exec()
        assert library.is_ready and not library._error, library.count_label.text()
        visible = {library._rel_to_path[r] for r in library._visible_rels()}
        assert visible and visible<=library._inspectable_paths and len(visible)<library.count
        assert all(r['vpath'] in visible for r in library._card_items)
        library.grab().save(str(out/'full-inspectable-library.png'))
        total, filtered = library.count, len(visible)
    finally:
        library.shutdown()
        library.close()

    # The background eligibility index and foreground model loader share archive
    # handles. Concurrent real reads must match their serial byte-for-byte data.
    siblings = list(dict.fromkeys([first, second, asset] +
                    list(loader.siblings(first).values()) + list(loader.siblings(asset).values())))[:8]
    assert len(siblings) >= 3
    expected = {p:hashlib.sha256(loader.read_entry(p)).digest() for p in siblings}
    with ThreadPoolExecutor(max_workers=6) as pool:
        actual = list(pool.map(lambda p:(p,hashlib.sha256(loader.read_entry(p)).digest()), siblings*4))
    assert all(digest == expected[p] for p,digest in actual)
    report = dict(default_filter=True, search_filter=True, directory_filter=True,
                  category_filter=True, picker_filter=True, invalid_clips_hidden=True,
                  skeleton_filter=True, additive_filter=True, concurrent_archive_reads=len(actual),
                  startup_worker=True, all_models=total, inspectable_models=filtered)
    (out/'filter-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)
    return report


if __name__ == '__main__': run(sys.argv[1] if len(sys.argv)>1 else 'work/inspection-filter-validation')
