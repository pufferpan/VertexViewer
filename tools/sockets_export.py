"""校验 WeaponPartsMeshSocketNameInfo 全表：确认 vlen == 53 + 12*count，导出 JSON 缓存。

用法：
    python tools/sockets_export.py            # 校验 + 写缓存
    python tools/sockets_export.py --report   # 只校验并打印覆盖率
"""
import json
import os
import struct
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
for _p in (os.path.join(BASE, "work"), os.path.join(BASE, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import dtparse                                        # noqa: E402
import mini_upk as mu                                 # noqa: E402
from core import loader                                # noqa: E402

VP = "../../../DeltaForce/Content/DataTables/WeaponPart/WeaponPartsMeshSocketNameInfo.uasset"
CACHE = os.path.join(os.environ.get("LOCALAPPDATA", "."), "VertexViewer", "weapon_sockets.json")
ROT_FORMAT = "FRotator(Pitch,Yaw,Roll) deg"


def key_of(row_name):
    """'/Game/Models/.../X_3P.X_3P' -> 'models/weapons/.../x_3p'"""
    pkg = row_name.split(".")[0]
    if pkg.startswith("/Game/"):
        pkg = pkg[len("/Game/"):]
    return pkg.strip("/").lower()


def parse(data, names):
    rows, _e, _n = dtparse.walk(data, names)
    out = {}
    bad = []
    for rn, props in rows:
        d = {}
        cnt = 0
        for name, typ, size, aidx, vstart, vlen in props:
            if name == "SocketNames":
                cnt = struct.unpack_from("<i", data, vstart)[0]
                nm = [names[struct.unpack_from("<i", data, vstart + 4 + 8 * k)[0]]
                      for k in range(cnt) if vstart + 12 + 8 * k <= vstart + vlen]
                d["names"] = nm
            elif name in ("SocketLocation", "SocketRotation"):
                c2 = struct.unpack_from("<i", data, vstart)[0]
                if vlen != 53 + 12 * c2:
                    bad.append((rn, name, c2, vlen))
                    continue
                off = vstart + 53
                d["loc" if name == "SocketLocation" else "rot"] = [
                    list(struct.unpack_from("<3f", data, off + 12 * k)) for k in range(c2)]
            elif name == "RootBoneName":
                d["root"] = names[struct.unpack_from("<i", data, vstart)[0]]
        if "names" in d:
            out[key_of(rn)] = [d.get("names", []), d.get("loc", []), d.get("rot", [])]
    return out, bad, len(rows)


def main():
    t0 = time.time()
    ua = loader.read_entry(VP)
    ue = loader.read_entry(VP[:-7] + ".uexp")
    upk = mu.Upk(ua, ue)
    data = upk.export_data(upk.exports[0])
    table, bad, n = parse(data, upk.names)
    print("rows=%d  parsed=%d  size-mismatch=%d  %.1fs" % (n, len(table), len(bad), time.time() - t0))
    for b in bad[:5]:
        print("  MISMATCH", b)
    # 覆盖：每个 mesh 的 socket 数分布
    cnts = {}
    for k, v in table.items():
        cnts[len(v[0])] = cnts.get(len(v[0]), 0) + 1
    print("socket-count distribution:", sorted(cnts.items())[:12], "…")
    key_names = ("bar_point", "han_point", "sto_point", "pisg_point", "sco_point",
                 "muzzle_point", "mag_point", "for_point", "rea_point", "mou_point")
    have = {kn: 0 for kn in key_names}
    for k, v in table.items():
        low = [x.lower() for x in v[0]]
        for kn in key_names:
            if kn in low:
                have[kn] += 1
    print("meshes containing socket:", have)
    if "--report" in sys.argv:
        return
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump({"format": ROT_FORMAT, "unit": "cm", "sockets": table}, f)
    print("wrote", CACHE, os.path.getsize(CACHE), "bytes")


if __name__ == "__main__":
    main()
