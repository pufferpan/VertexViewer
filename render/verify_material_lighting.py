"""Verify material lighting without a window; optionally compare a real gun.

Run ``python render/verify_material_lighting.py --real-model`` to capture the
M4A1 receiver using the same lighting as the viewer. The no-light and diffuse
energy checks use linear framebuffer values, before tone mapping and grain.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from OpenGL import GL
from PySide6.QtWidgets import QApplication
from core.types import Material, Mesh, MeshLOD, Section, Texture
from render import viewer as renderer
from render.viewer import OffscreenViewer, SceneState, mesh_bounds


def linear_center(viewer: OffscreenViewer) -> np.ndarray:
    viewer.render(128, 128)
    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, viewer.renderer._resolve_fbo)
    pixel = np.zeros((1, 1, 4), np.float32)
    GL.glReadPixels(64, 64, 1, 1, GL.GL_RGBA, GL.GL_FLOAT, pixel)
    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
    return pixel[0, 0, :3].astype(float)


def flat_state() -> SceneState:
    lod = MeshLOD(
        positions=np.array([[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]], np.float32),
        normals=np.array([[0, 0, 1]] * 4, np.float32),
        uvs=np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32),
        indices=np.array([0, 1, 2, 0, 2, 3], np.uint32),
        sections=[Section(material_path="surface", num_triangles=2)],
    )
    state = SceneState(mesh=Mesh(lods=[lod]), materials=[Material(
        pak_path="surface", base_color=(0.25, 0.12, 0.04, 1.0), roughness=1.0,
    )])
    state.camera.yaw = state.camera.pitch = 0
    state.camera.distance = 3
    state.lighting.shadow = False
    state.lighting.ambient_top = state.lighting.ambient_bottom = (0, 0, 0)
    state.lighting.env_intensity = 0
    for light in state.lighting.lights:
        light.intensity = 0
    return state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-model", action="store_true")
    parser.add_argument("--baseline-shader", type=Path)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    out = ROOT / "work/fix-20261101/lighting"
    out.mkdir(parents=True, exist_ok=True)
    report = {}
    state = flat_state()
    view = OffscreenViewer(state)
    try:
        dark = linear_center(view)
        assert np.max(dark) < 1e-6, dark
        state.lighting.key.set_direction((0, 0, 1))
        state.lighting.key.intensity = 1
        state.lighting.key.color = (1, 1, 1)
        state.lighting.key.angle = 0
        state.style = "pbr"
        lit = linear_center(view)
        # Lambert's 1/pi must not be cancelled: radiance 1 cannot turn this
        # rough dielectric into a self-lit copy of its albedo.
        expected = np.array([.25, .12, .04]) * .96 / np.pi + .04 / (4 * np.pi)
        assert np.allclose(lit, expected, atol=6e-4), (lit, expected)
        state.materials[0].base_color = (0, 0, 0, 1)
        black = linear_center(view)
        # Real dielectric Fresnel reflections remain visible on black paint.
        assert np.all(black > 0), black
        assert np.max(black) < .004, black
        # An untextured dynamic UI surface cannot be reconstructed from static
        # game assets. It must not become a white sheet over the actual model.
        state.materials[0].blend_mode = "Masked"
        state.materials[0].base_color = (1, 1, 1, 1)
        state.mesh_version += 1
        overlay_hidden = view.render(128, 128)
        state.mesh = None
        state.mesh_version += 1
        background = view.render(128, 128)
        assert np.array_equal(overlay_hidden, background)
        report.update(unlit_game_linear=dark.tolist(), rough_diffuse_linear=lit.tolist(),
                      expected_diffuse_linear=expected.tolist(), black_fresnel_linear=black.tolist(),
                      textureless_ui_overlay_hidden=True)
        masked = flat_state()
        masked.style = "pbr"
        masked.materials[0].emissive = (.1, .8, .03)
        masked.materials[0].emissive_texture = "emission-mask"
        tex = Texture(pak_path="emission-mask", width=2, height=2,
                      rgba=np.zeros((2, 2, 4), np.uint8))
        masked.textures = [tex]
        masked.mesh_version, masked.texture_version = 10, 10
        view.state = masked
        masked_black = linear_center(view)
        assert np.max(masked_black) < 1e-6, masked_black
        tex.rgba = np.full((2, 2, 4), 255, np.uint8)
        masked.texture_version += 1
        masked_white = linear_center(view)
        assert np.allclose(masked_white, (.1, .8, .03), atol=.001), masked_white
        report.update(black_emission_mask_linear=masked_black.tolist(),
                      white_emission_mask_linear=masked_white.tolist())
        if args.real_model:
            from core import loader
            vpath = next(p for p in loader.index() if p.endswith("Rec_AR_M4A1-Std_001_3P.uasset"))
            bundle = loader.load_model(vpath)
            state = SceneState(mesh=bundle.mesh, materials=bundle.materials, textures=bundle.textures)
            center, radius = mesh_bounds(bundle.mesh)
            state.camera.frame(center, radius, aspect=1.5)
            state.camera.yaw, state.camera.pitch = 0, 5
            state.camera.distance *= .7
            view.state = state
            view.capture(str(out / "m4a1-after.png"), 1440, 960)
            report["model"] = vpath
            report["texture_sizes"] = [[t.name, t.width, t.height] for t in bundle.textures]
            # Textureless masked/transparent UI overlays should already be
            # skipped, but the opaque receiver itself must remain visible.
            report["hidden_ui_overlays"] = [m.name for m in bundle.materials if m.is_untextured_overlay]
            if args.baseline_shader:
                baseline = args.baseline_shader.read_text(encoding="utf-8")
                original_source = renderer._shader_source
                with patch.object(renderer, "_shader_source", side_effect=lambda name:
                                  baseline if name == "scene.frag" else original_source(name)):
                    old_program = view.renderer.programs["scene"]
                    prog = view.renderer._build_program("baseline", "scene.vert", "scene.frag")
                    view.renderer.programs["scene"] = prog
                    view.renderer._loc[prog] = {}
                view.capture(str(out / "m4a1-before.png"), 1440, 960)
                view.state = flat_state()
                report["baseline_unlit_game_linear"] = linear_center(view).tolist()
                GL.glDeleteProgram(prog)
                view.renderer.programs["scene"] = old_program
    finally:
        view.release()
    (out / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
