"""Print the geometry quality numbers for one or more assets.

Usage:  python tools/probe_quality.py <vpath> [<vpath> ...]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from core import loader
from core import mesh as meshlib


def _metrics(lod):
    pos = lod.positions
    idx = lod.indices.astype(np.int64)
    if lod.vertex_count == 0 or idx.size < 3:
        return 0.0, 0.0, 0.0, 0.0
    tri = pos[idx.reshape(-1, 3)]
    areas = 0.5 * np.linalg.norm(
        np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    degenerate = float((areas <= 1e-12).mean())
    good = areas[areas > 1e-12]
    spread = float(good.max() / np.median(good)) if good.size else 0.0
    referenced = np.unique(idx)
    ref_ratio = float(referenced.size) / float(lod.vertex_count)
    return degenerate, spread, ref_ratio, float(idx.max())


def main(paths):
    for vpath in paths:
        print("=" * 78)
        print(vpath)
        try:
            blobs = loader.load_blobs(vpath)
            m = meshlib.load_mesh_from_blobs(vpath, blobs)
        except Exception as exc:
            print("  FAILED: %s: %s" % (type(exc).__name__, exc))
            continue
        print("  name=%s fmt=%s lods=%d" % (m.name, m.source_format, len(m.lods)))
        for i, lod in enumerate(m.lods):
            deg, spread, ref, mx = _metrics(lod)
            print("  LOD%d v=%-6d tri=%-6d sec=%-2d zero=%.1f%% ref=%.1f%% "
                  "max/med=%.1f idx_max=%d"
                  % (i, lod.vertex_count, lod.triangle_count, len(lod.sections),
                     deg * 100.0, ref * 100.0, spread, mx))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    main(sys.argv[1:])
