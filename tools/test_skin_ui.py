"""Failure fallback must preserve individual rail attachments and their sockets."""
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.gunsmith_page import GunsmithPage
from core.gunsmith import PartSpec


class SkinFallbackTests(unittest.TestCase):
    def test_same_slot_controls_select_the_actual_instance(self):
        parts = [PartSpec(vpath="Other_Rail_014_3P.uasset", slot="other", socket=s)
                 for s in ("RailCL_point", "RailCR_point")]
        page = SimpleNamespace(recipe=SimpleNamespace(parts=parts), _selected=None,
                               _loading=False, _sync_sliders=lambda: None)
        GunsmithPage._on_combo(page, 2)
        self.assertIs(GunsmithPage._current_spec(page), parts[1])
        selected = GunsmithPage._current_spec(page)
        selected.offset[0] = .1
        self.assertEqual(parts[0].offset, [0, 0, 0])

    def test_repeated_slot_instances_return_to_their_own_original(self):
        old = [PartSpec(vpath="Other_Rail_014_3P.uasset", slot="other", socket=s)
               for s in ("RailCL_point", "RailCR_point")]
        used = set()
        for socket, expected in (("RailCR_point", old[1]), ("RailCL_point", old[0])):
            spec = PartSpec(vpath="Other_Rail_014_Skin_3P.uasset", slot="other", socket=socket)
            matched = GunsmithPage._previous_skin_part(spec, old, used)
            self.assertIs(matched, expected)
            used.add(id(matched))
        self.assertIsNone(GunsmithPage._previous_skin_part(spec, old, used))

    def test_ambiguous_same_slot_is_not_guessed(self):
        old = [PartSpec(vpath="Other_Rail_014_3P.uasset", slot="other", socket=s)
               for s in ("RailCL_point", "RailCR_point")]
        unknown = PartSpec(vpath="Other_Unknown_099_3P.uasset", slot="other")
        self.assertIsNone(GunsmithPage._previous_skin_part(unknown, old, set()))

    def test_front_grip_does_not_fall_back_to_a_pistol_grip(self):
        old = PartSpec(vpath="PisG_Old_001_3P.uasset", slot="grip", socket="PisG_point")
        front = PartSpec(vpath="FroG_New_002_Skin_3P.uasset", slot="grip", socket="For_point")
        self.assertIsNone(GunsmithPage._previous_skin_part(front, [old], set()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
