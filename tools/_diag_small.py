"""Dump the platform-data / inline-mip region of an all-inline texture."""
import struct
import sys

sys.path.insert(0, ".")

from tools import pakpick
from tools.mini_upk import Upk, parse_properties

P = ("../../../DeltaForce/Content/GenTexDirHD/Game/Models/Equipments/Glasses/"
     "M_Head_Glasses_Glass_MilitaryFan_050/Textures/"
     "T_VMGen_NRMap_a1cecfebcb32c4e8122196392deda099")


def get(ext):
    try:
        return pakpick.extract(P + ext)
    except KeyError:
        return None


ua, ue = get(".uasset"), get(".uexp")
upk = Upk(ua, ue)
exp = upk.exports[0]
data = upk.export_data(exp)
props, end = parse_properties(upk, data)
print("payload", len(data), "props end", hex(end))
print("props", [(p.name, p.type, p.size) for p in props])
pfpos = data.find(b"PF_BC7")
print("PF at", hex(pfpos))
for i in range(end, min(len(data), end + 400), 4):
    v = struct.unpack_from("<I", data, i)[0]
    print(f"  {i:#06x} {v:#010x} {v}")
