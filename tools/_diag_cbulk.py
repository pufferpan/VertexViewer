"""Probe a texture whose .ubulk/.uptnl sizes are not raw BC7 (compressed bulk?)."""
import struct
import sys

sys.path.insert(0, ".")

from tools import pakpick
from tools.mini_upk import Upk, parse_properties
from core import texture as T

P = ("../../../DeltaForce/Content/GenTexDirHD/Game/Models/"
     "Equipments/Glasses/M_Head_Glasses_Glass_MilitaryFan_050/Textures/"
     "T_VMGen_NormalMap_bcd33961fe1c69c01da7c0205d4b20cf")


def get(ext):
    try:
        return pakpick.extract(P + ext)
    except Exception:
        return None


ua, ue, ub, up = get(".uasset"), get(".uexp"), get(".ubulk"), get(".uptnl")
print("sizes", len(ua or b""), len(ue or b""), len(ub or b""), len(up or b""))
upk = Upk(ua, ue, ub)
print("names", len(upk.names), "imports", len(upk.imports), "exports", len(upk.exports))
exp = upk.exports[0]
print("export", exp.name, "serial", exp.serial_size, exp.serial_offset,
      "hdr", upk.total_header_size)
data = upk.export_data(exp)
print("payload len", len(data))
props, end = parse_properties(upk, data)
print("props end", hex(end), [(p.name, p.type, p.size) for p in props])
print("raw after props:", data[end:end + 220].hex(" "))

pf, pf_pos = T._find_pixel_format(data)
print("pf", pf, hex(pf_pos) if pf_pos else None)
print("dims", T._platform_dims(data, pf_pos) if pf_pos else None)

if up:
    print("uptnl head", up[:64].hex(" "))
    oo = pakpick.oodle()
    for target in (1048576, 262144, 65536):
        try:
            out = oo.decompress(up, target)
            print("oodle whole-stream ->", target, "OK", len(out))
            break
        except Exception as exc:
            print("oodle whole-stream", target, "fail", type(exc).__name__, exc)
    # UE bulk-compressed layout: u32 block_size, u32 block_count, count*size
    if len(up) > 8:
        bs, bc = struct.unpack_from("<II", up, 0)
        print("as block header: block_size", bs, "block_count", bc)
        if 1 <= bc <= 64 and 0x100 <= bs <= 0x40000 and 8 + bc * 4 <= len(up):
            sizes = struct.unpack_from("<%dI" % bc, up, 8)
            print("  block sizes", sizes[:8], "sum", sum(sizes))
            off = 8 + bc * 4
            for i in range(min(bc, 4)):
                try:
                    out = oo.decompress(up[off:off + sizes[i]], 1048576 // bc)
                    print("  block", i, "->", len(out), out[:16].hex(" "))
                except Exception as exc:
                    print("  block", i, "fail", type(exc).__name__)
                off += sizes[i]
