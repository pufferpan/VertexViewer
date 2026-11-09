"""探针：干员网格只有 1 个 section，但材质槽有 N 个。

思路：拿每个材质槽的 BaseColor 贴图，按三角形 UV 质心采样，
哪个材质在图上有内容（非空、非纯黑）就归哪个材质。
本脚本只统计可分性，不改渲染。

用法：python tools/_mat_split_probe.py M_Elio_7DL9D_9j_A_Body_3P_HD
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                              # noqa: E402

from core import loader                                          # noqa: E402


def _tex_array(tex) -> np.ndarray | None:
    """贴图对象 -> (H,W,4) uint8。core.texture 里常见字段是 `pixels`/`array`。"""
    for name in ("rgba", "pixels", "array", "data"):
        arr = getattr(tex, name, None)
        if isinstance(arr, np.ndarray) and arr.ndim in (2, 3):
            if arr.ndim == 2:
                arr = np.dstack([arr, arr, arr, np.full(arr.shape, 255, arr.dtype)])
            if arr.shape[2] == 3:
                arr = np.dstack([arr, np.full(arr.shape[:2], 255, arr.dtype)])
            return arr
    return None


def main() -> None:
    want = sys.argv[1] if len(sys.argv) > 1 else "M_Elio_7DL9D_9j_A_Body_3P_HD"
    index = loader.index()
    vpaths = [k for k in index if k.endswith(want + ".uasset")]
    if not vpaths:
        print("找不到资产:", want)
        return
    bundle = loader.load_model(vpaths[0], want_textures=True)
    mesh = bundle.mesh
    lod = mesh.lods[0]
    print(f"{want}: 顶点 {lod.positions.shape[0]} 三角 {lod.indices.size // 3} "
          f"段 {len(lod.sections)} 材质 {len(bundle.materials)}")

    uv = None
    sets = getattr(lod, "uv_sets", None)
    if sets is not None and getattr(sets, "ndim", 0) == 3:
        for ch in range(sets.shape[1]):
            cand = np.asarray(sets[:, ch, :], dtype=np.float32)
            print(f"  UV 通道 {ch}: 范围 {float(cand.min()):.3f} ~ {float(cand.max()):.3f}")
            if uv is None:
                uv = cand
    if uv is None and lod.uvs is not None:
        uv = np.asarray(lod.uvs, dtype=np.float32)
    if uv is None or uv.size == 0:
        print("没有 UV")
        return
    print("UV 形状:", uv.shape, "范围:", float(uv.min()), float(uv.max()))

    by_pak = {getattr(t, "pak_path", ""): t for t in bundle.textures}
    maps = []
    for i, mat in enumerate(bundle.materials):
        tex = None
        want = getattr(mat, "base_color_texture", "") or ""
        if want:
            tex = by_pak.get(want)
            if tex is None:
                short = want.rsplit("/", 1)[-1]
                for t in bundle.textures:
                    if getattr(t, "pak_path", "").endswith(short):
                        tex = t
                        break
        arr = _tex_array(tex) if tex is not None else None
        maps.append(arr)
        print(f"  材质[{i}] {getattr(mat, 'name', '?')[:44]:<44} 贴图 "
              f"{'无' if arr is None else f'{arr.shape[1]}x{arr.shape[0]}'}")

    tri = lod.indices.reshape(-1, 3)
    cen = uv[tri].mean(axis=1)                                  # (T,2)
    print("UV 质心范围:", float(cen.min()), float(cen.max()))

    scores = []
    for arr in maps:
        if arr is None:
            scores.append(None)
            continue
        h, w = arr.shape[:2]
        px = np.clip((cen[:, 0] % 1.0) * (w - 1), 0, w - 1).astype(np.int32)
        py = np.clip((cen[:, 1] % 1.0) * (h - 1), 0, h - 1).astype(np.int32)
        rgb = arr[py, px, :3].astype(np.float32)
        alpha = arr[py, px, 3].astype(np.float32) if arr.shape[2] > 3 else 255.0
        lum = rgb.mean(axis=1)
        scores.append(((lum > 4.0) & (alpha > 8.0)).astype(np.float32))

    usable = [i for i, s in enumerate(scores) if s is not None]
    if not usable:
        print("没有可用贴图")
        return
    stack = np.stack([scores[i] for i in usable], axis=1)       # (T, M)
    total = stack.sum(axis=1)
    best = stack.argmax(axis=1)
    print(f"\n三角形 {stack.shape[0]}，平均命中材质数 {total.mean():.2f}")
    for k, i in enumerate(usable):
        cnt = int(((best == k) & (total > 0)).sum())
        print(f"  材质[{i}] 独占 {cnt:6d} 三角 ({cnt / len(best) * 100:5.1f}%)")
    print(f"  一个都没命中 {int((total == 0).sum())}，多命中 {int((total > 1).sum())}")


if __name__ == "__main__":
    main()
