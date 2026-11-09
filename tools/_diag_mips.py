"""Locate mip-dimension pairs inside the texture export data to reverse the mip layout."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.mini_upk import Upk, parse_properties  # noqa: E402

S = r"G:\xmcl-fetch\work\samples"
base = "T_VMGen_BaseColorMap_993eca56b1014c50d99948ab48a30e9a"
ua = open(os.path.join(S, base + ".uasset"), "rb").read()
ue = open(os.path.join(S, base + ".uexp"), "rb").read()
upk = Upk(ua, ue, None)
data = upk.export_data(upk.exports[0])
props, end = parse_properties(upk, data)
print("props end 0x%x data %d" % (end, len(data)))

for dim in (512, 256, 128, 64, 32, 16, 8, 4):
    pat = struct.pack("<ii", dim, dim)
    offs = []
    i = data.find(pat)
    while i >= 0:
        offs.append(i)
        i = data.find(pat, i + 1)
    print(f"  ({dim},{dim}) at {[hex(o) for o in offs]}")

# print every i32 in the region end..end+0x100 with offsets
print("\ni32 stream (offset : value) from 0x%x:" % end)
o = end
while o + 4 <= min(len(data), end + 0xC0):
    print(f"  0x{o:04x}  {struct.unpack_from('<i', data, o)[0]:12d}  0x{struct.unpack_from('<I', data, o)[0]:08X}")
    o += 4
