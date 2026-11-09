"""Dump export data tail (platform data) with local offsets."""
import os
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
print("props end 0x%x, data len %d" % (end, len(data)))
start = end
for i in range(start, min(len(data), start + 0x140), 8):
    chunk = data[i:i + 8]
    hx = " ".join(f"{c:02x}" for c in chunk)
    asc = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
    u32s = []
    for k in range(0, min(8, len(chunk)) - 3, 4):
        u32s.append(f"{int.from_bytes(chunk[k:k + 4], 'little'):10d}")
    print(f"{i - start:04x} (abs {i:04x})  {hx:<23}  {asc:<8}  {' '.join(u32s)}")
