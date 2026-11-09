"""Exact weapon/part identity, skin kit scope and reversible recipe checks."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import gunsmith as gs, weapon_skins as ws


def asset(stem, kit=""):
    root = ("../../../DeltaForce/Content/Commerical/WeaponAppear/" + kit + "/"
            if kit else "../../../DeltaForce/Content/Models/Weapons/Parts/")
    return root + stem + "/" + stem + "_3P.uasset"


M4 = asset("Rec_AR_M4A1-Std_001")
HK = asset("Rec_AR_HK416_021")
SCAR = asset("Rec_AR_ScarH_045")
BAR = asset("Bar_S-370_M4A1-Std_001")
MAG = asset("Mag_556-45-30R_M4A1-Std_001")
CUSTOM = asset("Sco_1X_custom_099")
KIT = "Ma2/Blue_p9/M4A1/Model"
BLUE = asset("Rec_AR_M4A1-Std_001_Blue_p9", KIT)
BLUE_MAG = asset("Mag_556-45-30R_M4A1-Std_001_Blue_p9", KIT)
BLUE_BAR = asset("Bar_AR-470_M16A2-Std_016_Blue_p9", KIT)
RED_KIT = "She4/Red_qt/M4A1"
RED = asset("Rec_AR_M4A1-Std_001_Red_qt", RED_KIT)
RED_BAR = asset("Bar_S-370_M4A1-Std_001_Red_qt", RED_KIT)
WRONG_MAG = asset("Mag_556-45-30R_M4A1-Std_001_Blue_p9",
                  "Ma2/Blue_p9/HK416/Model")
BLUE_OTHER_GUN = asset("Rec_AR_HK416_021_Blue_p9",
                       "Ma2/Blue_p9/HK416/Model")
COUNTER = asset("Rec_AR_M4A1-Std_001_Transparent_Counter")
FAKE = asset("Rec_AR_M4A1-Std_001_Material")
PATHS = (M4, HK, SCAR, BAR, MAG, CUSTOM, BLUE, BLUE_MAG, BLUE_BAR,
         RED, RED_BAR, WRONG_MAG, BLUE_OTHER_GUN, COUNTER, FAKE)


class SkinTests(unittest.TestCase):
    def setUp(self):
        ws.clear_cache()
        self.patches = [
            patch.object(ws, "_model_paths", return_value=PATHS),
            patch.object(ws, "_is_mesh", side_effect=lambda p: p != FAKE),
            patch.object(gs, "display_name", side_effect=lambda p: Path(p).stem),
            patch.object(ws, "_preset_mounts", return_value={}),
            patch.object(gs, "find_socket", side_effect=lambda parent, names, prefer="":
                         ((prefer or names[0]), parent, None) if prefer or names else None),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def recipe(self):
        return gs.Recipe(M4, "M4A1", [
            gs.PartSpec(BAR, "barrel", "枪管", offset=[.01, .02, .03],
                        rot=[4, 5, 6], socket="Bar_point", scale=1.2,
                        slot_fit=True, anchored=True),
            gs.PartSpec(MAG, "mag", "弹匣"),
            gs.PartSpec(CUSTOM, "optic", "自选瞄具"),
        ])

    def test_skin_list_uses_exact_gun_and_real_receiver(self):
        self.assertEqual([s.id for s in ws.list_skins(M4)], [M4, BLUE, RED])
        self.assertEqual([s.id for s in ws.list_skins(HK)], [HK, BLUE_OTHER_GUN])
        self.assertEqual([s.id for s in ws.list_skins(SCAR)], [SCAR])

    def test_exact_matching_parts_and_manual_configuration_survive(self):
        original = self.recipe()
        result = ws.apply_skin(original, BLUE)
        self.assertEqual(result.recipe.base, BLUE)
        self.assertEqual([p.vpath for p in result.recipe.parts],
                         [BAR, BLUE_MAG, CUSTOM])
        self.assertEqual(result.recipe.parts[0].offset, [.01, .02, .03])
        self.assertEqual(result.recipe.parts[0].rot, [4, 5, 6])
        self.assertEqual(result.recipe.parts[0].socket, "Bar_point")
        self.assertTrue(result.recipe.parts[0].slot_fit)
        self.assertTrue(result.recipe.parts[0].anchored)
        self.assertEqual(original.base, M4)
        self.assertEqual(original.parts[1].vpath, MAG)
        self.assertEqual(result.changed, ("弹匣",))
        self.assertEqual(result.retained, ("枪管", "自选瞄具"))

    def test_cross_skin_and_original_restore_source_parts(self):
        blue = ws.apply_skin(self.recipe(), BLUE).recipe
        red = ws.apply_skin(blue, RED).recipe
        self.assertEqual([p.vpath for p in red.parts], [RED_BAR, MAG, CUSTOM])
        restored = ws.apply_skin(red, M4).recipe
        self.assertEqual([p.vpath for p in restored.parts], [BAR, MAG, CUSTOM])
        self.assertTrue(all(not p.skin_source for p in restored.parts))

    def test_part_from_another_weapon_skin_directory_is_never_used(self):
        ws.clear_cache()
        with patch.object(ws, "_model_paths", return_value=tuple(
                p for p in PATHS if p != BLUE_MAG)):
            result = ws.apply_skin(self.recipe(), BLUE)
            self.assertEqual(result.recipe.parts[1].vpath, MAG)
            self.assertNotIn(WRONG_MAG, [p.vpath for p in result.recipe.parts])

    def test_cross_weapon_target_is_rejected(self):
        with self.assertRaises(ValueError):
            ws.apply_skin(self.recipe(), BLUE_OTHER_GUN)

    def test_scheme_roundtrip_keeps_skin_and_legacy_defaults(self):
        recipe = ws.apply_skin(self.recipe(), BLUE).recipe
        restored = gs.Recipe.from_dict(recipe.to_dict())
        self.assertEqual(restored.skin_id, BLUE)
        self.assertEqual(restored.skin_base, M4)
        self.assertEqual(restored.parts[1].skin_source, MAG)
        self.assertEqual(gs.Recipe.from_dict({"base": M4}).skin_id, "")
        self.assertEqual(gs.PartSpec.from_dict({"vpath": BAR}).skin_source, "")

    def test_official_action_uses_the_skin_kits_actual_designs(self):
        recipe = ws.apply_skin(self.recipe(), BLUE).recipe
        with patch.object(gs, "official_loadout", return_value=[
                gs.PartSpec(BAR, "barrel"), gs.PartSpec(MAG, "mag"),
                gs.PartSpec(CUSTOM, "optic")]):
            result = ws.official_parts(recipe)
        self.assertEqual(result.recipe.base, BLUE)
        self.assertEqual(set(p.vpath for p in result.recipe.parts),
                         {BLUE_BAR, BLUE_MAG, CUSTOM})
        self.assertNotIn(BAR, [p.vpath for p in result.recipe.parts])

    def test_she4_without_model_layer_is_scoped_to_its_gun(self):
        skin = next(s for s in ws.list_skins(M4) if s.id == RED)
        self.assertTrue(skin.kit_dir.endswith("She4/Red_qt/M4A1/"))
        self.assertEqual(skin.part_count, 1)
        self.assertEqual(ws.apply_skin(self.recipe(), RED).recipe.parts[0].vpath,
                         RED_BAR)

    def test_official_repeated_rail_covers_keep_their_separate_sockets(self):
        cover = asset("Other_Railcover_068")
        skin_cover = asset("Other_Railcover_068_Blue_p9", KIT)
        with patch.object(ws, "_model_paths",
                          return_value=PATHS + (cover, skin_cover)), \
             patch.object(gs, "official_loadout", return_value=[
                 gs.PartSpec(cover, "tactical", socket="CommonL_point"),
                 gs.PartSpec(cover, "tactical", socket="CommonR_point")]):
            result = ws.official_parts(gs.Recipe(base=BLUE))
        covers = [p for p in result.recipe.parts if p.vpath == skin_cover]
        self.assertEqual(len(covers), 2)
        self.assertEqual({p.socket for p in covers},
                         {"CommonL_point", "CommonR_point"})

    def test_explicit_parts_receiver_prefix_keeps_the_same_gun_identity(self):
        prefixed = asset("Parts_Rec_AR_M4A1-Std_001_Outers_1u",
                         "Ma1/Outers_1u/M4A1/Model")
        with patch.object(ws, "_model_paths", return_value=PATHS + (prefixed,)):
            self.assertEqual(ws.part_identity(prefixed), ws.part_identity(M4))
            result = ws.apply_skin(self.recipe(), prefixed)
            self.assertEqual(result.recipe.base, prefixed)
            self.assertEqual(result.skin.name, "Outers_1u")

    def test_uninstanced_auxiliary_mesh_is_not_added_from_skin_directory(self):
        floating = asset("Other_sr25-cqbRailcover_014_Blue_p9", KIT)
        with patch.object(ws, "_model_paths", return_value=PATHS + (floating,)), \
             patch.object(gs, "official_loadout", return_value=[
                 gs.PartSpec(BAR, "barrel"), gs.PartSpec(MAG, "mag")]):
            result = ws.official_parts(gs.Recipe(base=BLUE))
        self.assertNotIn(floating, [p.vpath for p in result.recipe.parts])
        self.assertIn(Path(floating).stem, result.omitted)

    def test_missing_real_parent_socket_keeps_original_primary(self):
        with patch.object(gs, "find_socket", return_value=None), \
             patch.object(gs, "official_loadout", return_value=[
                 gs.PartSpec(BAR, "barrel", socket="Bar_point")]):
            result = ws.official_parts(gs.Recipe(base=BLUE))
        self.assertEqual([p.vpath for p in result.recipe.parts], [BAR])
        self.assertIn(Path(BLUE_BAR).stem, result.omitted)

    def test_multiple_stock_candidates_require_same_gun_preset_instance(self):
        original = asset("Sto_S_Default_160")
        body = asset("Sto_A_HK416C_041_Blue_p9", KIT)
        adapter = asset("Sto_A_HK416C-B_089_Blue_p9", KIT)
        with patch.object(ws, "_model_paths", return_value=PATHS + (original, body, adapter)), \
             patch.object(ws, "_preset_mounts", return_value={
                 ws.part_identity(body): (("Sto_point", ws.part_identity(M4)),)}), \
             patch.object(gs, "official_loadout", return_value=[
                 gs.PartSpec(original, "stock")]):
            result = ws.official_parts(gs.Recipe(base=BLUE))
        stocks = [p for p in result.recipe.parts if p.slot == "stock"]
        self.assertEqual([p.vpath for p in stocks], [body])
        self.assertEqual(stocks[0].socket, "Sto_point")
        self.assertIn(Path(adapter).stem, result.omitted)

    def test_compound_stock_adds_only_matching_rods_with_actual_receiver_socket(self):
        body = asset("Sto_A_HK416C_041")
        rods = asset("Sto_A_HK416C-B_089")
        skin_body = asset("Sto_A_HK416C_041_Blue_p9", KIT)
        skin_rods = asset("Sto_A_HK416C-B_089_Blue_p9", KIT)
        extra = (body, rods, skin_body, skin_rods)
        with patch.object(ws, "_model_paths", return_value=PATHS + extra), \
             patch.object(gs, "official_loadout", return_value=[gs.PartSpec(body, "stock")]), \
             patch.object(gs._sockets, "socket_names", return_value=["416cPart_point"]), \
             patch.object(gs._sockets, "socket_matrix", return_value=np.eye(4)):
            skinned = ws.official_parts(gs.Recipe(base=BLUE)).recipe
            original = ws.official_parts(gs.Recipe(base=M4)).recipe
        self.assertEqual([p.vpath for p in skinned.parts if p.slot == "stock"],
                         [skin_body, skin_rods])
        self.assertEqual([p.vpath for p in original.parts if p.slot == "stock"], [body, rods])
        self.assertEqual(skinned.parts[-1].socket, "416cPart_point")

    def test_compound_stock_does_not_borrow_component_from_another_kit(self):
        body = asset("Sto_A_HK416C_041")
        rods = asset("Sto_A_HK416C-B_089")
        skin_body = asset("Sto_A_HK416C_041_Blue_p9", KIT)
        wrong_rods = asset("Sto_A_HK416C-B_089_Blue_p9", "Ma2/Blue_p9/HK416/Model")
        with patch.object(ws, "_model_paths", return_value=PATHS + (body, rods, skin_body, wrong_rods)), \
             patch.object(gs, "official_loadout", return_value=[gs.PartSpec(body, "stock")]), \
             patch.object(gs._sockets, "socket_names", return_value=["416cPart_point"]), \
             patch.object(gs._sockets, "socket_matrix", return_value=np.eye(4)):
            result = ws.official_parts(gs.Recipe(base=BLUE))
        self.assertNotIn(wrong_rods, [p.vpath for p in result.recipe.parts])


if __name__ == "__main__":
    unittest.main()
