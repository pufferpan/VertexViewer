import os
import struct
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
for _p in (os.path.join(BASE, "work"), os.path.join(BASE, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import dtparse                                        # noqa: E402
import mini_upk as mu                                 # noqa: E402
from core import loader                               # noqa: E402

VP = "../../../DeltaForce/Content/DataTables/WeaponAppearance/WeaponSocketTransformTable.uasset"
ua = loader.read_entry(VP)
ue = loader.read_entry(VP[:-7] + ".uexp")
upk = mu.Upk(ua, ue)
names = upk.names
data = upk.export_data(upk.exports[0])
rows, _e, n = dtparse.walk(data, names)
tags = dtparse.Tags(names)

want = (sys.argv[1] if len(sys.argv) > 1 else "M4A1").lower()
for rn, props in rows:
    if want in rn.lower() and "COD" not in rn:
        rn0, props0 = rn, props
        break
print("row", rn0)
m = [p for p in props0 if p[0] == "TransformMap"][0]
print(" TransformMap", m)


def parse_struct_val(r):
    """tagged property list -> dict name -> (type, size, [values])"""
    out = []
    while True:
        st = r.o
        nm = tags.nm(r)
        if nm == "None":
            return out
        r.o = st
        name, typ, size, aidx, vstart, vlen = tags.tag(r)
        out.append((name, typ, vlen, vstart))


def quat(d, o):
    return struct.unpack_from("<4f", d, o)


def vec(d, o):
    return struct.unpack_from("<3f", d, o)


r = dtparse.Rd(data, m[4])
nk = r.i32()
num = r.i32()
print("numkeys_remove=%d num=%d" % (nk, num))
for i in range(num):
    key = tags.nm(r)
    fields = parse_struct_val(r)
    print(" anim state:", key)
    anim = None
    for name, typ, vlen, vstart in fields:
        if name == "AnimName":
            anim = dtparse.fname_val(data, vstart, names)
        elif name == "SocketTransformMap":
            print("   AnimName =", anim, " socketmap size", vlen)
            rr = dtparse.Rd(data, vstart)
            nk2 = rr.i32()
            n2 = rr.i32()
            for j in range(n2):
                k2 = tags.nm(rr)
                f2 = parse_struct_val(rr)
                vals = {}
                for name2, typ2, vlen2, vstart2 in f2:
                    if name2 == "Rotation":
                        vals["rot"] = quat(data, vstart2)
                    elif name2 == "Translation":
                        vals["loc"] = vec(data, vstart2)
                    elif name2 == "Scale3D":
                        vals["scale"] = vec(data, vstart2)
                print("      %-24s %s" % (k2, vals))
