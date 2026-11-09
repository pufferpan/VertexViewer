"""Dump every index-container candidate of one mesh asset (debug helper)."""
from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, r"G:/xmcl-fetch/vertexviewer")

from core import mesh as M
from core import uasset as U
from core.loader import load_blobs


def main(vpath: str) -> int:
    blobs = load_blobs(vpath)
    ua = blobs.get("uasset") or b""
    ue = blobs.get("uexp") or b""
    ub = blobs.get("ubulk")
    pkg = U.Package(ua, ue or None, ub, vpath)
    exports = [e for e in pkg.exports if pkg.export_class(e).endswith("Mesh")]
    print("exports:", [(e.name, pkg.export_class(e), e.serial_offset, e.serial_size)
                       for e in exports])
    export = exports[0]
    raw = pkg.virtual()
    r = pkg.export_reader(export)
    props = {}
    try:
        props = pkg.read_properties(r)
    except Exception as exc:  # noqa: BLE001 - same fallback as the loader
        print("properties failed:", exc)
        r.pos = export.serial_offset
    start = export.serial_offset
    end = r.end
    if ub:
        heads = M._find_position_headers(ub, 0, len(ub))
        print("ubulk heads:", heads)
        for i, (poff, nv) in enumerate(heads):
            bstart = max(0, poff - 2)
            bend = heads[i + 1][0] if i + 1 < len(heads) else len(ub)
            blob = M._parse_blob(ub, bstart, bend, poff)
            if blob is None:
                print(f"blob{i}: parse failed")
                continue
            _dump(ub, blob, bstart, bend, f"blob{i}")
    else:
        heads = M._find_position_headers(raw, start, end)
        print("uexp heads:", heads)
        for i, (poff, nv) in enumerate(heads):
            bstart = max(start, poff - 2)
            bend = heads[i + 1][0] if i + 1 < len(heads) else end
            blob = M._parse_blob(raw, bstart, bend, poff)
            if blob is None:
                print(f"blob{i}: parse failed")
                continue
            _dump(raw, blob, start, end, f"blob{i}")
    return 0


def _dump(raw, blob, chunk_start, chunk_end, tag):
    nv = blob["num_vertices"]
    pos = blob["positions"]
    print(f"\n== {tag} nv={nv} pos={blob['index_offset'] - nv * 12} "
          f"uv_end={blob['index_offset']} blob_end={blob['blob_end']}")
    tail = M._locate_index_buffer(raw, max(blob["index_offset"] - 64, 0),
                                  blob["blob_end"], nv, pos)
    print("  tail container:", tail)
    if tail:
        idx = M._indices_from_container(raw, tail, nv)
        if idx is not None:
            print("    tail metrics:", M._index_quality(idx, pos),
                  "ref=%.3f" % (np.unique(idx).size / nv))
    # every container in the whole blob, decoded and scored
    rows = []
    for shift in range(4):
        base = shift
        n = (len(raw) - base) // 4 - 1
        if n <= 0:
            continue
        arr = np.frombuffer(raw, dtype="<i4", count=n, offset=base)
        for elem_size in (2, 4):
            hits = np.nonzero(arr == elem_size)[0]
            hits = hits[hits + 1 < n]
            if hits.size == 0:
                continue
            counts = arr[hits + 1].astype(np.int64)
            offs = base + hits.astype(np.int64) * 4 + 8
            ok = ((counts >= 300) & (counts % 3 == 0)
                  & (offs + counts * elem_size <= len(raw)))
            dtype = "<u2" if elem_size == 2 else "<u4"
            for k in np.nonzero(ok)[0]:
                off, count = int(offs[k]), int(counts[k])
                arr2 = np.frombuffer(raw, dtype=dtype, count=count, offset=off)
                if int(arr2.max()) >= nv:
                    continue
                deg, spread = M._index_quality(arr2, pos)
                ref = np.unique(arr2).size / nv
                rows.append((off, elem_size, count, deg, spread, ref))
    rows.sort(key=lambda t: (-t[5], t[3]))
    for off, elem_size, count, deg, spread, ref in rows[:8]:
        print(f"  cand off=0x{off:x} elem={elem_size} n={count} tri={count // 3} "
              f"zero={deg * 100:.1f}% ref={ref * 100:.1f}% max/med={spread:.1f}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
