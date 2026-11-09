"""诊断：HAAVK 头盔的索引容器选错了？用「边界边比例」挑正确候选。

边界边 = 只被 1 个三角形使用的无向边。一个封闭/半封闭的盔壳，边界边应该很少
（除了看不到的开口）。如果解出来的索引是被截断的子集，边界边比例会非常高，看起来
就是“模型碎掉、缺了一大块”。
"""

from __future__ import annotations

import sys
import numpy as np

sys.path.insert(0, r"G:\xmcl-fetch\vertexviewer")

from core import loader  # noqa: E402


def boundary_and_stats(ind: np.ndarray, nverts: int, positions=None) -> dict:
    tri = ind.reshape(-1, 3).astype(np.int64)
    e = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]], axis=0)
    e.sort(axis=1)
    uniq, counts = np.unique(e, axis=0, return_counts=True)
    boundary = int((counts == 1).sum())
    degenerate = int((tri[:, 0] == tri[:, 1]).sum() + (tri[:, 1] == tri[:, 2]).sum()
                     + (tri[:, 0] == tri[:, 2]).sum())
    out = {
        "tris": int(len(tri)),
        "verts_used": int(len(np.unique(ind))),
        "max_index": int(ind.max()) if ind.size else -1,
        "boundary_edges": boundary,
        "boundary_ratio": boundary / max(1, len(uniq)),
        "degenerate": degenerate / max(1, len(tri)),
    }
    return out


def candidates(buf: bytes, start: int, end: int, nverts: int):
    """把这一段里所有 (elem_size, data_off, count) 自描述候选列出来。"""
    out = []
    n = (end - start) // 4
    arr = np.frombuffer(buf, dtype="<i4", count=n, offset=start)
    for i in range(n - 1):
        es = int(arr[i])
        cnt = int(arr[i + 1])
        if es not in (2, 4) or cnt <= 0 or cnt % 3 or cnt < 300:
            continue
        off = start + (i + 1) * 4
        size = cnt * es
        if off + size > end:
            continue
        dtype = "<u2" if es == 2 else "<u4"
        ind = np.frombuffer(buf, dtype=dtype, count=cnt, offset=off)
        if ind.size and int(ind.max()) >= nverts:
            continue
        out.append((es, off, cnt, ind.copy()))
    return out


def main(path_suffix: str) -> None:
    idx = loader.index()
    vpath = [k for k in idx if k.endswith("/" + path_suffix + ".uasset")][0]
    blobs = loader.load_blobs(vpath)
    print(f"{path_suffix}: blobs " + ", ".join(f"{k}={len(v)}" for k, v in blobs.items()))
    from core import mesh as M

    mesh = M.load_mesh_from_blobs(vpath, blobs)
    lod = mesh.lods[0]
    ind = np.asarray(lod.indices).ravel()
    pos = np.asarray(lod.positions)
    print("chosen:", boundary_and_stats(ind, len(pos)))

    ubulk = blobs.get("ubulk") or b""
    if not ubulk:
        print("no ubulk")
        return
    for start, end, label in _lod_ranges(ubulk, len(pos)):
        cands = candidates(ubulk, start, end, len(pos))
        rows = []
        for es, off, cnt, arr in cands:
            st = boundary_and_stats(arr, len(pos))
            rows.append((st["boundary_ratio"], es, off, cnt, st))
        rows.sort(key=lambda r: r[0])
        print(f"-- {label}: {len(rows)} candidates")
        for br, es, off, cnt, st in rows[:6]:
            print(f"   elem={es} off={off} count={cnt} boundary={br:.3f} "
                  f"deg={st['degenerate']:.3f} used={st['verts_used']}/{len(pos)}")


def _lod_ranges(ubulk: bytes, nverts: int):
    """用 strip/stride/numverts 三个 u32 的开头模式粗定位每个 LOD 块。"""
    ranges = []
    n = (len(ubulk) // 4) - 3
    arr = np.frombuffer(ubulk, dtype="<u4", count=n, offset=0)
    for i in range(n - 3):
        if arr[i + 1] == 12 and 0 < arr[i + 2] < 2_000_000:
            nv = int(arr[i + 2])
            if arr[i + 3] == 12:
                start = i * 4
                ranges.append((start, None, f"block@ {start} verts={nv}"))
    # end = 下一个块起点
    out = []
    for k, (start, _e, label) in enumerate(ranges[:6]):
        end = ranges[k + 1][0] if k + 1 < len(ranges) else len(ubulk)
        out.append((start, end, label))
    return out


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "M_Head_Head_Helmet_HAAVK_094_3P_HD"
    main(arg)
