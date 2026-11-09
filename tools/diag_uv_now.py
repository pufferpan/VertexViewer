"""UV 诊断：内存路径 vs .uemodel 往返路径，外加原始顶点缓冲的 UV 布局统计。

    python tools/diag_uv_now.py [数量]
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from core import loader  # noqa: E402
from core import mesh as meshlib  # noqa: E402

CATALOG = r"G:\xmcl-fetch\work\mesh_catalog.json"

RAW = []          # 每次 _parse_blob 的记录


def patch_parse():
    orig = meshlib._parse_blob

    def wrapped(buf, blob_start, blob_end, pos_off):
        blob = orig(buf, blob_start, blob_end, pos_off)
        uv = blob.get("uvs")
        if uv is not None:
            n = blob["num_vertices"]
            tc = blob["num_texcoords"]
            off, cnt, size = uv
            RAW.append(dict(n=n, tc=tc, cnt=cnt, size=size,
                            ntc=n * tc, odd=(n + n % 2) * tc,
                            flat=blob["uvs"].size))
        return blob

    meshlib._parse_blob = wrapped


def stats(lod):
    uv = getattr(lod, "uvs", None)
    if uv is None:
        return "uv=None"
    return (f"uv{tuple(uv.shape)} u=[{uv[:,0].min():.3f},{uv[:,0].max():.3f}] "
            f"v=[{uv[:,1].min():.3f},{uv[:,1].max():.3f}] ch={getattr(lod,'uv_channels','?')} "
            f"v={lod.positions.shape[0]} tri={lod.triangle_count}")


def pick(n=6):
    cat = json.load(open(CATALOG, encoding="utf-8"))
    meshes = [k for k, v in cat.items() if v in ("StaticMesh", "SkeletalMesh")]
    sm = [k for k in meshes if "/Models/" in k and "/SM_" in k]
    sk = [k for k in meshes if cat[k] == "SkeletalMesh" and "/Models/" in k]
    out = []
    for group in (sm, sk):
        step = max(1, len(group) // max(1, n // 2))
        out += group[::step][: max(1, n // 2)]
    return out[:n]


def main(argv):
    patch_parse()
    vps = argv[1:] or pick(6)
    for vp in vps:
        print("\n===", vp)
        RAW.clear()
        os.environ["VERTEXVIEWER_NO_UEFORMAT"] = "1"
        loader._MESH_CACHE.clear()
        m1 = loader.load_mesh(vp)
        raws = list(RAW)
        os.environ.pop("VERTEXVIEWER_NO_UEFORMAT", None)
        loader._MESH_CACHE.clear()
        m2 = loader.load_mesh(vp)
        if not m1 or not m2:
            print("  load failed", bool(m1), bool(m2))
            continue
        for r in raws:
            flags = []
            if r["cnt"] == r["ntc"]:
                flags.append("cnt=n*tc")
            elif r["cnt"] == r["odd"]:
                flags.append("cnt=(n+n%2)*tc")
            else:
                flags.append("cnt=??")
            print(f"  raw n={r['n']} tc={r['tc']} uv_cnt={r['cnt']} uv_size={r['size']} "
                  f"-> {' '.join(flags)}  flat={r['flat']}")
        a, b = m1.lods[0], m2.lods[0]
        print("  mem:", stats(a))
        print("  uef:", stats(b))
        ua, ub = a.uvs, b.uvs
        if ua is None or ub is None:
            print("  !! uv missing")
            continue
        if ua.shape != ub.shape:
            print(f"  !! shape {ua.shape} vs {ub.shape}")
            continue
        d = np.abs(ua - ub).max()
        bad = int((np.abs(ua - ub) > 1e-6).any(axis=1).sum())
        print(f"  roundtrip max|dUV|={d:.6g}  差异顶点={bad}/{ua.shape[0]}")


if __name__ == "__main__":
    main(sys.argv)
