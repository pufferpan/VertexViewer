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

TYPES = {nm for nm in names if nm.endswith("Property")} | {"None"}
print("known type names:", sorted(TYPES))

want = (sys.argv[1] if len(sys.argv) > 1 else "M4A1").lower()
for rn, props in rows:
    if want in rn.lower() and "COD" not in rn:
        rn0, props0 = rn, props
        break
m = [p for p in props0 if p[0] == "TransformMap"][0]
blob = data[m[4]:m[4] + m[5]]
print("row", rn0, "blob", len(blob))


def fname(o):
    i, num = struct.unpack_from("<ii", blob, o)
    if not (0 <= i < len(names)) or num not in (0, 1):
        return None
    return names[i] if num == 0 else f"{names[i]}_{num-1}"


print("\ntag starts (name + type):")
for o in range(0, len(blob) - 15):
    a = fname(o)
    if a is None:
        continue
    b = fname(o + 8)
    if b in TYPES:
        print(f"  @{o:4d} {a:>22s} : {b}")
