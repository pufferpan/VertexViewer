"""Static GLB must keep the skeleton and reproduce the bind pose exactly."""
import unittest
import tempfile
from pathlib import Path

import numpy as np

from core.types import MeshLOD, Section
from exporters.static_glb import export_static_glb, skeleton_available
from tests.test_inspection_animation import accessor, fixture, read_glb


def skinned_positions(doc, binary):
    """Evaluate the GLB's own nodes/skin without looking at the source rig."""
    nodes = doc['nodes']
    local = np.tile(np.eye(4), (len(nodes), 1, 1))
    parents = [-1] * len(nodes)
    for index, node in enumerate(nodes):
        for child in node.get('children', []):
            parents[child] = index
        if 'matrix' in node:
            local[index] = np.array(node['matrix']).reshape(4, 4).T
        else:
            from core.inspection import world_matrices
            pose = np.array([[0, 0, 0, 1, 0, 0, 0, 1, 1, 1]], float)
            pose[0, :4] = node.get('rotation', [0, 0, 0, 1])
            pose[0, 4:7] = node.get('translation', [0, 0, 0])
            pose[0, 7:] = node.get('scale', [1, 1, 1])
            local[index] = world_matrices(pose, [-1])[0]
    world = np.empty_like(local)
    for index, parent in enumerate(parents):
        world[index] = local[index] if parent < 0 else world[parent] @ local[index]
    output = []
    for node in nodes:
        if 'mesh' not in node:
            continue
        primitive = doc['meshes'][node['mesh']]['primitives'][0]
        attributes = primitive['attributes']
        positions = accessor(doc, binary, attributes['POSITION'])
        skin = doc['skins'][node['skin']]
        bind = accessor(doc, binary, skin['inverseBindMatrices']).reshape(-1, 4, 4).transpose(0, 2, 1)
        transforms = world[skin['joints']] @ bind
        result = np.zeros_like(positions)
        for slot in range(2):
            if 'JOINTS_' + str(slot) not in attributes:
                continue
            joints = accessor(doc, binary, attributes['JOINTS_' + str(slot)])
            weights = accessor(doc, binary, attributes['WEIGHTS_' + str(slot)])
            for lane in range(4):
                matrix = transforms[joints[:, lane]]
                result += (np.einsum('nij,nj->ni', matrix[:, :3, :3], positions)
                           + matrix[:, :3, 3]) * weights[:, lane, None]
        output.append(result)
    return output


class StaticGlbTests(unittest.TestCase):
    def test_export_keeps_bones_and_bind_pose(self):
        bundle, _clip = fixture()
        self.assertTrue(skeleton_available(bundle.mesh))
        original = bundle.mesh.lods[0].positions.copy()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '静态.glb'
            info = export_static_glb(bundle, path)
            self.assertTrue(info['skinned'])
            self.assertEqual(info['bones'], 2)
            doc, binary = read_glb(path)
            self.assertEqual(len(doc['skins']), 1)
            self.assertEqual(len(doc['skins'][0]['joints']), 2)
            self.assertNotIn('animations', doc)
            attributes = doc['meshes'][0]['primitives'][0]['attributes']
            self.assertIn('JOINTS_0', attributes)
            self.assertIn('WEIGHTS_0', attributes)
            np.testing.assert_allclose(skinned_positions(doc, binary)[0], original, atol=2e-6)
        np.testing.assert_array_equal(bundle.mesh.lods[0].positions, original)

    def test_mesh_without_weights_is_reported_not_crashing(self):
        bundle, _clip = fixture()
        bundle.mesh.lods[0].bone_weights = None
        self.assertFalse(skeleton_available(bundle.mesh))
        with tempfile.TemporaryDirectory() as folder:
            info = export_static_glb(bundle, Path(folder) / 'plain.glb')
            self.assertFalse(info['skinned'])
            self.assertEqual(info['bones'], 0)
            doc, _binary = read_glb(Path(folder) / 'plain.glb')
            self.assertNotIn('skins', doc)

    def test_eight_weights_are_split_across_two_attribute_sets(self):
        bundle, _clip = fixture()
        lod = bundle.mesh.lods[0]
        clones = MeshLOD(positions=lod.positions.copy(), normals=lod.normals.copy(), uvs=lod.uvs.copy(),
                         indices=lod.indices.copy(), sections=[Section(num_triangles=1)],
                         bone_indices=np.zeros((3, 8), np.uint16),
                         bone_weights=np.tile([.125, .125, .125, .125, .125, .125, .125, .125], (3, 1)).astype(np.float32),
                         bones=lod.bones)
        bundle.mesh.lods[0] = clones
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'eight.glb'
            info = export_static_glb(bundle, path)
            doc, binary = read_glb(path)
            attributes = doc['meshes'][0]['primitives'][0]['attributes']
            self.assertIn('JOINTS_1', attributes)
            self.assertIn('WEIGHTS_1', attributes)
            weights = accessor(doc, binary, attributes['WEIGHTS_0']).sum(axis=1)
            weights = weights + accessor(doc, binary, attributes['WEIGHTS_1']).sum(axis=1)
            np.testing.assert_allclose(weights, 1.0, atol=1e-6)
            self.assertEqual(info['bones'], 2)


if __name__ == '__main__':
    unittest.main()
