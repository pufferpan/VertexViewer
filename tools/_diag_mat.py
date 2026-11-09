"""Dump UMaterialInstanceConstant properties for a few real DE material assets."""
import sys

sys.path.insert(0, ".")

from tools import pakpick
from tools.mini_upk import Upk, parse_properties

CANDIDATES = [
    "../../../DeltaForce/Content/Models/Characters_HD/Hero_HD/M_Roy_HD/M_Roy_016_HD/Materials/3P/MI_Roy_Haavk_051_Lower_3P.uasset",
    "../../../DeltaForce/Content/Models/Vehicles/Tiltrotor/Appearance_Base/Materials/MI_Tiltrotor_01.uasset",
    "../../../DeltaForce/Content/Models/Vehicles/LAV25/Appearance_Base/Materials/Destructed/MI_LAV25_Destructed_3.uasset",
]


def blobs(vpath):
    base = vpath[:-len(".uasset")]
    out = {}
    for ext in (".uasset", ".uexp", ".ubulk", ".uptnl"):
        try:
            out[ext] = pakpick.extract(base + ext)
        except KeyError:
            out[ext] = None
    return out


for vp in CANDIDATES:
    print("=" * 100)
    print(vp)
    b = blobs(vp)
    print("sizes", {k: (len(v) if v else None) for k, v in b.items()})
    upk = Upk(b[".uasset"], b[".uexp"], b[".ubulk"])
    print("names", len(upk.names), "imports", len(upk.imports), "exports", len(upk.exports))
    for i, e in enumerate(upk.exports):
        print(f"  export {i}: class={upk.class_name_of(e)!r} name={e.name!r} "
              f"size={e.serial_size} off={e.serial_offset}")
    print("  imports:", [(i.class_package, i.class_name, i.name) for i in upk.imports][:20])
    data = upk.export_data(upk.exports[0])
    props, end = parse_properties(upk, data)
    print("  props end", hex(end), "data", len(data))
    for p in props:
        val = p.value
        if isinstance(val, bytes):
            show = val[:48].hex()
        else:
            show = repr(val)[:120]
        print(f"   {p.name:<28} {p.type:<22} size={p.size:<5} {show}")
