"""Find inline mip start + check .uptnl (optional payload) for streamed mip0."""
import os
import sys

sys.path.insert(0, r"G:\xmcl-fetch\vertexviewer")
import numpy as np  # noqa: E402
import texture2ddecoder  # noqa: E402
from PIL import Image  # noqa: E402
from tools.mini_upk import Upk, parse_properties  # noqa: E402

S = r"G:\xmcl-fetch\work\samples"
VP = "../../../DeltaForce/Content/GenTexDirHD/Game/Models/Vehicles/AH_64E/Appearance_Base/Textures/T_VMGen_BaseColorMap_993eca56b1014c50d99948ab48a30e9a"
base = "T_VMGen_BaseColorMap_993eca56b1014c50d99948ab48a30e9a"


def dec(blob, w, h):
    rgba = texture2ddecoder.decode_bc7(blob, w, h)
    return np.frombuffer(rgba, dtype=np.uint8).reshape(h, w, 4)[::-1]


ue = open(os.path.join(S, base + ".uexp"), "rb").read()
ua = open(os.path.join(S, base + ".uasset"), "rb").read()
ub = open(os.path.join(S, base + ".ubulk"), "rb").read()
upk = Upk(ua, ue, ub)
d = upk.export_data(upk.exports[0])
print("export data", len(d), "ubulk", len(ub))

ref256 = dec(ub[:65536], 256, 256)
ref64 = np.asarray(Image.fromarray(ref256[:, :, :3]).resize((64, 64), Image.LANCZOS)).astype(np.float32)

best = []
for off in range(0x200, 0x400):
    blob = d[off:off + 4096]
    if len(blob) < 4096:
        break
    im = dec(blob, 64, 64)[:, :, :3].astype(np.float32)
    diff = np.abs(im - ref64).mean()
    best.append((diff, off))
best.sort()
print("best 64x64 offsets vs ubulk 256 downscaled:")
for diff, off in best[:6]:
    print("  0x%03x diff=%.2f" % (off, diff))
tail = np.abs(dec(d[-4096:], 64, 64)[:, :, :3].astype(np.float32) - ref64).mean()
print("  tail 0x%03x diff=%.2f" % (len(d) - 4096, tail))

# upside down variant (maybe no flip needed)
print()
try:
    from tools.pakpick import extract
    up = extract(VP + ".uptnl")
except Exception as e:
    up = None
    print("uptnl read failed:", type(e).__name__, e)
if up is not None:
    print("uptnl size", len(up))
    open(os.path.join(S, base + ".uptnl"), "wb").write(up)
    for w, h in ((512, 512), (256, 256)):
        need = (w // 4) * (h // 4) * 16
        if len(up) >= need:
            im = dec(up[:need], w, h)
            print("  uptnl as %dx%d mean=%.1f std=%.1f" % (w, h, im[:, :, :3].mean(), im[:, :, :3].std()))
            Image.fromarray(im, "RGBA").save(r"G:\xmcl-fetch\work\tex_uptnl_%d.png" % w)
