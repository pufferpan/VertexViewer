"""结构式扫描 FSkelMeshRenderSection 表（多种字段布局都试一遍）。

用法： python tools/_skel_sec4.py "<vpath 子串>" [总三角数] [材质数]
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
start, end = exp.serial_offset, min(exp.serial_offset + exp.serial_size, len(buf))
mv = memoryview(buf)

# 每个布局 = 每节「变长头之后的固定段」解析方式
LAYOUTS = [
    ("A: mat,base,tri,flags1", 1),
    ("B: mat,base,tri,flags1,bvert4", 4),
    ("C: mat,base,tri,flags2", 2),
    ("D: mat,base,tri,flags1,cloth4", 4),
]


def walk(off: int, tail_extra: int):
    if off + 4 > end:
        return None
    (count,) = struct.unpack_from("<i", mv, off)
    if not (1 <= count <= 200):
        return None
    pos = off + 4
    secs = []
    for _ in range(count):
        if pos + 4 > end:
            return None
        (bones,) = struct.unpack_from("<i", mv, pos)
        if not (0 <= bones <= 1024):
            return None
        pos += 4 + bones * 2
        if pos + 12 + tail_extra > end:
            return None
        mat, base, tris = struct.unpack_from("<III", mv, pos)
        if mat >= num_mats or tris == 0 or tris > 300000:
            return None
        secs.append((mat, base, tris))
        pos += 12 + tail_extra
    return secs, pos


hits = []
for off in range(start, end - 16, 4):
    (count,) = struct.unpack_from("<i", mv, off)
    if not (1 <= count <= 200):
        continue
    for name, extra in LAYOUTS:
        got = walk(off, extra)
        if not got:
            continue
        secs, stop = got
        tot = sum(s[2] for s in secs)
        if abs(tot - total_tris) <= max(32, total_tris // 500):
            hits.append((off, name, secs, stop, tot))

print("候选:", len(hits))
for off, name, secs, stop, tot in hits[:10]:
    print(f"  off={off} {name} n={len(secs)} tris={tot} stop={stop}")
    for mat, base, tris in secs[:16]:
        print(f"     mat={mat:<3} base={base:<8} tris={tris}")
