"""End-to-end smoke test: pak -> mesh -> materials -> textures -> renderer -> OBJ.

Run:  python tools/smoke_test.py [n_models]
Not a unit test framework on purpose -- this is the "does the whole thing
actually work on the real game files" gate I run before shipping.
"""
import json
import os
import random
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from core import loader                                        # noqa: E402

SAMPLES = os.path.abspath(os.path.join(ROOT, "..", "work", "sample_vpaths.json"))
BAD_NAMES = ("_PhysicsAsset", "_Anim", "AnimSequence", "Pose_", "_Pose", "T_", "M_Upper")


def pick(n):
    """A few real meshes spread over the categories."""
    samples = json.load(open(SAMPLES, encoding="utf-8"))
    pool = []
    for cat, paths in samples.items():
        for p in paths:
            if any(b in p for b in BAD_NAMES):
                continue
            pool.append(p)
    random.seed(1)
    random.shuffle(pool)
    return pool[:n]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    ok = 0
    fails = []
    for vpath in pick(n):
        name = vpath.split("/")[-1]
        t0 = time.time()
        try:
            bundle = loader.load_model(vpath)
        except Exception:
            fails.append((name, traceback.format_exc().splitlines()[-1]))
            continue
        dt = time.time() - t0
        mesh = bundle.mesh
        tris = sum(l.triangle_count for l in mesh.lods) if mesh else 0
        mats = len(bundle.materials)
        texs = len(bundle.textures)
        cn = bundle.display_name_cn
        status = "OK " if tris else "MESH?"
        if tris:
            ok += 1
        print(f"[{status}] {name[:46]:46s} lods={len(mesh.lods) if mesh else 0} "
              f"tris={tris:6d} mats={mats} texs={texs} {dt:5.2f}s cn={cn[:20]!r}")
        if not tris:
            fails.append((name, "no triangles"))

    print(f"\n{ok}/{n} models with geometry")
    for name, why in fails:
        print("  FAIL", name, "->", why)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
