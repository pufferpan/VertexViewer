"""Visual sanity check for a normal map + base color from GenTexDirHD."""
import json
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, ".")

from tools import pakpick
from core import texture as T

paths = [p for p in json.load(open("tools/_tex_paths.json"))
         if "GenTexDirHD" in p and "NRMap" in p]
want = sys.argv[1] if len(sys.argv) > 1 else "NRMap"
sel = [p for p in paths if want in p][:1]
if not sel:
    raise SystemExit("no path for " + want)
p = sel[0]
print(p)
d = p.rsplit(".", 1)[0]


def g(e):
    try:
        return pakpick.extract(d + e)
    except Exception:
        return None


ua, ue, ub, up = g(".uasset"), g(".uexp"), g(".ubulk"), g(".uptnl")
inf = T.inspect_texture(ua, ue, ub, up)
print({k: inf[k] for k in ("ok", "error", "pixel_format", "sx", "sy", "mip_count",
                          "source", "compression")})
tex = T.load_texture(ua, ue, ub, d + ".uasset", uptnl=up)
print("decoded", tex.width, tex.height, tex.source_format, tex.srgb)
a = tex.rgba
print("means R G B A", a[..., 0].mean().round(1), a[..., 1].mean().round(1),
      a[..., 2].mean().round(1), a[..., 3].mean().round(1))
tag = want.lower()
Image.fromarray(a[:, :, :3]).resize((512, 512)).save(f"G:/xmcl-fetch/work/texdbg_{tag}_rgb.png")
Image.fromarray(a[:, :, 0]).resize((512, 512)).save(f"G:/xmcl-fetch/work/texdbg_{tag}_r.png")
Image.fromarray(a[:, :, 3]).resize((512, 512)).save(f"G:/xmcl-fetch/work/texdbg_{tag}_a.png")
