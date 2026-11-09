"""在骨骼网格里找「索引头 + u16 索引数组」：count u32 紧跟一段 u16，值都 < 顶点数。

用法： python tools/_idx_lead.py "<vpath 子串>"
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from core import loader  # noqa: E402
from core import mesh as M  # noqa: E402
from core import uasset as ua  # noqa: E402

needle = sys.argv[1] if len(sys.argv) > 1 else "M_BHD_Grimes_A_019_Body_UI_HD"
vpath = [k for k in loader.index() if needle.lower() in k.lower() and k.endswith(".uasset")][0]
pkg = ua.Package(loader.read_entry(vpath), loader.read_entry(vpath[:-7] + ".uexp") or b"",
                 None, path=vpath)
exp = pkg.exports[0]
buf = pkg.virtual()
start, end = exp.serial_offset, min(exp.serial_offset + exp.serial_size, len(buf))
heads = M._find_position_headers(buf, start, end)
print("资产:", vpath)
print("heads:", heads[:4])
pos_off, nv = heads[0]
print("num_vertices:", nv)

mv = memoryview(buf)
best = []
for off in range(start, end - 64, 2):
    (count,) = struct.unpack_from("<I", mv, off)
    if not (3000 <= count <= 2_000_000):
        continue
    if off + 4 + count * 2 > end:
        continue
    head = np.frombuffer(buf, dtype="<u2", count=min(48, count), offset=off + 4)
    if head.max() >= nv or head.min() == head.max():
        continue
    # 抽样检查尾部也合法
    tail_off = off + 4 + (count - 24) * 2
    tail = np.frombuffer(buf, dtype="<u2", count=24, offset=tail_off)
    if tail.max() >= nv:
        continue
    best.append((count, off + 4, off))

best.sort(key=lambda t: -t[0])
print("候选:", len(best))
for count, data_off, hdr_off in best[:8]:
    print(f"  count={count} tris={count // 3} data@{data_off} header@{hdr_off}")
