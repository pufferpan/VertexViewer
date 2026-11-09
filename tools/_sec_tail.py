"""看骨骼网格 LOD0 索引缓冲「紧后面」的字节（section 表通常就在这儿）。

用法： python tools/_sec_tail.py "<vpath 子串>"
"""
from __future__ import annotations

import os
import struct
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
pos_off, nverts = heads[0]
blob_end = heads[1][0]
blob = M._parse_blob(buf, max(pos_off - 2, start), blob_end, pos_off)
print("num_vertices:", blob["num_vertices"], "index_offset:", blob["index_offset"])
found = M._resolve_indices(blob["raw"], max(blob.get("blob_start", 0), blob["index_offset"] - 64),
                           blob["blob_end"], start, end, blob["num_vertices"], blob["positions"])
if found is None:
    found = M._find_index_run(blob["raw"], blob["index_offset"], blob["blob_end"],
                              blob["num_vertices"], blob["positions"])
print("indices:", None if found is None else (found.size, int(found.max())))
if found is None:
    raise SystemExit("no indices")

tail = max(start, pos_off - 400)
print("region before position buffer:", tail, "pos_off:", pos_off)
chunk = bytes(buf[tail:tail + 240])
for i in range(0, len(chunk), 16):
    row = chunk[i:i + 16]
    hexs = " ".join(f"{b:02x}" for b in row)
    u32 = " ".join(f"{struct.unpack('<I', chunk[i + j:i + j + 4])[0]:>10}"
                   for j in range(0, min(16, len(row) - 3), 4))
    print(f"{tail + i:>9}  {hexs:<48}  {u32}")
