"""写真正的 UEFormat `.uemodel`（FModel / DeltaModelViewer 用的那个格式）。

规范来自 https://github.com/h4lfheart/UEFormat ，并与
DeltaModelViewer/DeltaCore/UemodelReader.cs 的读法逐字段对齐：

```
"UEFORMAT" | objectType:FStr("UEMODEL") | version:u8 | objectName:FStr | compressed:u8(0)
body: 若干段 { name:FStr, count:i32, byteSize:i32, payload }
  段 LODS: count = LOD 数；每 LOD = { name:FStr, lodSize:i32, chunk }
     chunk: 若干段 { name, count, byteSize, payload }
       VERTICES   count=nV   payload=nV*12         (float3, ue 空间, cm)
       INDICES    count=nI   payload=nI*4          (uint32)
       NORMALS    count=nV   payload=nV*16         (W(f32) + XYZ(f32))
       TANGENTS   count=nV   payload=nV*12         (float3)
       TEXCOORDS  count=通道数；每通道 int32 n + n*8 (float2)
       MATERIALS  count=材质数；每项 FStr name + FStr path + i32 firstIndex + i32 numFaces
```

坐标：UEFormat 存的是**未转换的 UE 坐标**（DeltaModelViewer 读进来后自己映射到
Y-up），所以我们这里直接用 ue 空间顶点（不套 `ue_to_gl`）。
"""
from __future__ import annotations

import os
import struct
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

MAGIC = b"UEFORMAT"
DEFAULT_VERSION = 1


# --------------------------------------------------------------------------- #
# 基础写盘
# --------------------------------------------------------------------------- #
def _fstr(text: str) -> bytes:
    raw = str(text).encode("utf-8")
    return struct.pack("<i", len(raw) + 1) + raw + b"\x00"


def _section(name: str, count: int, payload: bytes) -> bytes:
    return _fstr(name) + struct.pack("<ii", int(count), len(payload)) + payload


def _vec3_array(arr: np.ndarray) -> bytes:
    return np.ascontiguousarray(arr, dtype="<f4").tobytes()


# --------------------------------------------------------------------------- #
# 网格 → UEFormat
# --------------------------------------------------------------------------- #
def _lod_blob(lod, materials: Optional[Sequence[Any]] = None,
             lod_name: str = "LOD0") -> bytes:
    pos = np.asarray(lod.positions, dtype=np.float32).reshape(-1, 3)
    nrm = np.asarray(lod.normals, dtype=np.float32).reshape(-1, 3) if lod.normals is not None \
        else np.tile(np.array([[0.0, 0.0, 1.0]], np.float32), (len(pos), 1))
    tan = getattr(lod, "tangents", None)
    if tan is None:
        tan = np.tile(np.array([[1.0, 0.0, 0.0]], np.float32), (len(pos), 1))
    else:
        tan = np.asarray(tan, dtype=np.float32)
        tan = tan.reshape(len(pos), -1)[:, :3] if tan.size % len(pos) == 0 else \
            np.tile(np.array([[1.0, 0.0, 0.0]], np.float32), (len(pos), 1))
    idx = np.asarray(lod.indices, dtype=np.uint32).ravel()
    uv = getattr(lod, "uvs", None)
    uv = np.asarray(uv, dtype=np.float32).reshape(-1, 2) if uv is not None \
        else np.zeros((len(pos), 2), np.float32)

    w = np.ones((len(pos), 1), np.float32)              # 副切线符号：1 = 正常
    normals_blob = np.concatenate([w, nrm], axis=1).astype("<f4").tobytes()

    uv_blob = struct.pack("<i", len(uv)) + np.ascontiguousarray(uv, "<f4").tobytes()
    parts: List[bytes] = [
        _section("VERTICES", len(pos), _vec3_array(pos)),
        _section("INDICES", len(idx), idx.astype("<u4").tobytes()),
        _section("NORMALS", len(pos), normals_blob),
        _section("TANGENTS", len(pos), _vec3_array(tan)),
        _section("TEXCOORDS", 1, uv_blob),
    ]

    mats: List[Tuple[str, str, int, int]] = []
    sections = list(getattr(lod, "sections", []) or [])
    if sections:
        for i, sec in enumerate(sections):
            path = str(getattr(sec, "material_path", "") or "")
            name = path.rsplit("/", 1)[-1] if path else f"Section{i}"
            mats.append((name, path, int(getattr(sec, "first_index", 0)),
                         int(getattr(sec, "num_triangles", 0))))
    else:
        mats.append(("Section0", "", 0, len(idx) // 3))
    if materials:
        # 用真实材质名/路径覆盖（顺序对齐 section）
        out: List[Tuple[str, str, int, int]] = []
        for i, (nm, path, first, nf) in enumerate(mats):
            if i < len(materials):
                mat = materials[i]
                nm = str(getattr(mat, "name", nm) or nm)
                path = str(getattr(mat, "pak_path", "") or path)
            out.append((nm, path, first, nf))
        mats = out

    mat_payload = b"".join(_fstr(nm) + _fstr(path) + struct.pack("<ii", first, nf)
                           for nm, path, first, nf in mats)
    parts.append(_section("MATERIALS", len(mats), mat_payload))

    chunk = b"".join(parts)
    return _fstr(lod_name) + struct.pack("<i", len(chunk)) + chunk


def export_uemodel(bundle, path: str, lod: Optional[int] = None,
                  lod_names: Optional[Sequence[str]] = None,
                  version: int = DEFAULT_VERSION) -> str:
    """把 `core.types.ModelBundle`（或 Mesh）写成 UEFormat `.uemodel`。"""
    mesh = getattr(bundle, "mesh", bundle)
    materials = list(getattr(bundle, "materials", []) or [])
    lods = list(getattr(mesh, "lods", []) or [])
    if not lods:
        raise SystemExit("这个资产没有可导出的 LOD")
    picked = range(len(lods)) if lod is None else [int(lod)]
    names = list(lod_names or [f"LOD{i}" for i in range(len(lods))])

    body_lods = []
    for i in picked:
        nm = names[i] if i < len(names) else f"LOD{i}"
        body_lods.append(_lod_blob(lods[i], materials, nm))
    lod_payload = b"".join(body_lods)

    head = (MAGIC + _fstr("UEMODEL") + struct.pack("<B", int(version))
            + _fstr(getattr(mesh, "name", "") or os.path.basename(path)) + b"\x00")
    body = _section("LODS", len(body_lods), lod_payload)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(head + body)
    return path


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print("用法: python -m exporters.ueformat <资产虚拟路径> <out.uemodel> [lod]")
        return 2
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if here not in sys.path:
        sys.path.insert(0, here)
    from core import loader                                   # 延迟导入：打包时更省
    vpath = argv[0]
    if vpath in loader.index():
        bundle = loader.load_model(vpath)
    else:
        hits = [k for k in loader.index() if k.endswith("/" + vpath)]
        if not hits:
            raise SystemExit(f"索引里找不到 {vpath}")
        bundle = loader.load_model(hits[0])
    lod = int(argv[2]) if len(argv) > 2 else None
    out = export_uemodel(bundle, argv[1], lod)
    size = os.path.getsize(out)
    mesh = bundle.mesh
    print(f"写入 {out} ({size} 字节) · {len(mesh.lods)} LOD · "
          f"{len(mesh.lods[0].indices)//3} 三角形 · {len(bundle.materials)} 材质")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
