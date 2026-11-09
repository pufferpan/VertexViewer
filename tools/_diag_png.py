"""Decode candidate mip blobs to PNG so we can eyeball them."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np  # noqa: E402
import texture2ddecoder  # noqa: E402
from PIL import Image  # noqa: E402
from tools.mini_upk import Upk, parse_properties  # noqa: E402

S = r"G:\xmcl-fetch\work\samples"
OUT = r"G:\xmcl-fetch\work"
base = "T_VMGen_BaseColorMap_993eca56b1014c50d99948ab48a30e9a"
ua = open(os.path.join(S, base + ".uasset"), "rb").read()
ue = open(os.path.join(S, base + ".uexp"), "rb").read()
ub = open(os.path.join(S, base + ".ubulk"), "rb").read()
upk = Upk(ua, ue, ub)
data = upk.export_data(upk.exports[0])
props, end = parse_properties(upk, data)
print("props end 0x%x data %d ubulk %d" % (end, len(data), len(ub)))


def save(src, off, w, h, name):
    need = ((w + 3) // 4) * ((h + 3) // 4) * 16
    blob = src[off:off + need]
    if len(blob) < need:
        print(f"  {name}: only {len(blob)}/{need}")
        return None
    rgba = texture2ddecoder.decode_bc7(blob, w, h)
    a = np.frombuffer(rgba, dtype=np.uint8).reshape(h, w, 4).copy()
    # BC7 decoder returns bottom-up rows
    a = a[::-1]
    p = os.path.join(OUT, name)
    Image.fromarray(a, "RGBA").save(p)
    print(f"  saved {name} mean={a[:, :, :3].mean():.1f} std={a[:, :, :3].std():.1f}")
    return a


print("ubulk candidates:")
save(ub, 0, 256, 256, "tex_bulk_256.png")
save(ub, 65536, 128, 128, "tex_bulk_mip1_128.png")
print("uexp candidates:")
save(data, 0x23A, 64, 64, "tex_uexp_23a_64.png")
save(data, 0x23A, 128, 128, "tex_uexp_23a_128.png")
save(data, len(data) - 4096, 64, 64, "tex_uexp_tail64.png")
save(data, end, 64, 64, "tex_uexp_end_64.png")
