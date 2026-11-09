import os
import struct
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
for _p in (os.path.join(BASE, "work"), os.path.join(BASE, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np                                    # noqa: E402

import mini_upk as mu                                 # noqa: E402
from core import loader                               # noqa: E402

vp = sys.argv[1]
ua = loader.read_entry(vp)
ue = loader.read_entry(vp[:-7] + ".uexp")
upk = mu.Upk(ua, ue)
names = upk.names

CAND = ["Mag_point", "Mag_CL_point", "Trigger_Point", "bullet_chamber_point",
        "Bolt_Release", "Gun_bolt", "Gun_Cover", "Gun_Part01", "FireModeBone",
        "Weapon_3P", "b_IK_Gun", "b_IK_Hand_Root", "S_root", "Root"]
idx_of = {}
for i, nm in enumerate(names):
    if nm in CAND:
        idx_of.setdefault(nm, i)
print("socket-ish name indices:", idx_of)
print("exports:", [(e.name, e.offset, e.size) for e in upk.exports])

for nm, idx in idx_of.items():
    pat = struct.pack("<ii", idx, 0)
    where = []
    for buf_label, buf in (("uexp", ue), ("uasset", ua)):
        start = 0
        while True:
            k = buf.find(pat, start)
            if k < 0:
                break
            where.append((buf_label, k))
            start = k + 1
    print("%-22s idx=%-4d hits=%s" % (nm, idx, where[:6]))
    for label, k in where[:3]:
        buf = ue if label == "uexp" else ua
        chunk = buf[k:k + 64]
        vals = struct.unpack_from("<9f", buf, k + 16) if k + 16 + 36 <= len(buf) else None
        nxt = struct.unpack_from("<ii", buf, k + 8) if k + 16 <= len(buf) else None
        print("    @%s+%d next=(%s) floats=%s" % (
            label, k, nxt,
            None if vals is None else tuple(round(v, 3) for v in vals)))
        _ = np
