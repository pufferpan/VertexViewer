"""Honor actual skin material switches and calibrated stock extensions."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import gunsmith as gs, material, loader
from core.types import Material


class SkinMaterialTests(unittest.TestCase):
    def test_static_switch_reads_the_bool_tag_even_when_payload_is_empty(self):
        prop = lambda name, value=b'', **fields: SimpleNamespace(name=name, value=value, **fields)
        for value_name, enabled in (("Value", 0), ("Value", 1), ("ParameterValue", 1)):
            parsed = [([prop('SwitchParameters', b'wrapper-data')], 1),
                      ([prop('Switches', b'element-body')], 1),
                      ([prop('ParameterInfo', b'name'),
                        prop(value_name, type='BoolProperty', extra={'bool_value': enabled})], 12),
                      ([prop('Name', b'name-value')], 1)]
            with patch.object(material, 'parse_properties', side_effect=parsed), \
                 patch.object(material, '_fname_at', return_value=('UseEmissiveColor', 8)):
                self.assertEqual(material._static_switches(None, b'0123456789'),
                                 {'UseEmissiveColor': float(enabled)})

    def test_explicit_emissive_mask_survives_texture_slot_validation(self):
        mat = Material(texture_params={'EmissiveMaskMap': 'T_Weapon_Mask_HD'})
        material.fill_slots(mat)
        self.assertEqual(mat.emissive_texture, 'T_Weapon_Mask_HD')
        loader._validate_slots(mat)
        self.assertEqual(mat.emissive_texture, 'T_Weapon_Mask_HD')

    def test_skin_mask_resolves_inside_its_own_hd_texture_folder(self):
        target = 'Game/GunA/Texture/HD/T_Mask.uasset'
        with patch.object(loader, 'index', return_value={target: []}):
            self.assertEqual(loader.resolve_texture_ref('T_Mask', 'Game/GunA/Material'), target)

    def test_local_material_path_is_not_replaced_by_same_name_on_another_gun(self):
        local = 'Game/GunA/Material/Same.uasset'
        elsewhere = 'Game/GunB/Material/Same.uasset'
        with patch.object(loader, 'model_dir', return_value='Game/GunA'), \
             patch.object(loader, 'index', return_value={elsewhere: [], local: []}), \
             patch.object(loader, '_load_material_asset', side_effect=lambda path: Material(pak_path=path)), \
             patch.object(loader, '_apply_material_slots'):
            result = loader.materials_in('Game/GunA/Receiver.uasset')
        self.assertEqual([m.pak_path for m in result], [local])

    def test_disabled_emissive_color_does_not_turn_whole_skin_green(self):
        mat = Material(vector_params={'EmissiveColor': (.068, 1, .041, .3)},
                       scalar_params={'UseEmissiveColor': 0})
        material.fill_slots(mat)
        self.assertEqual(mat.emissive, (0, 0, 0))

    def test_enabled_emission_and_materials_without_switch_keep_their_color(self):
        for switches in ({}, {'UseEmissiveColor': 1}):
            mat = Material(vector_params={'EmissiveColor': (.1, .2, .3, 1)},
                           scalar_params=switches)
            material.fill_slots(mat)
            self.assertEqual(mat.emissive, (.1, .2, .3))

    def test_unused_effect_parameter_is_ignored_after_parent_resolution(self):
        mat = Material(vector_params={'EmissiveColor': (1, 1, 1, 0)})
        material.fill_slots(mat)
        self.assertEqual(mat.emissive, (1, 1, 1))
        parent = Material(parent_parameter_names=('BaseColorMap', 'NCEMap'))
        material.inherits_defaults(mat, parent)
        self.assertEqual(mat.emissive, (0, 0, 0))

    def test_skin_extension_uses_exact_component_number(self):
        source = 'models/weapons/parts/sto/sto_a_hk416c_041/sto_a_hk416c_041_3p'
        offsets = {source: np.array([-.12215, 0, 0], np.float32)}
        with patch.object(gs, 'part_offsets', return_value=offsets):
            skin = 'Commerical/RecordAction/Sto_A_HK416C_041_RecordAction_6b_3P.uasset'
            np.testing.assert_array_equal(gs.part_offset(skin), offsets[source])
            np.testing.assert_array_equal(gs.part_offset(skin.replace('_041_', '_089_')), [0,0,0])
            offsets['other/sto_a_hk416c_041_1p'] = np.array([9,0,0])
            np.testing.assert_array_equal(gs.part_offset(skin), [0,0,0])


if __name__ == '__main__':
    unittest.main()
