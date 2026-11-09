"""Broad sweep: decode N random Models/ assets and report quality stats."""
from __future__ import annotations

import random
import sys

sys.path.insert(0, r"G:/xmcl-fetch/vertexviewer")

from core import mesh as M
from core import uasset as U
from core.loader import index, load_blobs


def main(count: int = 40) -> int:
    idx = index()
    keys = [k for k in idx if k.endswith(".uasset") and "/Models/" in k]
    random.seed(20251025)
    sample = random.sample(keys, count)
    ok = 0
    fails = {}
    prop_ok = 0
    prop_total = 0
    bad_zero = []
    non_mono = []
    mats_missing = 0
    for path in sample:
        try:
            blobs = load_blobs(path)
            if not blobs.get("uasset"):
                raise M.MeshError("empty uasset")
            pkg = U.Package(blobs["uasset"], blobs.get("uexp"), blobs.get("ubulk"), path)
            exports = [e for e in pkg.exports
                       if pkg.export_class(e) in ("StaticMesh", "SkeletalMesh")]
            if exports:
                prop_total += 1
                r = pkg.export_reader(exports[0])
                try:
                    props = pkg.read_properties(r)
                    if props.get("StaticMaterials"):
                        prop_ok += 1
                except Exception:              # noqa: BLE001
                    pass
            m = M.load_mesh_from_blobs(path, blobs)
        except Exception as exc:               # noqa: BLE001
            key = "%s: %s" % (type(exc).__name__, str(exc)[:70])
            fails[key] = fails.get(key, 0) + 1
            continue
        ok += 1
        lods = m.lods
        if not lods:
            continue
        for i, lod in enumerate(lods):
            deg, _ = M._index_quality(lod.indices, lod.positions)
            if deg > 0.02:
                bad_zero.append((path, i, round(deg * 100, 1)))
                break
        tris = [l.triangle_count for l in lods]
        if tris != sorted(tris, reverse=True):
            non_mono.append((path, tris))
        if not any(s.material_path for l in lods for s in l.sections):
            mats_missing += 1
        for lod in lods:
            ext = lod.positions.max(axis=0) - lod.positions.min(axis=0)
            if not (0.001 < float(ext.min()) < 4000):
                bad_zero.append((path, "bounds", list(map(float, ext))))
                break
    print("sampled      : %d" % len(sample))
    print("decoded ok   : %d (%.0f%%)" % (ok, 100.0 * ok / max(1, len(sample))))
    print("props w/ mats: %d/%d" % (prop_ok, prop_total))
    print("no material  : %d" % mats_missing)
    print("zero>2%% LODs : %d" % len(bad_zero))
    for row in bad_zero[:6]:
        print("   ", row)
    print("non monotonic: %d" % len(non_mono))
    for row in non_mono[:6]:
        print("   ", row[0].rsplit("/", 1)[-1], row[1])
    print("failures     :")
    for key, num in sorted(fails.items(), key=lambda kv: -kv[1]):
        print("   %2d x %s" % (num, key))
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 40))
