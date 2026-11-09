"""Exercise skin controls, real component export and the populated credits screen."""
import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np


def run_features(out, app, base_bundle, base_vpath):
    from PySide6.QtCore import QEventLoop, QRect, Qt, QTimer
    from app.credits import CreditsWindow,credit_entries
    from app.gunsmith_page import GunsmithPage
    from app.wizard import CONFIG
    from core import gunsmith as gs
    from core.features import SKINS_ENABLED
    from render.viewer import OffscreenViewer, SceneState, mesh_bounds

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait_until(predicate, timeout=4000):
        deadline = time.monotonic() + timeout / 1000
        while not predicate() and time.monotonic() < deadline:
            wait(40)
        assert predicate(), "动画没有在预期时间内结束"

    # Widget controls are tested with the software viewport; actual skin pixels
    # are captured separately through the real OpenGL renderer below.
    with patch.dict(os.environ, {"VERTEXVIEWER_VIEWER": "fallback"}):
        page = GunsmithPage()
    page.setAttribute(Qt.WA_DontShowOnScreen)
    page.resize(1680, 960)
    page.use_current(base_bundle, base_vpath)
    page._apply_official()
    assert page.recipe.parts, page.status.text()
    skin, skins = None, []
    if SKINS_ENABLED:
        from core import weapon_skins as ws
        skins = ws.list_skins(base_vpath)
        skin = next((s for s in skins if s.name == "HavvkTech_p9"),
                    next(s for s in skins if not s.is_default and s.part_count))
        selected = next(i for i in range(page.skin_combo.count()) if page.skin_combo.itemData(i) == skin.id)
        page.skin_combo.setCurrentIndex(selected)
        page.btn_skin.click()
        assert page.recipe.skin_id == skin.id, page.status.text()
        assert page.recipe.base == skin.base
        assert page.skin_parts_switch.isChecked()
        assert any(p.vpath.lower().startswith(skin.kit_dir.lower()) for p in page.recipe.parts)
    else:
        assert page.skin_controls.isHidden() and not page.btn_skin.isEnabled()
    saved = gs.Recipe.from_dict(page.recipe.to_dict())
    assert saved.to_dict() == page.recipe.to_dict()
    page.show()
    wait(100)
    page.grab().save(str(out / "gunsmith-controls.png"))

    parent = out / "parts-export"
    parent.mkdir(parents=True, exist_ok=True)
    previous_manifests = set(parent.rglob("*__parts_manifest.json"))
    with patch("app.gunsmith_page.QFileDialog.getExistingDirectory", return_value=str(parent)):
        page._export_parts()
    manifests = sorted(set(parent.rglob("*__parts_manifest.json")) - previous_manifests)
    assert manifests, page.status.text()
    manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
    assert not manifest["errors"], manifest["errors"]
    assert len(manifest["parts"]) == len(page.recipe.parts) + 1

    pairs = [(part, page._bundle_for(part.vpath)) for part in page.recipe.parts]
    combined = gs.assemble(page.base_bundle, pairs, base_vpath=page.recipe.base)
    lod = combined.mesh.lods[0]
    assert sum(row["triangles"] for row in manifest["parts"]) == lod.triangle_count
    vertices = []
    for row in manifest["parts"]:
        obj = manifests[-1].parent / row["obj"]
        vertices.extend([list(map(float, line.split()[1:])) for line in obj.read_text().splitlines()
                         if line.startswith("v ")])
        assert (manifests[-1].parent / row["mtl"]).is_file()
    expected = np.unique(np.round(np.asarray(lod.positions, dtype=np.float64), 6), axis=0)
    actual = np.unique(np.round(np.asarray(vertices), 6), axis=0)
    assert actual.shape == expected.shape, (actual.shape, expected.shape)
    assert np.allclose(actual, expected, atol=1e-6)

    state = SceneState(mesh=combined.mesh, materials=combined.materials,
                       textures=combined.textures, style="game")
    center, radius = mesh_bounds(combined.mesh)
    state.camera.frame(center, radius, aspect=1280 / 720)
    state.camera.yaw, state.camera.pitch = 0, 8
    state.camera.distance *= .66
    viewer = OffscreenViewer(state)
    viewer.capture(str(out / "assembly.png"), 1280, 720)
    viewer.release()
    page.hide()
    page.deleteLater()

    config = Path(CONFIG)
    config_before = config.read_bytes() if config.exists() else None
    credits = CreditsWindow()
    credits.setAttribute(Qt.WA_DontShowOnScreen)
    credits.start()
    native = QRect(credits.geometry())
    wait_until(lambda: credits._opened)
    assert credits.geometry() == native, "感谢名单改变了原生窗口尺寸"
    assert credits.entries == credit_entries() and credits.bg.row_count() == 3
    credits.grab().save(str(out / "credits.png"))
    credits.back_button.click()
    wait_until(lambda: not credits.isVisible())
    assert config_before == (config.read_bytes() if config.exists() else None), "配置文件被修改"
    credits.deleteLater()
    return {"skins_enabled": SKINS_ENABLED, "skin": skin.name if skin else "原版",
            "skin_options": len(skins), "skin_controls": SKINS_ENABLED,
            "official_skin_parts": len(pairs), "recipe_roundtrip": True,
            "independent_parts_exported": len(manifest["parts"]), "part_export_errors": [],
            "export_positions_match_preview": True, "credits_count": len(credits.entries),
            "credits_rows": 3, "credits_settings_unchanged": True}
