"""Dump the buffer chain of each LOD of one asset.

Usage:  python tools/probe_chain.py <vpath>
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from core import loader
from core import mesh as meshlib
from core import uasset as ualib


def headers_in(buf, start, end, nv):
    """All (offset, elem_size, count) with count == nv or nv*tc."""
    out = []
    for off in range(start, min(end, start + 4096) - 8):
        for size in (1, 2, 4, 8, 12, 16):
            count = struct.unpack_from("<i", buf, off + 4)[0]
            esz = struct.unpack_from("<i", buf, off)[0]
            if esz == size and (count == nv or count == nv * 2 or count == nv * 3
                                or count == nv * 4):
                out.append((off, size, count))
                break
    return out


def main(vpath):
    blobs = loader.load_blobs(vpath)
    pkg = ualib.Package(blobs["uasset"], blobs.get("uexp"), blobs.get("ubulk"), vpath)
    cls = "SkeletalMesh" if pkg.find_exports("SkeletalMesh") else "StaticMesh"
    export = pkg.find_exports(cls)[0]
    r = pkg.export_reader(export)
    try:
        pkg.read_properties(r)
    except Exception:
        r.pos = export.serial_offset
    buf = pkg.virtual()
    end = export.serial_offset + export.serial_size
    print("%s  class=%s export=%s [0x%x,0x%x) props_end=0x%x"
          % (vpath.rsplit("/", 1)[-1], cls, export.name, export.serial_offset, end, r.pos))
    heads = meshlib._find_position_headers(buf, r.pos, end)
    print("  position headers:", [(h, n) for h, n in heads])
    for i, (pos_off, nv) in enumerate(heads):
        blob_start = pos_off - 2
        blob_end = heads[i + 1][0] - 2 if i + 1 < len(heads) else end
        vbinfo = meshlib._parse_vertex_buffer(buf, pos_off + 16, blob_end, nv)
        tc, nv2, tan, uv = vbinfo
        uv_end = uv[0] + uv[1] * uv[2]
        print("  LOD%d nv=%d blob=[0x%x,0x%x) tc=%s tan=(0x%x,%d,%d) "
              "uv=(0x%x,%d,%d) uv_end=0x%x tail=%d"
              % (i, nv, blob_start, blob_end, tc, tan[0], tan[1], tan[2],
                 uv[0], uv[1], uv[2], uv_end, blob_end - uv_end))
        hs = headers_in(buf, uv_end, blob_end, nv)
        for off, size, count in hs[:14]:
            print("      hdr @0x%-8x (%d, %d)" % (off, size, count))


if __name__ == "__main__":
    for p in sys.argv[1:]:
        main(p)
        print()
