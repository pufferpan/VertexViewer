"""Verify independent parts retain assembly transforms and isolated texture files."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import gunsmith as gs
from core.types import Material, Mesh, MeshLOD, ModelBundle, Section, Texture
from exporters.part_export import export_parts


def bundle(color):
    lod = MeshLOD(positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32),
                  normals=np.array([[0, 0, 1]] * 3, np.float32),
                  uvs=np.array([[0, 0], [1, 0], [0, 1]], np.float32),
                  tangents=np.array([[1, 0, 0, 1]] * 3, np.float32),
                  indices=np.array([0, 1, 2], np.uint32),
                  sections=[Section(material_path="material", num_triangles=1)])
    rgba = np.full((2, 2, 4), [*color, 255], np.uint8)
    return ModelBundle(mesh=Mesh(name="test", lods=[lod]), display_name="test",
                       materials=[Material(pak_path="material", name="mat", base_color_texture="diffuse")],
                       textures=[Texture(pak_path="diffuse", name="diffuse", rgba=rgba)])


def read_vertices(path):
    return np.array([[float(x) for x in line.split()[1:]] for line in Path(path).read_text().splitlines()
                     if line.startswith("v ")])


class PartExportTests(unittest.TestCase):
    def test_exported_components_reassemble_to_preview_and_keep_their_textures(self):
        base, part = bundle([200, 10, 10]), bundle([10, 20, 210])
        spec = gs.PartSpec(vpath="part", slot="stock", name="stock", offset=[.1, .2, .3],
                           rot=[20, 10, -15], scale=1.3)
        world = gs._trs((0, 0, 0), (2, 3, 4))
        original = part.mesh.lods[0].positions.copy()
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(gs, "resolve_placements", return_value={id(spec): world}), \
                patch.object(gs, "part_offset", return_value=np.array([.05, 0, 0])):
            expected = gs.assemble(base, [(spec, part)], base_vpath="base").mesh.lods[0].positions
            result = export_parts(base, [(spec, part)], "base", folder, "test")
            self.assertEqual(len(result["parts"]), 2)
            self.assertEqual(result["errors"], [])
            actual = np.concatenate([read_vertices(Path(folder) / row["obj"]) for row in result["parts"]])
            # OBJ independently deduplicates/sorts each component's vertex rows.
            sort = lambda a: a[np.lexsort(a.T[::-1])]
            np.testing.assert_allclose(sort(actual), sort(expected), atol=1e-6)
            np.testing.assert_array_equal(part.mesh.lods[0].positions, original)
            for row, color in zip(result["parts"], ([200, 10, 10], [10, 20, 210])):
                mtl = (Path(folder) / row["mtl"]).read_text()
                relative = next(line.split(maxsplit=1)[1] for line in mtl.splitlines() if line.startswith("map_Kd "))
                im = np.array(Image.open(Path(folder) / relative))
                np.testing.assert_array_equal(im[0, 0, :3], color)
            manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["parts"][1]["socket"], spec.socket)
            self.assertEqual(manifest["parts"][1]["scale"], 1.3)

    def test_unavailable_component_is_recorded_as_a_failure(self):
        spec = gs.PartSpec(vpath="missing", slot="stock", name="missing")
        with tempfile.TemporaryDirectory() as folder, patch.object(gs, "resolve_placements", return_value={}):
            result = export_parts(bundle([1, 2, 3]), [(spec, None)], "base", folder, "test")
            self.assertEqual(len(result["parts"]), 1)
            self.assertEqual(result["errors"][0]["vpath"], "missing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
