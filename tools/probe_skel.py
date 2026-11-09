"""Probe: locate skeletal mesh LOD render data and its index buffer.

Run:  python tools/probe_skel.py [--sample 6] [--vpath <path> ...]

For every SkeletalMesh export it finds the inline position buffers
(``(12, n, 12, n)`` headers) and then hunts for the index list, reporting
where it sits relative to the vertex data.
"""
from __future__ import annotations

import argparse
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import mesh, uasset  # noqa: E402


def position_headers(buf, start, end):
    mv = memoryview(buf)
    out = []
    pat = b"\x0c\x00\x00\x00"
    for i in range(start, max(start, end - 16)):
        if buf[i:i + 4] != pat:
            continue
        n = struct.unpack_from("<i", mv, i + 4)[0]
        n2 = struct.unpack_from("<i", mv, i + 12)[0]
        if n == n2 and 32 <= n <= 4000000 and i + 16 + n * 12 <= end:
            out.append((i, n))
    return out


def index_runs(buf, num_vertices, min_run=300):
    runs = []
    for align in (0, 1):
        arr = np.frombuffer(buf, dtype="<u2", count=(len(buf) - align) // 2, offset=align)
        v = (arr < num_vertices).astype(np.int8)
        d = np.diff(np.concatenate(([0], v, [0])))
        s = np.nonzero(d == 1)[0]
        e = np.nonzero(d == -1)[0]
        for a, b in zip(s, e):
            if b - a >= min_run:
                runs.append((int(b - a), align + int(a) * 2))
    runs.sort(reverse=True)
    return runs


def probe(vpath, verbose=False):
    blobs = {}
    try:
        from core import loader
        blobs = loader.load_blobs(vpath)
    except Exception as exc:  # noqa: BLE001
        return f"{vpath}: load failed {exc}"
    pkg = uasset.Package(blobs.get("uasset", b""), blobs.get("uexp", b""), blobs.get("ubulk"), vpath)
    exports = pkg.find_exports("SkeletalMesh")
    if not exports:
        return f"{vpath}: no SkeletalMesh export"
    buf = pkg.virtual()
    lines = [f"{vpath.split('/')[-1]}: exports={len(pkg.exports)} uasset={len(blobs.get('uasset', b''))} "
             f"uexp={len(blobs.get('uexp', b''))} ubulk={len(blobs.get('ubulk') or b'')}"]
    for exp in exports:
        end = min(exp.serial_offset + exp.serial_size, len(buf))
        heads = position_headers(buf, exp.serial_offset, end)
        lines.append(f"  export {exp.name} off={exp.serial_offset} size={exp.serial_size} pos_headers={[(hex(o), n) for o, n in heads][:8]}")
        for off, n in heads[:1]:
            P = np.frombuffer(buf, dtype="<f4", count=n * 3, offset=off + 16).reshape(n, 3)
            lines.append(f"    LOD0 vertices={n} lo={np.round(P.min(0), 1)} hi={np.round(P.max(0), 1)}")
            runs = index_runs(buf, n)[:3]
            for length, o in runs:
                need = (length // 3) * 3
                idx = np.frombuffer(buf, dtype="<u2", count=need, offset=o).astype(np.uint32)
                deg, spread = mesh._index_quality(idx, P.astype(np.float64))
                lines.append(f"    run {hex(o)} len={length} tri={need // 3} degenerate={deg:.4f} spread={spread:.1f}")
            if not runs:
                lines.append("    no u16 index run found")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=6)
    ap.add_argument("--vpath", action="append", default=[])
    args = ap.parse_args()
    paths = list(args.vpath)
    if not paths:
        from core import loader
        index = loader.index()
        pool = [k for k in index if "/Content/Models/" in k and k.endswith(".uasset") and "_3P" in k]
        step = max(1, len(pool) // args.sample)
        paths = pool[::step][:args.sample]
    for vpath in paths:
        try:
            print(probe(vpath))
        except Exception as exc:  # noqa: BLE001
            print(f"{vpath}: {type(exc).__name__}: {exc}")
    print()


if __name__ == "__main__":
    main()
