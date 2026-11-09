"""Focused regressions for model loading, assembly and renderer sanitisation."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import gunsmith as gs, loader
from core.types import Material, Mesh, MeshLOD, Section, Texture
from render.viewer import prepare_lod, _as_texture_array


def triangle(**kwargs):
    fields = dict(positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32),
                  indices=np.array([0, 1, 2], np.uint32),
                  uvs=np.zeros((3, 2), np.float32),
                  sections=[Section(num_triangles=1, num_vertices=3)])
    fields.update(kwargs)
    return MeshLOD(**fields)


class ModelRegressions(unittest.TestCase):
    def test_merge_preserves_all_uv_channels_and_pads_from_uv0(self):
        a = triangle(uv_sets=np.array([[[0, 0], [.2, .7]]] * 3, np.float32))
        b = triangle(uvs=np.full((3, 2), .4, np.float32))
        merged, _ = gs.merge([(a, []), (b, [])])
        self.assertEqual(merged.uv_channel_count, 2)
        np.testing.assert_array_equal(merged.uv(1)[:3], a.uv(1))
        np.testing.assert_array_equal(merged.uv(1)[3:], b.uvs)

    def test_missing_material_does_not_shift_following_bindings(self):
        blue = Material(name="blue", base_color=(0, 0, 1, 1))
        merged, mats = gs.merge([(triangle(), []), (triangle(), [blue])])
        self.assertEqual(len(merged.sections), len(mats))
        self.assertEqual(mats[1].base_color, blue.base_color)

    def test_same_material_path_with_different_overrides_stays_independent(self):
        red = Material(name="same", pak_path="same", base_color=(1, 0, 0, 1))
        blue = Material(name="same", pak_path="same", base_color=(0, 0, 1, 1))
        lod = triangle(sections=[Section(material_path="same", num_triangles=1)])
        merged, mats = gs.merge([(lod, [red]), (lod, [blue])])
        self.assertNotEqual(merged.sections[0].material_path, merged.sections[1].material_path)
        self.assertEqual([m.base_color for m in mats], [red.base_color, blue.base_color])
        self.assertEqual(red.pak_path, "same")

    def test_invalid_part_indices_cannot_reach_another_part(self):
        bad = triangle(indices=np.array([0, 1, 3, 0, 1, 2]),
                       sections=[Section(num_triangles=2)])
        merged, _ = gs.merge([(bad, []), (triangle(), [])])
        np.testing.assert_array_equal(merged.indices, [0, 1, 2, 3, 4, 5])
        self.assertEqual([s.first_index for s in merged.sections], [0, 3])

    def test_renderer_drops_bad_triangles_and_keeps_section_offsets(self):
        lod = triangle(indices=np.array([0, 1, -1, 0, 1, 2, 0, 1, 99, 2, 1, 0]),
                       sections=[Section(material_path="a", first_index=0, num_triangles=2),
                                 Section(material_path="b", first_index=6, num_triangles=2)])
        prepared = prepare_lod(lod)
        np.testing.assert_array_equal(prepared.indices, [0, 1, 2, 2, 1, 0])
        self.assertEqual(prepared.ranges, [(0, 3, "a"), (3, 3, "b")])

    def test_missing_decoded_texture_is_a_valid_fallback(self):
        self.assertIsNone(_as_texture_array(Texture(name="missing", rgba=None)))
        self.assertIsNone(_as_texture_array(np.zeros((2, 2, 2), np.uint8)))
        rgba = _as_texture_array(np.full((2, 2, 3), np.nan))
        self.assertTrue(np.isfinite(rgba).all())

    def test_zero_first_index_is_explicit(self):
        lod = triangle(sections=[Section(num_triangles=1), Section(num_triangles=1)])
        self.assertEqual([s[3] for s in gs._section_ranges(lod)], [0, 0])

    def test_renderer_does_not_mutate_source_uv(self):
        lod = triangle(uv_sets=np.full((3, 2, 2), .2, np.float32))
        before = lod.uv_sets.copy()
        a = prepare_lod(lod, 1)
        b = prepare_lod(lod, 1)
        np.testing.assert_array_equal(a.uvs, b.uvs)
        np.testing.assert_array_equal(lod.uv_sets, before)

    def test_fresh_mesh_is_not_replaced_by_disk_uemodel(self):
        fresh = Mesh(name="fresh", lods=[triangle()])
        with patch.object(loader, "_MESH_CACHE", {}), \
             patch.object(loader, "load_blobs", return_value={"uasset": b"data"}), \
             patch("core.mesh.load_mesh_from_blobs", return_value=fresh), \
             patch("core.ueformat.read_uemodel", side_effect=AssertionError("stale cache read")):
            self.assertIs(loader.load_mesh("test/mesh.uasset"), fresh)


if __name__ == "__main__":
    unittest.main(verbosity=2)
