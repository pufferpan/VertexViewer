"""结构式扫描 FSkelMeshRenderSection 表（每节开头是变长的 BoneMap 数组，定长扫描找不到）。

用法： python tools/_skel_sec2.py "<vpath 子串>" [总三角数] [材质数]
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
print("资产:", vpath)

ua_bytes = loader.read_entry(vpath)
ue_bytes = loader.read_entry(vpath[:-len(".uasset")] + ".uexp") or b""
pkg = ua.Package(ua_bytes, ue_bytes, None, path=vpath)
exp = pkg.exports[0]
buf = pkg.virtual()
start, end = exp.serial_offset, min(exp.serial_offset + exp.serial_size, len(buf))
mv = memoryview(buf)


def parse_table(off: int):
    """按 FSkelMeshRenderSection 结构往下读，返回 (sections, 结束位置) 或 None。"""
    if off + 4 > end:
        return None
    (count,) = struct.unpack_from("<i", mv, off)
    if not (1 <= count <= 24):
        return None
    pos = off + 4
    out = []
    for _ in range(count):
        if pos + 4 > end:
            return None
        (bones,) = struct.unpack_from("<i", mv, pos)
        if not (1 <= bones <= 512):
            return None
        pos += 4 + bones * 2
        if pos + 17 > end:
            return None
        mat, base, tris = struct.unpack_from("<III", mv, pos)
        if mat >= num_mats or tris == 0 or tris > 300000:
            return None
        out.append((mat, base, tris, bytes(mv[pos + 12:pos + 17]).hex(" ")))
        pos += 13
        # 有的版本 flags 后还跟一个 uint32（MaxBoneInfluences / 对齐）
    return out, pos


hits = []
for off in range(start, end - 8, 4):
    got = parse_table(off)
    if not got:
        continue
    secs, stop = got
    total = sum(s[2] for s in secs)
    if abs(total - total_tris) <= max(64, total_tris // 200):
        hits.append((off, secs, stop, total))

print("候选:", len(hits))
for off, secs, stop, total in hits[:8]:
    print(f"  off={off} n={len(secs)} tris={total} stop={stop}")
    for mat, base, tris, flags in secs:
        print(f"     mat={mat:<3} base={base:<8} tris={tris:<7} flags={flags}")
