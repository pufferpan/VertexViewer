"""再扫一遍 FSkelMeshRenderSection：这次加上「空数组 + i16」这些尾部字段。

用法： python tools/_skel_sec5.py "<vpath 子串>" [总三角数] [材质数]
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
num_mats = int(sys.argv[3]) if len(sys.argv) > 3 else 8

idx = loader.index()
vpath = [k for k in idx if needle.lower() in k.lower() and k.endswith(".uasset")][0]
pkg = ua.Package(loader.read_entry(vpath), loader.read_entry(vpath[:-7] + ".uexp") or b"",
                 None, path=vpath)
exp = pkg.exports[0]
buf = pkg.virtual()
start, end = min(exp.serial_offset, len(buf)), min(exp.serial_offset + exp.serial_size, len(buf))
mv = memoryview(buf)
unpack_i = struct.Struct("<i").unpack_from

TAILS = (0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24)


def walk(off: int, extra: int):
    (count,) = unpack_i(mv, off)
    if not (1 <= count <= 64):
        return None
    pos = off + 4
    secs = []
    for _ in range(count):
        if pos + 4 > end:
            return None
        (bones,) = unpack_i(mv, pos)
        if not (0 <= bones <= 1024):
            return None
        pos += 4 + bones * 2
        if pos + 12 + extra > end:
            return None
        mat, base, tris = struct.unpack_from("<III", mv, pos)
        if mat >= num_mats or tris == 0 or tris > 300000:
            return None
        secs.append((mat, base, tris))
        pos += 12 + extra
    return secs, pos


hits = []
for off in range(start, end - 24, 2):
    (count,) = unpack_i(mv, off)
    if not (1 <= count <= 64):
        continue
    for extra in TAILS:
        got = walk(off, extra)
        if not got:
            continue
        secs, stop = got
        if abs(sum(s[2] for s in secs) - total_tris) <= max(16, total_tris // 2000):
            hits.append((off, extra, secs, stop))

print("候选:", len(hits))
for off, extra, secs, stop in hits[:10]:
    print(f"  off={off} extra={extra} n={len(secs)} tris={sum(s[2] for s in secs)} stop={stop}")
    for mat, base, tris in secs[:16]:
        print(f"     mat={mat:<3} base={base:<9} tris={tris}")
