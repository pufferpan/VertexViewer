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
sel = None
for rn, props in rows:
    if want in rn.lower() and "COD" not in rn:
        sel = (rn, props)
        break
rn, props = sel
print("row", rn)
for p in props:
    print("  prop", p)
m = [p for p in props if p[0] == "TransformMap"][0]
o, ln = m[4], m[5]
raw = data[o:o + ln]

print("\nhexdump of TransformMap value (%d bytes) @export offset %d" % (len(raw), o))
for i in range(0, len(raw), 16):
    chunk = raw[i:i + 16]
    hexs = " ".join("%02x" % b for b in chunk)
    txt = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
    # decode 8-byte aligned names
    dec = []
    for j in range(0, len(chunk) - 7, 8):
        idx, num = struct.unpack_from("<ii", chunk, j)
        if 0 <= idx < len(names) and num in (0, 1):
            dec.append("%s(%d)" % (names[idx], idx))
    print("%5d  %-47s  %-16s  %s" % (i, hexs, txt, " ".join(dec)))
