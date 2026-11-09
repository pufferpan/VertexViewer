"""LOD index counts may start on any virtual byte alignment."""
import struct
import sys
import unittest
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import mesh


class IndexAlignmentTests(unittest.TestCase):
    def buffer(self, parity, element=2, gap=b''):
        indices = np.array([0, 1, 2, 0, 2, 3], dtype='<u2' if element == 2 else '<u4')
        prefix = b'\xff' * (32 + parity)
        raw = prefix + struct.pack('<I', indices.size) + indices.tobytes() + gap
        return raw + b'\xff' * 32, len(raw), indices

    def test_all_four_count_alignments_for_16_and_32_bit_indices(self):
        for element in (2, 4):
            for parity in range(4):
                with self.subTest(element=element, parity=parity):
                    raw, position, expected = self.buffer(parity, element)
                    found = mesh._locate_leading_container(raw, position, 0, 4)
                    self.assertIsNotNone(found)
                    np.testing.assert_array_equal(mesh._indices_from_container(raw, found, 4), expected)

    def test_index_data_must_end_exactly_at_position_header(self):
        for gap in (b'\xff', b'\xff' * 3):
            raw, position, _ = self.buffer(0, gap=gap)
            self.assertIsNone(mesh._locate_leading_container(raw, position, 0, 4))

    def test_odd_lod_uses_own_leading_indices_instead_of_next_lod(self):
        raw, position, expected = self.buffer(1)
        next_indices = np.array([0, 2, 1], dtype='<u2')
        raw += struct.pack('<II', 2, 3) + next_indices.tobytes()
        positions = np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0]], np.float32)
        result = mesh._resolve_indices(raw, position, len(raw), 0, len(raw),
                                       4, positions, pos_off=position)
        np.testing.assert_array_equal(result, expected)


if __name__ == '__main__':
    unittest.main()
