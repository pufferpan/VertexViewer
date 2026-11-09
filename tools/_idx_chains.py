"""找多个 FMultisizeIndexContainer（b32 conform + u8 size + i32 count）链，看是不是按材质分段的。"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import loader  # noqa: E402
from core import uasset as ua  # noqa: E402

needle = sys.argv[1] if len(sys.argv) > 1 else "M_Kai_002_Body_3P_HD"
idx = loader.index()
vpath = [k for k in idx if needle.lower() in k.lower() and k.endswith(".uasset")][0]
pkg = ua.Package(loader.read_entry(vpath), loader.read_entry(vpath[:-7] + ".uexp") or b"",
                 None, path=vpath)
exp = pkg.exports[0]
buf = pkg.virtual()
start, end = exp.serial_offset, min(exp.serial_offset + exp.serial_size, len(buf))
mv = memoryview(buf)

cands = []
for off in range(start, end - 12, 2):
    size = mv[off + 1]
    if size not in (2, 4):
        continue
    if mv[off] not in (0, 1):
        continue
    (n,) = struct.unpack_from("<i", mv, off + 2)
    if not (3 <= n <= 4_000_000):
        continue
    stop = off + 6 + n * size
    if stop > end:
        continue
    cands.append((off, size, n, stop))

print("容器候选:", len(cands))
# 找能把相邻容器串起来的链
by_off = {c[0]: c for c in cands}
chains = []
for off, size, n, stop in cands:
    chain = [(off, size, n)]
    cur = stop
    while cur in by_off:
        o2, s2, n2, st2 = by_off[cur]
        if s2 != size:
            break
        chain.append((o2, s2, n2))
        cur = st2
    if len(chain) >= 3:
        chains.append((off, size, chain, sum(c[2] for c in chain)))

chains.sort(key=lambda c: -len(c[2]))
print("链:", len(chains))
for off, size, chain, total in chains[:6]:
    print(f"  start={off} size={size} containers={len(chain)} idx_count={total} tris={total // 3}")
    print("     counts:", [c[2] for c in chain][:12])
