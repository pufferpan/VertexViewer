"""Locate skeletal index buffers by scanning the whole export.

Usage:  python tools/probe_skel2.py <vpath>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from core import loader
from core import mesh as meshlib
from core import uasset as ualib


def analyse(vpath):
    blobs = loader.load_blobs(vpath)
    pkg = ualib.Package(blobs["uasset"], blobs.get("uexp"), blobs.get("ubulk"), vpath)
    exports = pkg.find_exports("SkeletalMesh")
    if not exports:
        print("no SkeletalMesh export")
        return
    export = exports[0]
    r = pkg.export_reader(export)
    props = {}
    try:
        props = pkg.read_properties(r)
    except Exception:
        r.pos = export.serial_offset
    buf = pkg.virtual()
    heads = meshlib._find_position_headers(buf, r.pos, r.end)
    print("export %s size=%d prop_end=0x%x heads=%s"
          % (export.name, export.serial_size, r.pos, heads))
    for i, (pos_off, nv) in enumerate(heads):
        blob_start = pos_off - 2
        blob_end = heads[i + 1][0] - 2 if i + 1 < len(heads) else export.serial_offset + export.serial_size
        blob = meshlib._parse_blob(buf, blob_start, blob_end, pos_off)
        positions = meshlib.ue_to_gl(blob["positions"].astype(np.float32))
        cands = meshlib._index_candidates(buf, blob_start, blob_end, nv)
        scored = []
        for off, size, count in cands:
            arr = np.frombuffer(buf, dtype=("<u2" if size == 2 else "<u4"),
                                count=min(count, 3000), offset=off)
            deg, spread = meshlib._index_quality(arr, positions)
            ref = np.unique(arr).size / float(nv)
            scored.append((deg, -count, spread, ref, off, size, count))
        scored.sort()
        print("  LOD%d nv=%d blob=[0x%x,0x%x) cands=%d"
              % (i, nv, blob_start, blob_end, len(scored)))
        for deg, negc, spread, ref, off, size, count in scored[:6]:
            print("     off=0x%-8x size=%d count=%-7d tris=%-6d zero=%5.1f%% "
                  "ref=%5.1f%% max/med=%.1f  (blob+0x%x)"
                  % (off, size, count, count // 3, deg * 100, ref * 100, spread,
                     off - blob_start))


if __name__ == "__main__":
    analyse(sys.argv[1])
