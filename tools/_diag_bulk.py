"""Inspect pak records + siblings for the AH_64E texture, and try BC7 decodes of .ubulk."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools import pakpick  # noqa: E402
from core.pak import PakFile, load_keyvault  # noqa: E402

VP = ("../../../DeltaForce/Content/GenTexDirHD/Game/Models/Vehicles/AH_64E/"
      "Appearance_Base/Textures/T_VMGen_BaseColorMap_993eca56b1014c50d99948ab48a30e9a")

idx = json.load(open(pakpick.IDX, "r", encoding="utf-8"))
pak_name = idx[VP + ".uasset"][0]
pak = os.path.join(pakpick.PAK_DIR, pak_name)
print("pak:", pak_name)
kv = load_keyvault(pakpick.VAULT)
pf = PakFile(pak, kv)
od = pakpick.oodle()

for ext in (".uasset", ".uexp", ".ubulk", ".uptnl"):
    rec = pf.record(VP + ext)
    if rec is None:
        print(f"{ext:8s} <no record>")
        continue
    print(f"{ext:8s} kind={rec['kind']:9s} method={rec['method']:5s} usize={rec['usize']:8d} "
          f"csize={rec['csize']:8d} blocks={len(rec['blocks'])} enc={rec['encrypted']} blocksz={rec['block_size']}")

d = VP.rsplit("/", 1)[0] + "/"
print("\ndir in pak:")
for k in sorted(pf.entries):
    if d in k:
        rec = pf.record(k)
        print(f"   {k.rsplit('/', 1)[-1]:70s} {rec['usize'] if rec else '-'}")

ub = pf.read(VP + ".ubulk", od)
print("\nubulk decompressed:", len(ub) if ub else None)
if ub:
    import numpy as np
    import texture2ddecoder
    for (w, h) in ((256, 256), (128, 128), (512, 512), (64, 64)):
        need = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 16
        if need > len(ub):
            print(f"  BC7 {w}x{h}: needs {need} > {len(ub)}")
            continue
        rgba = texture2ddecoder.decode_bc7(ub[:need], w, h)
        a = np.frombuffer(rgba, dtype=np.uint8)
        print(f"  BC7 {w}x{h}: mean={a.mean():.1f} std={a.std():.1f} uniq={len(set(a[:8000].tolist()))}")
