"""Operator sections bind their own materials at every LOD."""
import sys,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import loader,mesh
from core.types import Mesh,MeshLOD,Section,Material
from core.skeletal import Reader,SkeletalLayoutError
from core import material
from types import SimpleNamespace


class OperatorTests(unittest.TestCase):
    def test_explicit_character_texture_channels_override_filename_guesses(self):
        declared='/Game/Character/Textures/UI/Head_CSSS'
        exact='../../../DeltaForce/Content/Character/Textures/UI/Head_CSSS.uasset'
        mat=Material(base_color_texture=exact,orm_texture=exact,
                     texture_params={'BaseColorMap':declared})
        with patch.object(loader,'index',return_value={exact:[]}):
            self.assertEqual(loader.resolve_texture_ref(declared),exact)
            self.assertEqual(loader.resolve_texture_ref(exact),exact)
            loader._validate_slots(mat)
        self.assertEqual(mat.base_color_texture,exact)
        self.assertEqual(mat.orm_texture,'')

    def test_shared_default_skin_texture_retains_authoritative_package_path(self):
        package='/Game/Characters/Default/Textures/F_Luna_Lower_C'
        upk=SimpleNamespace(imports=[SimpleNamespace(name=package,outer=0),
            SimpleNamespace(name='F_Luna_Lower_C',outer=-1)])
        self.assertEqual(material.object_path(upk,-2),package)
        exact='../../../DeltaForce/Content/Characters/Default/Textures/F_Luna_Lower_C.uasset'
        wrong='../../../DeltaForce/Content/Characters/Skin/Textures/F_Luna_Lower_C.uasset'
        with patch.object(loader,'index',return_value={exact:[],wrong:[]}):
            self.assertEqual(loader.resolve_texture_ref(package,'../../../DeltaForce/Content/Characters/Skin/Materials'),exact)
            self.assertEqual(loader.resolve_asset(package),exact)
            self.assertIsNone(loader.resolve_texture_ref('/Game/Missing/F_Luna_Lower_C',wrong.rsplit('/',1)[0]))

    def test_materials_used_only_by_a_later_lod_are_loaded_without_sorting(self):
        model=Mesh(material_paths=['Upper','Face','MergedBody'],lods=[MeshLOD(sections=[Section(material_path='Upper'),Section(material_path='Face')])])
        with patch.object(loader,'resolve_asset',side_effect=lambda path,base:path), \
             patch.object(loader,'_load_material_asset',side_effect=lambda path:Material(name=path,pak_path=path)), \
             patch.object(loader,'_apply_material_slots') as slots:
            mats=loader.load_materials_for(model,'Character/Skin.uasset')
        self.assertEqual([m.pak_path for m in mats],['Upper','Face','MergedBody'])
        self.assertTrue(all(c.kwargs['allow_model_fallback'] is False for c in slots.call_args_list))

    def test_missing_native_slot_does_not_shift_other_sections_or_guess_body(self):
        model=Mesh(material_paths=['Missing','Face'],lods=[MeshLOD()])
        with patch.object(loader,'resolve_asset',side_effect=lambda path,base:None if path=='Missing' else path), \
             patch.object(loader,'_load_material_asset',return_value=Material(name='Face',pak_path='Face')), \
             patch.object(loader,'_apply_material_slots'),patch.object(loader,'synthetic_material') as guess:
            mats=loader.load_materials_for(model,'Character/Skin.uasset')
        self.assertEqual([m.pak_path for m in mats],['Missing','Face'])
        guess.assert_not_called()

    def test_high_precision_tangent_normals_do_not_truncate_to_eight_bits(self):
        raw=np.array([[32767,0,0,32767],[0,-32767,0,-32767]],dtype=np.int16)
        np.testing.assert_allclose(mesh._decode_packed(raw),[[1,0,0],[0,-1,0]])
        np.testing.assert_array_equal(mesh._pack_tangent(raw,None)[:,3],[1,-1])

    def test_corrupt_native_arrays_do_not_read_outside_the_export(self):
        with self.assertRaises(SkeletalLayoutError):Reader(b'\xff'*4,0,4).array(12,4096)
        with self.assertRaises(SkeletalLayoutError):Reader(b'\x05\0\0\0',0,4).boolean()


if __name__=='__main__':unittest.main()
