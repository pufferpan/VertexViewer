"""Exercise the same bundled resources and native libraries as the delivered EXE.

VertexViewer.exe --verify-release <output-directory> writes screenshots and JSON;
it never changes the first-run settings.
"""
import json
import sys
import traceback
from pathlib import Path


def run(output):
    out = Path(output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = {"frozen": bool(getattr(sys, "frozen", False)), "errors": []}
    try:
        from PySide6.QtCore import QEventLoop, QTimer, Qt
        from PySide6.QtWidgets import QApplication
        from app.wizard import WizardWindow
        from core import loader
        from core.texture import inspect_texture, load_texture
        from core.version import stamp
        from render.viewer import OffscreenViewer, SceneState, mesh_bounds
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        from app.fluent_api import apply_dark_palette, apply_fluent_theme
        apply_fluent_theme(True)
        apply_dark_palette(app, True)
        report["version"] = stamp()

        wizard = WizardWindow()
        wizard.setAttribute(Qt.WA_DontShowOnScreen)
        wizard.start()
        loop = QEventLoop()
        QTimer.singleShot(3800, loop.quit)
        loop.exec()
        report["wizard_rows"] = wizard.bg.row_count()
        report["wizard_intro_finished"] = not wizard._intro
        wizard.grab().save(str(out / "wizard.png"))
        assert report["wizard_rows"] == 3 and report["wizard_intro_finished"]
        wizard.hide()

        paths = loader.index()
        import numpy as np
        report['operators'] = []
        for stem in ('M_Kai_Haavk_049_Body_3P_HD', 'F_Luna_SOL_013_Body_UI_HD',
                     'M_Elio_7DL9D_9j_A_Body_3P_HD', 'M_C204_Upper_1P_HD'):
            path = next(p for p in paths if p.endswith('/'+stem+'.uasset'))
            operator = loader.load_model(path)
            mesh = operator.mesh
            assert mesh.source_format == 'UE/DF-skeletal-sections', (stem,mesh.source_format)
            assert len(mesh.lods) >= 1 and mesh.material_paths
            materials = {m.pak_path:m for m in operator.materials}
            for lod in mesh.lods:
                assert all(s.material_path in materials for s in lod.sections)
                assert sum(s.num_triangles for s in lod.sections) == lod.triangle_count
            entry = {'model':stem,'lods':len(mesh.lods),'materials':len(materials),
                     'sections':[len(l.sections) for l in mesh.lods]}
            report['operators'].append(entry)
            if stem == 'F_Luna_SOL_013_Body_UI_HD':
                lower = next(m for m in operator.materials if m.name.endswith('Lower_MT'))
                assert '/F_Luna_014_HD/Textures/F_Luna_014_Lower_C.uasset' in lower.base_color_texture
                entry['shared_lower_texture'] = lower.base_color_texture
            if stem in ('M_Kai_Haavk_049_Body_3P_HD','F_Luna_SOL_013_Body_UI_HD'):
                op_state = SceneState(mesh=mesh, materials=operator.materials,
                                      textures=operator.textures,style='game')
                center,radius=mesh_bounds(mesh)
                op_state.camera.frame(center,radius,aspect=1.5)
                op_state.camera.yaw,op_state.camera.pitch=32,12
                op_viewer=OffscreenViewer(op_state)
                op_viewer.capture(str(out/('operator-'+stem+'.png')),1200,800)
                op_viewer.release()
        report["weapon_index_fix"] = []
        for stem in ("FroG_Pic_Mag-AFG_003", "Other_KACrailcover3_068", "Sto_A_CoreCP_023"):
            path = next(p for p in paths if p.endswith("/" + stem + "_3P.uasset"))
            lod = loader.load_mesh(path).lods[0]
            triangles = lod.indices.reshape(-1, 3)
            p = lod.positions[triangles].astype(np.float64)
            faces = np.cross(p[:, 1]-p[:, 0], p[:, 2]-p[:, 0])
            lengths = np.linalg.norm(faces, axis=1)
            normals = lod.normals[triangles].mean(axis=1)
            normals /= np.maximum(np.linalg.norm(normals, axis=1)[:, None], 1e-9)
            valid = lengths > 1e-10
            median_dot = float(np.median(np.sum(faces[valid] / lengths[valid, None] * normals[valid], axis=1)))
            report["weapon_index_fix"].append({"part": stem, "triangles": lod.triangle_count,
                                               "median_face_normal_dot": median_dot})
            assert median_dot > .9, report["weapon_index_fix"][-1]
        # A real official skin uses a mask to limit its green effect to a few
        # details. Losing that mask previously made the whole receiver glow.
        hk_path = next(p for p in paths if p.endswith("/Rec_AR_HK416_021_RecordAction_6b_3P.uasset"))
        hk = loader.load_model(hk_path, want_textures=False)
        hk_mat = hk.materials[0]
        report["skin_emission_mask"] = {
            "enabled": hk_mat.scalar_params.get("UseEmissiveColor"),
            "texture": hk_mat.emissive_texture,
        }
        assert hk_mat.scalar_params.get("UseEmissiveColor") == 1
        assert hk_mat.emissive_texture.endswith("/T_HK416_RecordAction_6b_Mask_HD.uasset")
        # This asset's HD sidecars failed in the previous packaged startup log.
        vp = next(p for p in paths if "BF_ADS_001/Texture/T_VMGen_BaseColorMap_" in p
                  and p.endswith(".uasset"))
        blobs = {}
        for kind, path in loader.siblings(vp).items():
            try:
                blobs[kind] = loader.read_entry(path)
            except Exception:
                report["errors"].append({"stage": kind, "traceback": traceback.format_exc()})
        info = inspect_texture(blobs.get("uasset", b""), blobs.get("uexp"),
                               blobs.get("ubulk"), blobs.get("uptnl"))
        tex = load_texture(blobs.get("uasset", b""), blobs.get("uexp"),
                           blobs.get("ubulk"), vp, blobs.get("uptnl"))
        report["hd_texture"] = {"source": info["source"], "chosen": info["chosen"],
                                "width": tex.width, "height": tex.height}

        vp = next(p for p in paths if p.endswith("Rec_AR_M4A1-Std_001_3P.uasset"))
        bundle = loader.load_model(vp)
        report["gun_textures"] = [{"name": t.name, "width": t.width, "height": t.height}
                                  for t in bundle.textures]
        state = SceneState(mesh=bundle.mesh, materials=bundle.materials, textures=bundle.textures,
                           style="game")
        center, radius = mesh_bounds(bundle.mesh)
        state.camera.frame(center, radius, aspect=1.5)
        state.camera.yaw, state.camera.pitch = 0, 5
        state.camera.distance *= .7
        viewer = OffscreenViewer(state)
        report["gl"] = viewer.gl_info
        report["anisotropy"] = viewer.renderer._anisotropy
        viewer.capture(str(out / "model.png"), 1440, 960)
        viewer.release()
        from tools.verify_feature_ui import run_features
        report["features"] = run_features(out, app, bundle, vp)
        from tools.verify_inspection_features import run as verify_inspection
        report["inspection"] = verify_inspection(out / "inspection")
        from tools.verify_inspection_binding import run as verify_binding
        report["inspection_binding"] = verify_binding(out / "inspection-binding")
        from tools.verify_inspection_filter import run as verify_filter
        report["inspection_filter"] = verify_filter(out / "inspection-filter")
        assert tex.width == 2048 and tex.height == 2048, report["hd_texture"]
        assert not report["errors"], report["errors"]
    except Exception:
        report["errors"].append({"stage": "verification", "traceback": traceback.format_exc()})
    (out / "release-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1]))
