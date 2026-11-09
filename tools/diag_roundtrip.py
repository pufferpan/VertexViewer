"""`.uemodel` 往返一致性检查（我们写 -> 我们读，逐数组比对）。

    python tools/diag_roundtrip.py
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from core import loader  # noqa: E402
from core import ueformat  # noqa: E402

VPATHS = [
    "../../../DeltaForce/Content/Models/Props/Collect/props_collect_Catgoods_1199/props_collect_Catgoods_1199_3P.uasset",
    "../../../DeltaForce/Content/Models/Weapons/Parts/Mag/Mag_AK74_545x39-30R-Std_004/SM_Mag_AK74_545x39-30R-Std_004_3P.uasset",
]


def cmp(name, a, b):
    if a is None or b is None:
        print(f"   {name:10s} a={None if a is None else a.shape} b={None if b is None else b.shape}")
        return
    if a.shape != b.shape:
        print(f"   {name:10s} !! shape {a.shape} -> {b.shape}")
        return
    d = float(np.abs(a.astype(np.float64) - b.astype(np.float64)).max())
    bad = int((np.abs(a.astype(np.float64) - b.astype(np.float64)) > 1e-5).any(axis=1).sum()) \
        if a.ndim > 1 else -1
    print(f"   {name:10s} ok shape={a.shape} max|d|={d:.6g} 差异行={bad}")


def main():
    os.environ["VERTEXVIEWER_NO_UEFORMAT"] = "1"
    for vp in VPATHS:
        loader._MESH_CACHE.clear()
        m = loader.load_mesh(vp)
        if not m:
            print("load failed", vp)
            continue
        print("\n===", vp.rsplit("/", 1)[-1], "lods:", len(m.lods),
              "uv_channels:", getattr(m.lods[0], "uv_channels", "?"))
        tmp = os.path.join(tempfile.gettempdir(), "rt_test.uemodel")
        ueformat.write_uemodel(m, tmp, object_name="rt", object_path=vp)
        back, _n, _p = ueformat.read_uemodel(tmp)
        if not back.lods:
            print("   !! 读回没有 LOD")
            continue
        for i, (a, b) in enumerate(zip(m.lods, back.lods)):
            print(f"  LOD{i} orig tris={a.triangle_count} back tris={b.triangle_count}")
            cmp("positions", a.positions, b.positions)
            cmp("normals", a.normals, b.normals)
            cmp("uvs", a.uvs, b.uvs)
            cmp("tangents", a.tangents, b.tangents)
            cmp("indices", a.indices.reshape(-1, 1), b.indices.reshape(-1, 1))
            if a.uvs is not None and b.uvs is not None and a.uvs.shape == b.uvs.shape:
                # V 翻转的迹象
                dv = float(np.abs(a.uvs[:, 1] - (1.0 - b.uvs[:, 1])).max())
                print(f"   (V 翻转匹配度: |a.v-(1-b.v)| max={dv:.4g}  -> "
                      f"{'像是翻了 V' if dv < 1e-5 else '没翻 V'})")
        os.remove(tmp)


if __name__ == "__main__":
    main()
