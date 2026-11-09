"""Inspect pak records + zlib block structure for a suspicious bulk texture."""
import json
import os
import sys
import zlib

sys.path.insert(0, ".")

from tools import pakpick
from core.pak import PakFile, load_keyvault

P = ("../../../DeltaForce/Content/GenTexDirHD/Game/Environment/Structures/"
     "Morocco/00_CommonMaterial/HD/Textures/"
     "T_VMGen_NormalMap_bcd33961fe1c69c01da7c0205d4b20cf")

idx = json.load(open(pakpick.IDX))
kv = load_keyvault(pakpick.VAULT)
cache = {}
for ext in (".uasset", ".uexp", ".ubulk", ".uptnl"):
    vp = P + ext
    if vp not in idx:
        print(ext, "not in index")
        continue
    pak, loc = idx[vp]
    pf = cache.get(pak)
    if pf is None:
        pf = cache[pak] = PakFile(os.path.join(pakpick.PAK_DIR, pak), kv)
    key = vp.replace("../../../DeltaForce/", "")
    rec = pf.record(key)
    print(ext, pak, "rec=", rec)
    raw = pf.raw(key)
    print("   raw", len(raw or b""), (raw or b"")[:24].hex(" "))
    if ext in (".ubulk", ".uptnl") and raw:
        # walk concatenated zlib members
        buf = raw
        total = 0
        n = 0
        while buf and n < 64:
            try:
                d = zlib.decompressobj()
                out = d.decompress(buf)
            except Exception as exc:
                print("   zlib stop at member", n, "err", exc)
                break
            total += len(out)
            n += 1
            buf = d.unused_data
            if not buf:
                break
        print("   zlib members", n, "total out", total, "left", len(buf or b""))
