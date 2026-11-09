"""Property walk + map value byte dump for the AH_64E BaseColor texture."""
import os
import sys
import struct

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.mini_upk import Upk, parse_properties  # noqa: E402

S = r"G:\xmcl-fetch\work\samples"
base = "T_VMGen_BaseColorMap_993eca56b1014c50d99948ab48a30e9a"
ua = open(os.path.join(S, base + ".uasset"), "rb").read()
ue = open(os.path.join(S, base + ".uexp"), "rb").read()
ub = open(os.path.join(S, base + ".ubulk"), "rb").read()

upk = Upk(ua, ue, ub)
data = upk.export_data(upk.exports[0])
props, end = parse_properties(upk, data)
print(f"export data {len(data)}  props {len(props)}  end 0x{end:x}")
for p in props:
    print(f"  @0x{p.offset:04x} {p.name:26s} {p.type:18s} size={p.size:6d} extra={ {k: v for k, v in p.extra.items() if k != 'struct_guid'} }")
    if p.size and p.size <= 64:
        print(f"       val: {p.value.hex()}")

mp = [p for p in props if p.type == "MapProperty"]
if mp:
    v = mp[0].value
    print(f"\nmap value {len(v)} bytes @0x{mp[0].offset:04x} (value starts 0x{mp[0].offset + 0:x})")
    r = 0
    for i in range(0, len(v), 16):
        chunk = v[i:i + 16]
        hx = " ".join(f"{c:02x}" for c in chunk)
        asc = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
        print(f"{i:04x}  {hx:<47}  {asc}")

print("\nubulk size", len(ub), "first 64:", ub[:64].hex())
print("ubulk last 64:", ub[-64:].hex())
