"""Walk concatenated zlib members inside a bulk stream (virtual-texture case)."""
import zlib

import sys
sys.path.insert(0, ".")

from tools import pakpick
from tools.mini_upk import Upk, parse_properties

P = ("../../../DeltaForce/Content/GenTexDirHD/Game/Environment/Structures/"
     "Morocco/00_CommonMaterial/HD/Textures/"
     "T_VMGen_NormalMap_bcd33961fe1c69c01da7c0205d4b20cf")


def walk(buf, limit=4096):
    total, n, sizes = 0, 0, []
    while buf and n < limit:
        d = zlib.decompressobj()
        try:
            out = d.decompress(buf)
            out += d.flush()
        except Exception as exc:
            print("   stop at member", n, exc)
            break
        sizes.append(len(out))
        total += len(out)
        n += 1
        buf = d.unused_data
        if not buf:
            break
    return n, total, sizes, len(buf or b"")


for ext in (".ubulk", ".uptnl"):
    vp = P + ext
    try:
        b = pakpick.extract(vp)
    except KeyError:
        print(ext, "missing")
        continue
    print(ext, len(b), b[:16].hex(" "))
    n, total, sizes, left = walk(b)
    print("   members", n, "total", total, "first sizes", sizes[:10], "left", left)
