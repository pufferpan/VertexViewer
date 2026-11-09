"""Diagnostic: figure out the exact FPackageFileSummary layout of  uassets."""
import sys
import struct

F = r"G:\xmcl-fetch\work\samples\T_VMGen_BaseColorMap_993eca56b1014c50d99948ab48a30e9a.uasset"
F2 = r"G:\xmcl-fetch\work\enc1.uasset"


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def fstr(b, o):
    n = i32(b, o)
    o += 4
    if n == 0:
        return "", o
    if n < 0:
        raw = b[o:o + (-n) * 2]
        return raw.decode("utf-16-le", "replace").rstrip("\0"), o + (-n) * 2
    return b[o:o + n - 1].decode("utf-8", "replace"), o + n


def probe(path):
    b = open(path, "rb").read()
    print("=" * 70)
    print(path, "size", len(b))
    print("magic 0x%08X legacy %d ue3 %d ue4 %d lic4 %d" % (
        u32(b, 0), i32(b, 4), i32(b, 8), i32(b, 12), i32(b, 16)))
    print("0x14 =", i32(b, 0x14), " 0x18 =", i32(b, 0x18))
    folder, o = fstr(b, 0x1C)
    print("folderName@0x1C:", repr(folder), "-> next", hex(o))
    p = o
    for name in ("PackageFlags", "NameCount", "NameOffset", "LocalizationId",
                 "GatherableCount", "GatherableOffset", "ExportCount",
                 "ExportOffset", "ImportCount", "ImportOffset", "DependsOffset",
                 "SoftPkgCount", "SoftPkgOffset", "SearchableNamesOffset",
                 "ThumbnailTableOffset"):
        if name.endswith("Id") or name == "LocalizationId":
            v, p = fstr(b, p)
            if p > len(b):
                print("  !! ran past end at", name)
                return
            print(f"  @{hex(p)} {name} = {v!r}")
            continue
        v = i32(b, p)
        print(f"  @{hex(p)} {name} = {v}")
        p += 4
    print("guid @", hex(p), b[p:p + 16].hex())
    p += 16
    ngen = i32(b, p); p += 4
    print("  generations", ngen)
    for _ in range(ngen):
        print("   ", i32(b, p), i32(b, p + 4)); p += 8
    print("  engineVersion @", hex(p), "u16x3", struct.unpack_from("<HHH", b, p), "changelist", u32(b, p + 6))
    p += 10
    branch, p = fstr(b, p)
    print("  branch", repr(branch), "@", hex(p))


probe(F)
probe(F2)
