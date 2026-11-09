"""看 core.mesh._scan_lod_sections 对骨骼网格到底扫出了什么。

用法： python tools/_sec_probe.py "<vpath 子串>"
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import loader  # noqa: E402
from core import mesh as M  # noqa: E402
from core import uasset as ua  # noqa: E402

needle = sys.argv[1] if len(sys.argv) > 1 else "M_Kai_002_Body_3P_HD"
idx = loader.index()
vpath = [k for k in idx if needle.lower() in k.lower() and k.endswith(".uasset")][0]
print("资产:", vpath)

ua_bytes = loader.read_entry(vpath)
ue_bytes = loader.read_entry(vpath[:-len(".uasset")] + ".uexp") or b""
pkg = ua.Package(ua_bytes, ue_bytes, None, path=vpath)
exp = pkg.exports[0]
buf = pkg.virtual()
start, end = exp.serial_offset, min(exp.serial_offset + exp.serial_size, len(buf))

heads = M._find_position_headers(buf, start, end)
print("headers:", heads[:4])
blobs = []
for i, (pos_off, _n) in enumerate(heads[:3]):
    b_end = heads[i + 1][0] if i + 1 < len(heads) else end
    try:
        blobs.append(M._parse_blob(buf, max(pos_off - 2, start), b_end, pos_off))
    except Exception as exc:                                   # noqa: BLE001
        print("  blob fail", i, exc)
print("blobs:", [(b["num_vertices"], b.get("index_offset")) for b in blobs])

secs = M._scan_lod_sections(buf, start, end, [b["num_vertices"] for b in blobs])
print("section_lods:", len(secs) if secs else 0)
entries = secs or []
print("type:", type(entries[0]))
for item in entries[:6]:
    print("  entry:", type(item), getattr(item, "__dict__", item) if not isinstance(item, tuple) else item[:2])
