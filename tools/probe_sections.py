"""扫 uexp 找 FStaticMeshSection 记录（诊断多 section 模型为什么只解析出 1 个）。

用法： python tools/probe_sections.py <资产名片段>
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import loader  # noqa: E402

NEEDLE = sys.argv[1] if len(sys.argv) > 1 else "honeycombsmoke_01_1P"
vp = [k for k in loader.index() if NEEDLE in k and k.endswith(".uasset")]
vp = [k for k in vp if "_Skeleton" not in k and "PhysicsAsset" not in k and "/ABP_" not in k]
if not vp:
    print("no asset")
    sys.exit(1)
path = vp[0]
blobs = loader.load_blobs(path)
uexp = blobs.get("uexp") or b""
mv = memoryview(uexp)
print(path.split("/")[-1], "uexp", len(uexp))

# 已知 LOD0 的三角形数与顶点数
model = loader.load_model(path, lod=0, want_textures=False)
lod = model.mesh.lods[0]
tris = len(lod.indices) // 3
verts = len(lod.positions)
print("tris", tris, "verts", verts, "materials", len(model.materials))

hits = []
for pos in range(0, len(uexp) - 8):
    count = struct.unpack_from("<i", mv, pos)[0]
    if count < 2 or count > 12:
        continue
    base = pos + 4
    if base + count * 20 > len(uexp):
        continue
    total = 0
    first_ok = True
    expect = 0
    maxv = -1
    mat_ok = True
    for i in range(count):
        mat, first, t, minv, maxv_ = struct.unpack_from("<5i", mv, base + i * 20)
        if mat < 0 or mat > 32 or t <= 0 or first != expect or minv < 0 or maxv_ < minv:
            first_ok = False
            break
        expect = first + t * 3
        total += t
        maxv = max(maxv, maxv_)
    if not first_ok:
        continue
    if total == tris and maxv + 1 == verts:
        hits.append((pos, count, total))

print("候选记录：", len(hits))
for pos, count, total in hits[:5]:
    print(f"  @{pos} count={count} tris={total}")
    for i in range(count):
        mat, first, t, minv, maxv_ = struct.unpack_from("<5i", mv, pos + 4 + i * 20)
        name = (model.materials[mat].name if mat < len(model.materials) else f"#{mat}")
        print(f"     mat={mat} ({name}) first={first} tris={t} v[{minv}..{maxv_}]")
