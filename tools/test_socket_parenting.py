"""Actual selected-instance socket parenting; no ambiguous/global guessing."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import gunsmith as gs
from core.types import MeshLOD


def move(x=0, y=0, z=0):
    matrix = np.eye(4, dtype=np.float32)
    matrix[:3, 3] = (x, y, z)
    return matrix


class SocketParentTests(unittest.TestCase):
    def setUp(self):
        self.sockets = {}
        self.lod = MeshLOD(positions=np.array([[0, 0, 0], [1, 1, 1]], np.float32))
        patches = [
            patch.object(gs._sockets, "socket_names",
                         side_effect=lambda path: list(self.sockets.get(path, {}))),
            patch.object(gs._sockets, "socket_matrix",
                         side_effect=lambda path, name: self.sockets.get(path, {}).get(name)),
            patch.object(gs, "_bbox_fallback", side_effect=lambda *args: move(77, 88, 99)),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def solve(self, *parts):
        return gs.resolve_placements("receiver", self.lod,
                                     [(part, self.lod) for part in parts])

    def test_explicit_rail_waits_for_handguard_and_composes_world_matrices(self):
        root = move(1, 2, 3)
        root[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        self.sockets = {"receiver": {"Han_point": root},
                        "Han_test_001": {"RailCL_point": move(.4, 0, 0)}}
        child = gs.PartSpec("Other_cover_002", "other", socket="railcl_POINT")
        parent = gs.PartSpec("Han_test_001", "handguard", socket="Han_point")
        result = self.solve(child, parent)  # parent is deliberately later
        np.testing.assert_allclose(result[id(child)], root @ move(.4, 0, 0))
        self.assertEqual(child.socket, "RailCL_point")

    def test_existing_parent_family_has_priority_over_other_socket_owners(self):
        self.sockets = {"receiver": {"Bar_point": move(5)},
                        "Bar_test_001": {"Muzzle_point": move(.3)},
                        "Other_extra_003": {"Muzzle_point": move(20)}}
        child = gs.PartSpec("Muz_test_002", "muzzle", socket="Muzzle_point")
        parent = gs.PartSpec("Bar_test_001", "barrel", socket="Bar_point")
        unrelated = gs.PartSpec("Other_extra_003", "other")
        result = self.solve(child, unrelated, parent)
        np.testing.assert_allclose(result[id(child)][:3, 3], [5.3, 0, 0])

    def test_missing_explicit_socket_does_not_use_unrelated_generic_socket(self):
        self.sockets = {"receiver": {"Common_point": move(123)}}
        child = gs.PartSpec("Other_test_001", "other", socket="Missing_point")
        result = self.solve(child)
        np.testing.assert_array_equal(result[id(child)], move(77, 88, 99))

    def test_two_selected_owners_are_ambiguous(self):
        self.sockets = {"receiver": {"Han_point": move(1)},
                        "Han_A_001": {"RailCL_point": move(2)},
                        "Han_B_002": {"RailCL_point": move(3)}}
        child = gs.PartSpec("Other_test_003", "other", socket="RailCL_point")
        parents = [gs.PartSpec("Han_A_001", "handguard", socket="Han_point"),
                   gs.PartSpec("Han_B_002", "handguard", socket="Han_point")]
        result = self.solve(child, *parents)
        np.testing.assert_array_equal(result[id(child)], move(77, 88, 99))

    def test_a_part_is_never_its_own_parent(self):
        self.sockets = {"Other_test_001": {"Self_point": move(2)}}
        child = gs.PartSpec("Other_test_001", "other", socket="Self_point")
        np.testing.assert_array_equal(self.solve(child)[id(child)], move(77, 88, 99))

    def test_cyclic_explicit_dependencies_finish_with_safe_fallbacks(self):
        self.sockets = {"Other_A_001": {"A_point": move(1)},
                        "Other_B_002": {"B_point": move(2)}}
        first = gs.PartSpec("Other_A_001", "other", socket="B_point")
        second = gs.PartSpec("Other_B_002", "other", socket="A_point")
        result = self.solve(first, second)
        self.assertEqual(set(result), {id(first), id(second)})
        np.testing.assert_array_equal(result[id(first)], move(77, 88, 99))


if __name__ == "__main__":
    unittest.main()
