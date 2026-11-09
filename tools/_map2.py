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

want = (sys.argv[1] if len(sys.argv) > 1 else "M4A1").lower()
for rn, props in rows:
    if want not in rn.lower() or "COD" in rn:
        continue
    m = [p for p in props if p[0] == "TransformMap"][0]
    raw = data[m[4]:m[4] + m[5]]
    break

def nm(o):
    i, num = struct.unpack_from("<ii", raw, o)
    s = names[i] if 0 <= i < len(names) else f"<{i}>"
    return s + (f"_{num-1}" if num else "")

print("map bytes", len(raw), "header i32:", struct.unpack_from("<ii", raw, 0))
print("first 12 FNames(8B):", [nm(8 + 8 * i) for i in range(12)])

target = 0x16e  # StructProperty
print("\nStructProperty tag candidates:")
for o in range(0, len(raw) - 48, 1):
    if struct.unpack_from("<ii", raw, o) == (target, 0):
        print(f"  @{o}: name={nm(o)} type={nm(o+8)} size={struct.unpack_from('<i', raw, o+16)[0]} "
              f"aidx={struct.unpack_from('<i', raw, o+20)[0]} "
              f"next16={raw[o+24:o+40].hex()} then {nm(o+40)}")
