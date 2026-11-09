"""Dump names + nested tagged struct arrays of a material instance."""
import sys

sys.path.insert(0, ".")

from tools import pakpick
from tools.mini_upk import Upk, parse_properties

VP = ("../../../DeltaForce/Content/Models/Vehicles/LAV25/Appearance_Base/Materials/"
      "Destructed/MI_LAV25_Destructed_3.uasset")


def blobs(vpath):
    base = vpath[:-len(".uasset")]
    out = {}
    for ext in (".uasset", ".uexp", ".ubulk"):
        try:
            out[ext] = pakpick.extract(base + ext)
        except KeyError:
            out[ext] = None
    return out


b = blobs(VP)
upk = Upk(b[".uasset"], b[".uexp"], b[".ubulk"])
print("names:")
for i, n in enumerate(upk.names):
    print(f"  {i:3d} {n}")
print("imports):")
for i, im in enumerate(upk.imports):
    print(f"  imp {i:2d} pkg={im.class_package!r} cls={im.class_name!r} "
          f"name={im.name!r} outer={im.outer}")
print("exports:")
for i, e in enumerate(upk.exports):
    print(f"  {i} cls={upk.class_name_of(e)!r} name={e.name!r} off={e.serial_offset} size={e.serial_size}")

data = upk.export_data(upk.exports[0])
props, end = parse_properties(upk, data)
for p in props:
    print("-" * 90)
    print(p.name, p.type, "size", p.size, "extra", p.extra)
    if p.type != "ArrayProperty":
        print("   raw", p.value.hex() if isinstance(p.value, bytes) else p.value)
        continue
    inner = p.value
    import struct
    count = struct.unpack_from("<i", inner, 0)[0]
    print("   count", count, "len", len(inner))
    pos = 4
    for k in range(count):
        sub, pos = parse_properties(upk, inner, pos)
        print(f"   [elem {k}]")
        for q in sub:
            print(f"      {q.name:<20} {q.type:<16} size={q.size:<5} "
                  f"extra={q.extra} raw={q.value.hex()[:80] if isinstance(q.value, bytes) else q.value}")
    break
