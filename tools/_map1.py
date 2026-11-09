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
print("names:", len(upk.names), "exports:", len(upk.exports))
data = upk.export_data(upk.exports[0])
rows, _e, n = dtparse.walk(data, upk.names)
print("rows", len(rows), n)

want = (sys.argv[1] if len(sys.argv) > 1 else "M4A1").lower()
for rn, props in rows:
    if want not in rn.lower():
        continue
    print("ROW", rn)
    for nm, typ, size, aidx, vs, vl in props:
        print("  ", nm, typ, size, "vstart", vs, "vlen", vl)
        if nm == "TransformMap":
            raw = data[vs:vs + vl]
            for i in range(0, len(raw), 16):
                seg = raw[i:i + 16]
                print(f"   {i:4} {' '.join(f'{c:02x}' for c in seg)}")
    break
