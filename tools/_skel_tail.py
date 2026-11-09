"""看骨骼网格索引缓冲后面到底是什么（section 表应该就在这附近）。

用法： python tools/_skel_tail.py "<vpath 子串>"
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

needle = sys.argv[1] if len(sys.argv) > 1 else "M_Kai_002_Body_3P_HD"
idx = loader.index()
hits = [k for k in idx if needle.lower() in k.lower() and k.endswith(".uasset")]
vpath = hits[0]
print("资产:", vpath)

ua_bytes = loader.read_entry(vpath)
ue_bytes = loader.read_entry(vpath[:-len(".uasset")] + ".uexp") or b""
pkg = ua.Package(ua_bytes, ue_bytes, None, path=vpath)
exp = pkg.exports[0]
buf = pkg.virtual()
start, end = exp.serial_offset, min(exp.serial_offset + exp.serial_size, len(buf))

heads = M._find_position_headers(buf, start, end)
print("position headers:", heads[:6])
num_vertices = heads[0][1] if heads else 0
print("num_vertices:", num_vertices)

# 找最长的「连续 uint16 且都 < num_vertices」的段 = 索引缓冲
data = np.frombuffer(buf[start:end], dtype="<u2")
mask = data < max(num_vertices, 1)
best_len, best_at = 0, -1
run_start = None
for i, ok in enumerate(mask):
    if ok:
        if run_start is None:
            run_start = i
        ln = i - run_start + 1
        if ln > best_len:
            best_len, best_at = ln, run_start
    else:
        run_start = None
idx_off = start + best_at * 2
idx_len = best_len * 2
print(f"index run: off={idx_off} bytes={idx_len} tris={idx_len // 6}")

tail = idx_off + idx_len
print("tail offset:", tail, "remaining:", end - tail)

# 打印索引缓冲尾部之后 400 字节
chunk = bytes(buf[tail:tail + 400])
for i in range(0, len(chunk), 16):
    row = chunk[i:i + 16]
    hexs = " ".join(f"{b:02x}" for b in row)
    ints = " ".join(f"{struct.unpack('<i', chunk[i + j:i + j + 4])[0]:>10}"
                    for j in range(0, min(16, len(row) - 3), 4))
    print(f"{tail + i:>9}  {hexs:<48}  {ints}")
