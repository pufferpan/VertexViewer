"""改枪页的皮肤套装匹配：同一把枪的所有皮肤套装都要进下拉。

皮肤套装里的机匣部件号常常和原版不同（换皮连模具都换），旧逻辑只认部件号
完全一致，结果 M4A1 这种枪只剩「原版」一项。这里用假 vpath 验证按枪名键展开。
"""
import unittest
from unittest import mock

from core import weapon_skins as ws


def _kit(set_name: str, gun: str, receiver: str) -> list:
    root = ("../../../DeltaForce/Content/Commerical/WeaponAppear/Ma3/%s/%s/"
            % (set_name, gun))
    return [
        root + "Model/%s/%s_3P.uasset" % (receiver, receiver),
        root + "Model/%s/%s_1P.uasset" % (receiver, receiver),
        root + "Model/Bar_AR-%s-Std_015_%s/Bar_AR-%s-Std_015_%s_3P.uasset"
        % (gun, set_name, gun, set_name),
        root + "Texture/HD/T_Bar_BC_HD.uasset",
        root + "Material/MI_Bar.uasset",
    ]


class SkinKitTest(unittest.TestCase):
    def test_gun_key(self):
        self.assertEqual(ws._gun_key("rec_ar_m4a1-std_001"), "m4a1")
        self.assertEqual(ws._gun_key("rec_smg_qcq171_060"), "qcq171")
        self.assertEqual(ws._gun_key("rec_pt_coltpython_std_014"), "coltpython")
        self.assertEqual(ws._gun_key("WeaponAppear/Ma2/HavvkTech_p9/M4A1/"), "m4a1")

    def test_cross_number_kit_is_selectable(self):
        base = ("../../../DeltaForce/Content/Models/Weapons/Parts/AR/"
                "Rec_AR_M4A1-Std_001_3P.uasset")
        kit = _kit("Florals_h2", "M4A1", "Rec_AR_M4A1-Std_015_Florals_h2")
        paths = [base] + kit
        with mock.patch.object(ws, "_model_paths", return_value=tuple(paths)), \
                mock.patch.object(ws, "_is_mesh", return_value=True):
            ws.clear_cache()
            skins = ws.list_skins(base)
        names = [s.name for s in skins]
        self.assertIn("原版", names)
        self.assertIn("Florals_h2", names)
        cross = [s for s in skins if s.cross]
        self.assertEqual(len(cross), 1)
        self.assertEqual(cross[0].family, "rec_ar_m4a1-std_015")
        self.assertTrue(cross[0].part_count >= 1)

    def test_other_gun_kits_stay_out(self):
        base = ("../../../DeltaForce/Content/Models/Weapons/Parts/AR/"
                "Rec_AR_M4A1-Std_001_3P.uasset")
        other = _kit("Neon_q1", "AK12", "Rec_AR_AK12_030_Neon_q1")
        with mock.patch.object(ws, "_model_paths", return_value=tuple([base] + other)), \
                mock.patch.object(ws, "_is_mesh", return_value=True):
            ws.clear_cache()
            names = [s.name for s in ws.list_skins(base)]
        self.assertNotIn("Neon_q1", names)


if __name__ == "__main__":
    unittest.main()
