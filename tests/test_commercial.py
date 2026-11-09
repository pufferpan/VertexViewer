"""Commerical/（游戏里就是这个拼写）皮肤目录的过滤与分类。

皮肤模型不在 work/mesh_catalog.json 里，`inspectable_paths()` 也不知道它们，
所以浏览列表要靠 `commercial_like_mesh()` 补进来、靠 `guess_category()` 分类。
这里只用路径字符串做判定，不读游戏 pak。
"""
import unittest

from app.browser import commercial_series, guess_category, is_model_asset, model_rel
from core.loader import commercial_like_mesh, is_commercial

SKIN_PART = ("../../../DeltaForce/Content/Commerical/WeaponAppear/Ma1/GameboyS2_2x_Specail/MP7/"
             "Model/Rec_SMG_MP7_055_GameboyS2_2x_Specail/"
             "Rec_SMG_MP7_055_GameboyS2_2x_Specail_1P.uasset")
SKIN_PROP = ("../../../DeltaForce/Content/Commerical/PropAppear/Ma2/"
             "Prop_Collect_5C5P2_up_1479/Prop_Collect_5C5P2_up_1479_1P.uasset")
SKIN_CHAR = ("../../../DeltaForce/Content/Commerical/CharAppear/She4/"
             "Char_Dress_6D2KC_test/SkeletalMesh/Char_Dress_6D2KC_test.uasset")


class CommercialFilterTest(unittest.TestCase):
    def test_marker_needs_content_segment(self):
        self.assertTrue(is_commercial(SKIN_PART))
        # UMG 蓝图目录里也有叫 Commercial 的，不能当成游戏资产
        self.assertFalse(is_commercial(
            "../../../DeltaForce/Content/BluePrints/UI/Commercial/WBP_Shop.uasset"))

    def test_mesh_parts_pass(self):
        for path in (SKIN_PART, SKIN_PROP, SKIN_CHAR):
            with self.subTest(path=path):
                self.assertTrue(commercial_like_mesh(path))

    def test_non_mesh_parts_rejected(self):
        root = ("../../../DeltaForce/Content/Commerical/WeaponAppear/Ma1/GameboyS2_2x_Specail/MP7/")
        rejected = [
            root + "Model/Rec_SMG_MP7_055_GameboyS2_2x_Specail/"
                   "Rec_SMG_MP7_055_GameboyS2_2x_Specail_Skeleton.uasset",
            root + "Material/MI_Rec_SMG_MP7_055.uasset",
            root + "Texture/HD/T_Rec_SMG_MP7_055_BC_HD.uasset",
            root + "Aniamtion/Body/Rec_SMG_MP7_055_1P.uasset",
            "../../../DeltaForce/Content/Commerical/Icon/ItemIconWeapon_RTI/Weapon_Icon_1.uasset",
            "../../../DeltaForce/Content/Commerical/WeaponAppear/Ma1/GameboyS2_2x_Specail/MP7/"
            "Model/T_Rec_SMG_MP7_055_BC.uasset",
            "../../../DeltaForce/Content/Commerical/WeaponAppear/Ma1/GameboyS2_2x_Specail/MP7/"
            "BP_Weapon_Appear.uasset",
        ]
        for path in rejected:
            with self.subTest(path=path.split("/")[-1]):
                self.assertFalse(commercial_like_mesh(path))


class CommercialCategoryTest(unittest.TestCase):
    def test_categories(self):
        self.assertEqual(guess_category(SKIN_PART), "武器皮肤")
        self.assertEqual(guess_category(SKIN_PROP), "道具皮肤")
        self.assertEqual(guess_category(SKIN_CHAR), "角色皮肤")
        self.assertEqual(guess_category(
            "../../../DeltaForce/Content/Commerical/Event/S1/Prop_Event_1.uasset"), "活动")
        self.assertEqual(guess_category(
            "../../../DeltaForce/Content/Models/Weapons/AR/M4.uasset"), "武器")

    def test_categories_accept_rel_paths(self):
        # 浏览器里 guess_category 拿到的是 rel（没有前导斜杠），规则照样要命中
        self.assertEqual(
            guess_category("Commerical/PropAppear/Ma2/Prop_Collect_1/Prop_1P.uasset"),
            "道具皮肤")
        self.assertEqual(
            guess_category("Commerical/WeaponAppear/Ma1/Skin/MP7/Model/P/P_1P.uasset"),
            "武器皮肤")
        self.assertEqual(guess_category("Models/Weapons/AR/M4.uasset"), "武器")

    def test_series_only_when_it_adds_information(self):
        # WeaponAppear 的 <皮肤> 目录名和资产名不同，能当搜索词
        self.assertEqual(commercial_series(SKIN_PART), "GameboyS2_2x_Specail")
        # PropAppear 没有 Model/ 层，退回成资产目录名（与标题重复）→ 不用
        self.assertEqual(commercial_series(SKIN_PROP), "")

    def test_browser_keeps_skin_paths(self):
        self.assertTrue(is_model_asset(SKIN_PART))
        self.assertTrue(is_model_asset(SKIN_PROP))
        self.assertEqual(model_rel(SKIN_PROP),
                         "Commerical/PropAppear/Ma2/Prop_Collect_5C5P2_up_1479/"
                         "Prop_Collect_5C5P2_up_1479_1P.uasset")


if __name__ == "__main__":
    unittest.main()
