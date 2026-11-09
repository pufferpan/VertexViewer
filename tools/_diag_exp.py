"""Dump header start + export record + property list guess for one texture."""
import struct

F = r"G:\xmcl-fetch\work\samples\T_VMGen_BaseColorMap_993eca56b1014c50d99948ab48a30e9a.uasset"
X = r"G:\xmcl-fetch\work\samples\T_VMGen_BaseColorMap_993eca56b1014c50d99948ab48a30e9a.uexp"
b = open(F, "rb").read()
x = open(X, "rb").read()
print("uasset size", len(b))
print("head:", " ".join(f"{c:02x}" for c in b[:0x20]))
print("i32@0x04 =", struct.unpack_from("<i", b, 4)[0],
      "i32@0x08 =", struct.unpack_from("<i", b, 8)[0])
print("\nimport table 0x3b1..0x405:")
for o in range(0x3B1, 0x405, 28):
    print(f"  @{o:#x}", struct.unpack_from("<8i", b, o) if o + 28 <= len(b) else "eof")
print("\nexport record 0x405..0x46d:")
print("  ", struct.unpack_from("<4i", b, 0x405), "then name", struct.unpack_from("<2i", b, 0x405 + 16))
vals = struct.unpack_from("<4i2iIiqqiiii16sIIIII", b, 0x405)
print("  parsed:", vals)
print("\ndepends/preload 0x46d..:", " ".join(f"{c:02x}" for c in b[0x46D:]))
print("\nuexp size", len(x))
print("uexp head 0x00..0x80:", " ".join(f"{c:02x}" for c in x[:0x80]))
print("uexp ascii:", "".join(chr(c) if 32 <= c < 127 else "." for c in x[:0x100]))
