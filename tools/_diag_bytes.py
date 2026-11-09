"""Byte-exact dump of the summary region + candidate field parses."""
import struct

F = r"G:\xmcl-fetch\work\samples\T_VMGen_BaseColorMap_993eca56b1014c50d99948ab48a30e9a.uasset"
b = open(F, "rb").read()


def i32(o):
    return struct.unpack_from("<i", b, o)[0]


# dump printable/hex map 0x10..0x110
for base in range(0x10, 0x110, 16):
    chunk = b[base:base + 16]
    hx = " ".join(f"{c:02x}" for c in chunk)
    asc = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
    print(f"{base:04x}  {hx:<47}  {asc}")

print("\ni32 at each offset 0x20..0x90:")
for o in range(0x20, 0x94, 4):
    print(f"  0x{o:03x}: {i32(o):12d}  0x{struct.unpack_from('<I', b, o)[0]:08X}")
