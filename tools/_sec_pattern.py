"""按「材质号递增」模式找 section 表：section 一般按 MaterialIndex 0,1,2… 排列。

用法： python tools/_sec_pattern.py "<vpath 子串>" [材质数]
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from core import loader  # noqa: E402
from core import uasset as ua  # noqa: E402

needle = sys.argv[1] if len(sys.argv) > 1 else "M_Kai_002_Body_3P_HD"
nmats = int(sys.argv[2]) if len(sys.argv) > 2 else 8

idx = loader.index()
vpath = [k for k in idx if needle.lower() in k.lower() and k.endswith(".uasset")][0]
print("资产:", vpath)
pkg = ua.Package(loader.read_entry(vpath), loader.read_entry(vpath[:-7] + ".uexp") or b"",
                 None, path=vpath)
exp = pkg.exports[0]
buf = pkg.virtual()
start = exp.serial_offset
end = min(exp.serial_offset + exp.serial_size, len(buf))
span = bytes(buf[start:end])
arr = np.frombuffer(span, dtype="<u4")
print("u32 个数:", arr.size)

# 找 arr[i]==0 且后面按递增出现 1..nmats-1 的位置（间隔 16..256 字节）
hits = []
zeros = np.flatnonzero(arr[: arr.size - 4] == 0)
for z in zeros[:200000]:
    pos = int(z)
    cur = pos
    ok = True
    last = 0
    for m in range(1, nmats):
        lo = cur + 4
        hi = min(arr.size, cur + 64)
        seg = arr[lo:hi]
        nz = np.flatnonzero(seg == m)
        if nz.size == 0:
            ok = False
            break
        cur = lo + int(nz[0])
        last = m
    if ok:
        hits.append((start + pos * 4, last))

print("候选:", len(hits))
for off, last in hits[:15]:
    print(f"  off={off} 到材质 {last}")
    base = off - 8
    chunk = bytes(buf[base:base + 200])
    for i in range(0, len(chunk), 16):
        row = chunk[i:i + 16]
        print(f"   {base + i:>9}  " + " ".join(f"{b:02x}" for b in row))
    print()
