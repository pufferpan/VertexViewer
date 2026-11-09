"""PartSocketsTable：紧凑打印 SocketName / SocketPartType / 标志位。"""
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

VP = "../../../DeltaForce/Content/DataTables/WeaponPart/PartSocketsTable.uasset"
ua = loader.read_entry(VP)
ue = loader.read_entry(VP[:-7] + ".uexp")
upk = mu.Upk(ua, ue)
data = upk.export_data(upk.exports[0])
rows, _e, _n = dtparse.walk(data, upk.names)
names = upk.names
print("rows", len(rows))


def get(props, key):
    for name, typ, size, aidx, vstart, vlen in props:
        if name == key:
            return typ, vstart, vlen
    return None, 0, 0


for rn, props in rows:
    out = {}
    for key in ("SocketId", "SocketName", "SocketPartType", "bIsCommon", "bDefaultHide", "CamPoint"):
        typ, vs, vl = get(props, key)
        if typ is None:
            out[key] = "-"
        elif typ == "NameProperty":
            i = struct.unpack_from("<i", data, vs)[0]
            out[key] = names[i]
        elif typ == "UInt32Property":
            out[key] = struct.unpack_from("<I", data, vs)[0]
        elif typ == "EnumProperty":
            i = struct.unpack_from("<i", data, vs)[0]
            out[key] = names[i].split("::")[-1]
        elif typ == "BoolProperty":
            out[key] = bool(data[vs - 1]) if vl == 0 else bool(data[vs])
        else:
            out[key] = "?"
    print("%-3s %-28s %-22s common=%-5s hide=%-5s %s" % (
        out["SocketId"], out["SocketName"], out["SocketPartType"],
        out["bIsCommon"], out["bDefaultHide"], out["CamPoint"]))
