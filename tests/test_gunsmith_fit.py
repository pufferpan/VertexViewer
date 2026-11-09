# -*- coding: utf-8 -*-
"""改枪装配的几条硬规则：同族去重、悬空件贴回、官方包围盒不把件拽开。"""
import unittest

import numpy as np

from core import gunsmith as gs
from core.mesh import MeshLOD


def lod_box(x0, x1, y0, y1, z0, z1) -> MeshLOD:
    corners = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1)
                        for z in (z0, z1)], np.float32)
    return MeshLOD(positions=corners)


def spec(name: str, slot: str = "", socket: str = "") -> gs.PartSpec:
    vpath = "../../../DeltaForce/Content/Models/Weapons/Parts/X/%s_3P.uasset" % name
    return gs.PartSpec(vpath=vpath, slot=slot or gs.mount_family(vpath), socket=socket)


class DedupeTest(unittest.TestCase):
    def test_keeps_first_of_major_family(self):
        picks = [spec("Sto_C_X", "stock"), spec("Sto_S_X", "stock"),
                 spec("Bar_X", "barrel")]
        keep = gs._dedupe_major(picks)
        self.assertEqual(len(keep), 2)
        self.assertTrue(keep[0].vpath.endswith("Sto_C_X_3P.uasset"))
        self.assertTrue(keep[1].vpath.endswith("Bar_X_3P.uasset"))

    def test_keeps_two_magazines(self):
        picks = [spec("Mag_A", "mag"), spec("Mag_B", "mag")]
        self.assertEqual(len(gs._dedupe_major(picks)), 2)

    def test_keeps_second_optic(self):
        picks = [spec("Sco_A", "optic"), spec("Sco_B", "optic")]
        self.assertEqual(len(gs._dedupe_major(picks)), 2)


class CloseGapTest(unittest.TestCase):
    def test_pushes_part_back_onto_receiver(self):
        base = lod_box(0.0, 0.30, -0.03, 0.05, -0.03, 0.03)
        stock = lod_box(-0.12, -0.045, 0.0, 0.05, -0.02, 0.02)
        picks = [spec("Sto_A", "stock")]
        plan = {id(picks[0]): np.eye(4, dtype=np.float32)}
        out = gs._close_mount_gaps(base, [(picks[0], stock)], plan)
        mat = out[id(picks[0])]
        self.assertGreater(float(mat[0, 3]), 0.005)      # 往机匣方向推了
        lo, hi = gs._lod_bounds_after(stock, mat)
        self.assertLessEqual(float(lo[0] - 0.0), 0.0 + 1e-4)   # 已经贴上机匣
        self.assertLessEqual(abs(float(hi[0]) - 0.0), 0.02)

    def test_leaves_big_gap_alone(self):
        base = lod_box(0.0, 0.30, -0.03, 0.05, -0.03, 0.03)
        far = lod_box(-0.60, -0.50, 0.0, 0.05, -0.02, 0.02)
        picks = [spec("Sto_B", "stock")]
        plan = {id(picks[0]): np.eye(4, dtype=np.float32)}
        out = gs._close_mount_gaps(base, [(picks[0], far)], plan)
        self.assertAlmostEqual(float(out[id(picks[0])][0, 3]), 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
