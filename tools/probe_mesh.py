"""Static/skeletal mesh acceptance probe.

Picks real models out of the pak index across many categories, runs
``core.mesh`` on each of them and prints a table:

    category | asset | LODs | verts | tris | sections | material | bounds

Usage::

    python tools/probe_mesh.py                 # default sample set
    python tools/probe_mesh.py --limit 20      # more per category
    python tools/probe_mesh.py --obj           # write an OBJ for the first hit
    python tools/probe_mesh.py --vpath <v>     # inspect a single asset off-tree
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from core import loader, mesh  # noqa: E402

WORK = r"G:/xmcl-fetch/work"

# (label, substring of the vpath below Content/) -- first match wins
CATEGORIES = [
    ("weapon-part", "Models/Weapons/"),
    ("vehicle", "Models/Vehicles/"),
    ("scene-object", "Models/SceneObjects/"),
    ("prop", "Environment/Props/"),
    ("structure", "Environment/Structures/"),
    ("biome-nature", "Environment/Biome/"),
    ("destructible", "Battlefield/Destructible/"),
    ("effect-mesh", "Effects/Common/"),
    ("ui-mesh", "UI/UIVX/"),
    ("gameplay", "Environment/Gameplay/"),
    ("buildmap", "Maps/BuildMaps_HD/"),
    ("miniworld", "Environment/MiniWorld/"),
    ("landmark", "Environment/Landmark/"),
    ("weapon-prop", "SafeHouseP/"),
]


def _candidates():
    idx = loader.index()
    picked = []
    seen = set()
    for label, needle in CATEGORIES:
        for vpath in sorted(idx):
            if needle not in vpath or not vpath.endswith(".uasset"):
                continue
            base = vpath.rsplit("/", 1)[-1]
            if not base.startswith(("SM_", "SKM_")):
                continue
            if vpath in seen:
                continue
            if vpath.replace(".uasset", ".ubulk") not in idx:
                continue
            seen.add(vpath)
            picked.append((label, vpath))
            break
    return picked


def _fmt(v):
    return "%.3f" % v


def _describe(m, label, vpath):
    short = vpath.split("/Content/", 1)[-1]
    print("=" * 100)
    print("[%s] %s" % (label, short))
    print("    mesh=%r lods=%d format=%s" % (m.name, len(m.lods), m.source_format))
    print("    bounds center=(%s, %s, %s) extent=(%s, %s, %s)" % tuple(
        [_fmt(x) for x in m.bounds_center] + [_fmt(x) for x in m.bounds_extent]))
    for i, lod in enumerate(m.lods):
        uv = "-" if lod.uvs is None else str(lod.uvs.shape)
        nm = "-" if lod.normals is None else str(lod.normals.shape)
        print("    LOD%d v=%d tri=%d sec=%d uv=%s n=%s" % (
            i, lod.vertex_count, lod.triangle_count, len(lod.sections), uv, nm))
        if lod.positions.size:
            lo = lod.positions.min(axis=0)
            hi = lod.positions.max(axis=0)
            print("         pos range x[%s..%s] y[%s..%s] z[%s..%s]" % (
                _fmt(lo[0]), _fmt(hi[0]), _fmt(lo[1]), _fmt(hi[1]),
                _fmt(lo[2]), _fmt(hi[2])))
        if lod.indices.size:
            idxmax = int(lod.indices.max())
            bad = idxmax >= lod.vertex_count
            print("         index max=%d %s" % (idxmax, "OUT OF RANGE" if bad else "ok"))
        for s in lod.sections:
            print("         section mat=%s tri=%d first_index=%d" % (
                s.material_path, s.num_triangles, s.first_index))


def write_obj(m, path, lod_index=0):
    """Minimal OBJ writer (development aid only)."""
    lod = m.lods[lod_index]
    lines = ["# %s (LOD%d) verts=%d tris=%d" % (m.name, lod_index,
                                                lod.vertex_count, lod.triangle_count)]
    for p in lod.positions:
        lines.append("v %.6f %.6f %.6f" % (p[0], p[1], p[2]))
    if lod.uvs is not None:
        for uv in lod.uvs:
            lines.append("vt %.6f %.6f" % (uv[0], uv[1]))
    if lod.normals is not None:
        for n in lod.normals:
            lines.append("vn %.6f %.6f %.6f" % (n[0], n[1], n[2]))
    has_vt = lod.uvs is not None
    has_vn = lod.normals is not None
    tris = lod.indices.reshape(-1, 3)
    offset = 0
    for si, sec in enumerate(lod.sections):
        lines.append("g section_%d" % si)
        n = sec.num_triangles if sec.num_triangles else len(tris) - offset
        for t in tris[offset:offset + n]:
            a, b, c = int(t[0]) + 1, int(t[1]) + 1, int(t[2]) + 1
            if has_vt and has_vn:
                lines.append("f %d/%d/%d %d/%d/%d %d/%d/%d" % (
                    a, a, a, b, b, b, c, c, c))
            elif has_vn:
                lines.append("f %d//%d %d//%d %d//%d" % (a, a, b, b, c, c))
            else:
                lines.append("f %d %d %d" % (a, b, c))
        offset += n
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return len(lines)


def _reason(exc):
    text = "%s: %s" % (type(exc).__name__, exc)
    low = text.lower()
    if "ubulk" in low or "no lod buffers" in low:
        return "no ubulk geometry"
    if "no staticmesh" in low or "no staticmesh/skeletalmesh" in low:
        return "not a mesh export"
    if "no fstaticmeshsection" in low:
        return "no section records"
    if "beyond payload" in low or "unexpected end" in low:
        return "truncated / stream mismatch"
    return type(exc).__name__


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--vpath", default=None)
    ap.add_argument("--obj", action="store_true", help="write work/probe_mesh_X.obj")
    ap.add_argument("--traceback", action="store_true")
    args = ap.parse_args(argv)

    if args.vpath:
        samples = [("custom", args.vpath)]
    else:
        samples = _candidates()

    ok = 0
    reasons = {}
    first_ok = None
    for label, vpath in samples:
        try:
            blobs = loader.load_blobs(vpath)
            m = mesh.load_mesh_from_blobs(vpath, blobs)
            if not m.lods or m.lods[0].vertex_count == 0:
                raise mesh.MeshError("empty geometry")
            _describe(m, label, vpath)
            ok += 1
            if first_ok is None:
                first_ok = m
        except Exception as exc:                                   # noqa: BLE001
            reason = _reason(exc)
            reasons[reason] = reasons.get(reason, 0) + 1
            print("=" * 100)
            print("[%s] %s" % (label, vpath.split("/Content/", 1)[-1]))
            print("    FAILED %s" % reason)
            if args.traceback:
                traceback.print_exc()

    print("=" * 100)
    print("summary: %d/%d ok" % (ok, len(samples)))
    for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print("   failed %2d x %s" % (n, reason))

    if args.obj and first_ok is not None:
        out = os.path.join(WORK, "probe_mesh_%s.obj" % first_ok.name)
        write_obj(first_ok, out)
        lod = first_ok.lods[0]
        print("wrote %s (v=%d tri=%d) %d lines" % (
            out, lod.vertex_count, lod.triangle_count,
            sum(1 for _ in open(out, encoding="utf-8"))))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
