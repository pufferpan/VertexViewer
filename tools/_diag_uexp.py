"""Walk the texture uexp property list by hand-ish, dump region, search markers."""
import os
import struct

S = r"G:\xmcl-fetch\work\samples"
base = "T_VMGen_BaseColorMap_993eca56b1014c50d99948ab48a30e9a"
x = open(os.path.join(S, base + ".uexp"), "rb").read()
print("uexp size", len(x))
for marker in (b"PF_BC7", b"Android", b"IOS", b"None", b"TC_BC7", b"TEXTUREGROUP"):
    offs = []
    i = x.find(marker)
    while i >= 0 and len(offs) < 8:
        offs.append(i)
        i = x.find(marker, i + 1)
    print(f"  {marker!r} at {[hex(o) for o in offs]}")


def dump(a, b, label=""):
    print(f"--- {label} 0x{a:x}..0x{b:x} ---")
    for i in range(a, min(b, len(x)), 16):
        chunk = x[i:i + 16]
        hx = " ".join(f"{c:02x}" for c in chunk)
        asc = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
        print(f"{i:04x}  {hx:<47}  {asc}")


dump(0x30, 0x250, "head")
