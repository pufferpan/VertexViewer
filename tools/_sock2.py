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

vp = "../../../DeltaForce/Content/DataTables/WeaponPart/WeaponPartsMeshSocketNameInfo.uasset"
ua = loader.read_entry(vp)
ue = loader.read_entry(vp[:-7] + ".uexp")
upk = mu.Upk(ua, ue)
names = upk.names
data = upk.export_data(upk.exports[0])
rows, _e, n = dtparse.walk(data, names)

want = sys.argv[1] if len(sys.argv) > 1 else "M4A1"
hits = [(rn, ps) for rn, ps in rows if want.lower() in rn.lower()]
print("hits", len(hits))
for rn, ps in hits[:2]:
    print("row", rn)
    for name, typ, size, aidx, vstart, vlen in ps:
        raw = data[vstart:vstart + vlen]
        print(f"  {name:16s} {typ:16s} len={vlen} hex={raw.hex()}")
        if typ == "ArrayProperty":
            cnt = struct.unpack_from("<i", data, vstart)[0]
            print("     count", cnt, "remain", vlen - 4, "per", (vlen - 4) / max(cnt, 1))
            for k in range(cnt):
                i, num = struct.unpack_from("<ii", data, vstart + 4 + 8 * k)
                print("       [%d] %s (%d)" % (k, names[i] if 0 <= i < len(names) else "?", i))
