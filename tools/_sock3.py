"""WeaponPartsMeshSocketNameInfo：按 count + 53 偏移解 SocketLocation/SocketRotation。"""
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

VP = "../../../DeltaForce/Content/DataTables/WeaponPart/WeaponPartsMeshSocketNameInfo.uasset"
PATTERNS = sys.argv[1:] or ["Rec_AR_M4A1", "Bar_S-370_M4A1", "Sto_A_M4A1", "Sco_"]


def load_rows():
    ua = loader.read_entry(VP)
    ue = loader.read_entry(VP[:-7] + ".uexp")
    upk = mu.Upk(ua, ue)
    data = upk.export_data(upk.exports[0])
    rows, _e, _n = dtparse.walk(data, upk.names)
    return data, upk.names, rows


def fn(d, o):
    i, num = struct.unpack_from("<ii", d, o)
    return i


data, names, rows = load_rows()
print("rows", len(rows))
by_pat = {}
for rn, props in rows:
    for pat in PATTERNS:
        if pat.lower() in rn.lower():
            by_pat.setdefault(pat, []).append((rn, props))

for pat, items in by_pat.items():
    print("\n########", pat, len(items))
    for rn, props in items[:3]:
        print("ROW", rn.split("/")[-1])
        for name, typ, size, aidx, vstart, vlen in props:
            if name == "SocketNames":
                cnt = struct.unpack_from("<i", data, vstart)[0]
                got = [names[fn(data, vstart + 4 + 8 * k)] for k in range(cnt)]
                print("   names  (%d) %s" % (cnt, got))
            elif name in ("SocketLocation", "SocketRotation"):
                cnt = struct.unpack_from("<i", data, vstart)[0]
                off = vstart + 4 + 49
                vals = []
                for k in range(cnt):
                    if off + 12 * (k + 1) > vstart + vlen + 12:
                        break
                    vals.append(tuple(round(v, 3) for v in
                                      struct.unpack_from("<3f", data, off + 12 * k)))
                print("   %-15s cnt=%d vlen=%d %s" % (name, cnt, vlen, vals))
            elif name == "RootBoneName":
                print("   rootbone =", names[fn(data, vstart)])
