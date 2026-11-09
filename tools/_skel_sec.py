"""找骨骼网格的 FSkelMeshSection 表：在导出体里搜「i32 条数 + N 条记录」且三角数合计对得上。

用法： python tools/_skel_sec.py "<vpath 子串>" [总三角数]
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import loader  # noqa: E402
from core import uasset as ua  # noqa: E402

needle = sys.argv[1] if len(sys.argv) > 1 else "M_Kai_002_Body_3P_HD"
total_tris = int(sys.argv[2]) if len(sys.argv) > 2 else 42251

idx = loader.index()
hits = [k for k in idx if needle.lower() in k.lower() and k.endswith(".uasset")]
if not hits:
    raise SystemExit("找不到资产: " + needle)
vpath = hits[0]
print("资产:", vpath)

ua_bytes = loader.read_entry(vpath)
ue_bytes = loader.read_entry(vpath[:-len(".uasset")] + ".uexp") or b""
pkg = ua.Package(ua_bytes, ue_bytes, None, path=vpath)
exports = [e for e in pkg.exports]
print("exports:", len(exports))
exp = exports[0]
print("serial_offset:", exp.serial_offset,
      "serial_size:", exp.serial_size)

buf = pkg.virtual()
start = exp.serial_offset
end = min(exp.serial_offset + exp.serial_size, len(buf))
print("buffer:", len(buf), "export:", start, end)

mv = memoryview(buf)
STRIDES = (16, 18, 20, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40, 44, 48)
found = []
for off in range(start, end - 8, 4):
    (count,) = struct.unpack_from("<i", mv, off)
    if not (1 <= count <= 24):
        continue
    for stride in STRIDES:
        for tri_off in (8, 12, 16, 20):
            if tri_off + 4 > stride:
                continue
            rec = off + 4
            if rec + count * stride > end:
                continue
            tris, mats, ok = 0, [], True
            for i in range(count):
                base = rec + i * stride
                (mat,) = struct.unpack_from("<H", mv, base)
                (t,) = struct.unpack_from("<I", mv, base + tri_off)
                if mat > 32 or t == 0 or t > 200000:
                    ok = False
                    break
                tris += t
                mats.append(mat)
            if ok and abs(tris - total_tris) <= 400:
                found.append((off, count, stride, tri_off, tuple(mats), tris))

print("候选:", len(found))
for off, count, stride, tri_off, mats, tris in found[:12]:
    print(f"  off={off} count={count} stride={stride} tri_off={tri_off} tris={tris} mats={mats}")
    for i in range(min(count, 12)):
        base = off + 4 + i * stride
        raw = bytes(mv[base:base + stride])
        print("    ", raw.hex(" "))
