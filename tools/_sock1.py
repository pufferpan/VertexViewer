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


def load(vp):
    ua = loader.read_entry(vp)
    ue = loader.read_entry(vp[:-7] + ".uexp")
    upk = mu.Upk(ua, ue)
    data = upk.export_data(upk.exports[0])
    rows, _e, n = dtparse.walk(data, upk.names)
    return upk, data, rows


vp = "../../../DeltaForce/Content/DataTables/WeaponPart/WeaponPartsMeshSocketNameInfo.uasset"
upk, data, rows = load(vp)
names = upk.names
tags = dtparse.Tags(names)
print("names", len(names), "rows", len(rows))

want = sys.argv[1] if len(sys.argv) > 1 else "M4A1"
hits = [(rn, ps) for rn, ps in rows if want.lower() in rn.lower()]
print("hits", len(hits))
for rn, ps in hits[:3]:
    print("row", rn)
    for name, typ, size, aidx, vstart, vlen in ps:
        raw = data[vstart:vstart + vlen]
        if typ == "ArrayProperty":
            cnt = struct.unpack_from("<i", data, vstart)[0]
            print(f"  {name:16s} {typ} size={vlen} count={cnt} hex={raw[:64].hex()}")
            # try FName array
            if name == "SocketNames":
                for k in range(cnt):
                    i, num = struct.unpack_from("<ii", data, vstart + 4 + 8 * k)
                    print("      name[%d] = %s (%d)" % (k, names[i] if 0 <= i < len(names) else "?", i))
        else:
            print(f"  {name:16s} {typ:20s} {raw[:48].hex()}")
