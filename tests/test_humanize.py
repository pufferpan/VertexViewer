"""显示名生成（core/humanize.py）的回归测试。

要点：仓库不附带任何游戏文本/图标（names.json、locres、icons.db 已剥离），
界面上的名字必须由代号拼出来，且读起来像人起的。
"""
import unittest

from core import cnnames, humanize

REC = '../../../DeltaForce/Content/Models/Weapons/Parts/Rec/Rec_AR_M4A1-Std_001/Rec_AR_M4A1-Std_001_3P.uasset'
BAR = '../../../DeltaForce/Content/Models/Weapons/Parts/Bar/Bar_AR-227_SG553-Std_015/Bar_AR-227_SG553-Std_015_1P.uasset'
MUZ = '../../../DeltaForce/Content/Models/Weapons/Parts/Muz/Muz_M-S_M250Silencer_097/Muz_M-S_M250Silencer_097_3P.uasset'
PROP = ('../../../DeltaForce/Content/Commerical/PropAppear/Ma2/Prop_Collect_5C5P2_up_1479/'
        'Prop_Collect_5C5P2_up_1479_1P.uasset')


class HumanizeCase(unittest.TestCase):
    def test_receiver_name(self):
        self.assertEqual(humanize.pretty(REC), 'M4A1 机匣')

    def test_barrel_name(self):
        self.assertEqual(humanize.pretty(BAR), 'SG553 枪管')

    def test_camel_case_model_plus_word(self):
        # M250Silencer 这种「型号+英文词」要拆开，不能整坨摆到界面上
        self.assertEqual(humanize.pretty(MUZ), 'M250 消音器 枪口')

    def test_prop_name(self):
        self.assertEqual(humanize.pretty(PROP), '5C5P2 藏品')

    def test_never_empty(self):
        # 空路径允许返回空串；只要「有代号」就一定有名字
        for path in ('x', '../../../DeltaForce/Content/Models/A.uasset'):
            self.assertTrue(humanize.pretty(path))

    def test_category_word(self):
        self.assertEqual(humanize.category_word(REC), '机匣')


class FallbackCase(unittest.TestCase):
    def test_resolve_cn_falls_back(self):
        # names.json 不存在时也要出名字（走 humanize）
        self.assertEqual(cnnames.resolve_cn(REC), 'M4A1 机匣')

    def test_category_of_uses_generated_name(self):
        self.assertEqual(cnnames.category_of(BAR), '配件')


if __name__ == '__main__':
    unittest.main()
