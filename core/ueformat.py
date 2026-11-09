"""UEFormat `.uemodel` 读写（严格按 h4lfheart/UEFormat 的 docs/generic.md + docs/uemodel.md）。

文件布局（全部小端）：

    FUEFormatHeader
        byte[8]  Magic            "UEFORMAT"
        FString  Identifier        "UEMODEL"
        byte     FileVersion       1
        FString  ObjectName
        FString  ObjectPath
        bool     IsCompressed      （true 时后面跟 CompressionFormat / UncompressedSize / CompressedSize）
    Body：一个根级 FDataAttributeSet
        LODS     : TArray<UEModelLOD>
        SKELETON : FDataAttributeSet
        COLLISION: TArray<FConvexMeshCollision>

    FString            = int32 Length + utf-8 bytes（无 \0）
    FVector            = float X, Y, Z
    FNormal            = float BinormalSign + FVector Normal
    FMeshUVFloat       = float U, V
    FDataAttribute     = FString Name + int32 ByteSize + byte[ByteSize] Data
    UEModelLOD         = FString Name + FDataAttributeSet Attributes

这一段是「照着 UEFormat 写」的，不是自定义格式：别的工具（Blender 插件 / FModel 导出器）
能直接吃我们写出来的文件，我们也能直接读它们写出来的文件。
"""
from __future__ import annotations

import struct
from typing import Dict, List, Tuple

MAGIC = b"UEFORMAT"
IDENT_MODEL = "UEMODEL"
VERSION = 1


class _W:
    def __init__(self) -> None:
        self.b = bytearray()

    def raw(self, data: bytes) -> None:
        self.b += data

    def i32(self, v: int) -> None:
        self.b += struct.pack("<i", int(v))

    def u8(self, v: int) -> None:
        self.b += struct.pack("<B", int(v))

    def f32(self, v: float) -> None:
        self.b += struct.pack("<f", float(v))

    def bool_(self, v: bool) -> None:
        self.b += struct.pack("<?", bool(v))

    def string(self, s: str) -> None:
        data = (s or "").encode("utf-8")
        self.i32(len(data))
        self.b += data

    def vec(self, x: float, y: float, z: float) -> None:
        self.b += struct.pack("<fff", float(x), float(y), float(z))


class _R:
    def __init__(self, data: bytes) -> None:
        self.b = data
        self.o = 0

    def take(self, n: int) -> bytes:
        if self.o + n > len(self.b):
            raise ValueError("uemodel: unexpected end of file")
        out = self.b[self.o:self.o + n]
        self.o += n
        return out

    def i32(self) -> int:
        return struct.unpack("<i", self.take(4))[0]

    def u8(self) -> int:
        return struct.unpack("<B", self.take(1))[0]

    def f32(self) -> float:
        return struct.unpack("<f", self.take(4))[0]

    def bool_(self) -> bool:
        return struct.unpack("<?", self.take(1))[0]

    def string(self) -> str:
        n = self.i32()
        if n <= 0:
            return ""
        return self.take(n).decode("utf-8", "replace")

    def vec(self) -> Tuple[float, float, float]:
        return struct.unpack("<fff", self.take(12))


def _attr_set(fields: List[Tuple[str, bytes]]) -> bytes:
    """FDataAttributeSet：int32 Count + (FString Name + int32 ByteSize + bytes)*."""
    w = _W()
    w.i32(len(fields))
    for name, payload in fields:
        w.string(name)
        w.i32(len(payload))
        w.raw(payload)
    return bytes(w.b)


def _read_attr_set(r: _R) -> Dict[str, bytes]:
    n = r.i32()
    out: Dict[str, bytes] = {}
    for _ in range(max(0, n)):
        name = r.string()
        size = r.i32()
        out[name] = r.take(max(0, size))
    return out


# --------------------------------------------------------------------------- #
# write
# --------------------------------------------------------------------------- #
def write_uemodel(mesh, path: str, *, object_name: str = "", object_path: str = "",
                  material_paths: Dict[int, str] | None = None) -> dict:
    """把 `core.types.Mesh` 写成 UEFormat `.uemodel`。返回统计信息。"""
    import numpy as np

    lods: List[Tuple[str, bytes]] = []
    mat_paths = material_paths or {}
    total_v = total_f = 0
    for li, lod in enumerate(mesh.lods):
        pos = np.asarray(lod.positions, np.float32).reshape(-1, 3)
        nrm = np.asarray(lod.normals, np.float32).reshape(-1, 3)
        uv = np.asarray(lod.uvs, np.float32).reshape(len(pos), -1)
        idx = np.asarray(lod.indices, np.uint32).reshape(-1)

        w = _W()
        # VERTICES : TArray<FVector>
        w.i32(len(pos))
        for p in pos:
            w.vec(*p)
        verts = bytes(w.b)

        # NORMALS : TArray<FNormal>（BinormalSign + Normal）
        w = _W()
        w.i32(len(nrm))
        for nv in nrm:
            w.f32(1.0)
            w.vec(*nv)
        norms = bytes(w.b)

        # TANGENTS : TArray<FVector>（有就写，没有写 0 长度数组）
        tan = getattr(lod, "tangents", None)
        w = _W()
        if tan is not None and len(tan):
            ta = np.asarray(tan, np.float32).reshape(len(pos), -1)[:, :3]
            w.i32(len(ta))
            for tv in ta:
                w.vec(*tv)
        else:
            w.i32(0)
        tang = bytes(w.b)

        # TEXCOORDS : TArray<FTexCoordEntry>（只写 UV0，名字按 UEFormat 习惯叫 UVMap）
        w = _W()
        w.i32(1)
        w.string("UVMap")
        w.i32(len(uv))
        for u in uv:
            w.f32(u[0])
            w.f32(u[1] if len(u) > 1 else 0.0)
        texcoords = bytes(w.b)

        # INDICES : TArray<uint>
        w = _W()
        w.i32(len(idx))
        w.raw(idx.astype("<u4").tobytes())
        indices = bytes(w.b)

        # MATERIALS : TArray<FMaterial>
        w = _W()
        secs = list(getattr(lod, "sections", []) or [])
        w.i32(len(secs))
        for si, sec in enumerate(secs):
            w.string(sec.material_path.rsplit("/", 1)[-1] if sec.material_path else f"Section{si}")
            w.string(mat_paths.get(si, sec.material_path or ""))
            w.i32(int(sec.first_index))
            w.i32(int(sec.num_triangles))
        materials = bytes(w.b)

        fields = [("VERTICES", verts), ("NORMALS", norms), ("TANGENTS", tang),
                  ("TEXCOORDS", texcoords), ("INDICES", indices), ("MATERIALS", materials)]
        name = f"LOD{li}"
        w = _W()
        w.string(name)
        w.raw(_attr_set(fields))
        lods.append((name, bytes(w.b)))
        total_v += len(pos)
        total_f += len(idx) // 3

    # LODS : TArray<UEModelLOD>
    w = _W()
    w.i32(len(lods))
    for _, blob in lods:
        w.raw(blob)
    lods_blob = bytes(w.b)

    body = _attr_set([
        ("LODS", lods_blob),
        ("SKELETON", _attr_set([])),
        ("COLLISION", struct.pack("<i", 0)),
    ])

    w = _W()
    w.raw(MAGIC)
    w.string(IDENT_MODEL)
    w.u8(VERSION)
    w.string(object_name or mesh.name or "")
    w.string(object_path or "")
    w.bool_(False)          # IsCompressed
    w.raw(body)

    with open(path, "wb") as fh:
        fh.write(bytes(w.b))
    return {"path": path, "bytes": len(w.b), "lods": len(lods),
            "vertices": total_v, "triangles": total_f, "format": "UEFORMAT/UEMODEL"}


# --------------------------------------------------------------------------- #
# read  -> core.types.Mesh
# --------------------------------------------------------------------------- #
def read_uemodel(path: str):
    """读 UEFormat `.uemodel`，返回 `(Mesh, object_name, object_path)`。"""
    import numpy as np
    from .types import Mesh, MeshLOD, Section

    with open(path, "rb") as fh:
        data = fh.read()
    r = _R(data)
    if r.take(8) != MAGIC:
        raise ValueError("不是 UEFormat 文件（magic 不匹配）")
    ident = r.string()
    if ident != IDENT_MODEL:
        raise ValueError(f"只支持 UEMODEL，这个文件是 {ident!r}")
    _version = r.u8()
    object_name = r.string()
    object_path = r.string()
    if r.bool_():
        r.string()          # CompressionFormat
        r.i32()             # UncompressedSize
        r.i32()             # CompressedSize
        raise ValueError("压缩的 uemodel 暂不支持（FModel 默认不压缩）")

    root = _read_attr_set(r)
    lods_blob = root.get("LODS", struct.pack("<i", 0))
    lr = _R(lods_blob)
    count = lr.i32()
    mesh = Mesh(name=object_name or "Model", pak_path=object_path, source_format="UEFORMAT")
    for li in range(max(0, count)):
        _name = lr.string()
        attrs = _read_attr_set(lr)

        def _array(payload: bytes, stride_bytes: int):
            """TArray<T>：int32 Count + Count*stride 字节。"""
            if not payload:
                return 0, b""
            return struct.unpack_from("<i", payload, 0)[0], payload[4:]

        n_pos, vb = _array(attrs.get("VERTICES", b""), 12)
        pos = np.frombuffer(vb[:n_pos * 12], np.float32).reshape(-1, 3).copy()

        n_nrm, nb = _array(attrs.get("NORMALS", b""), 16)
        if nb:
            # FNormal = BinormalSign(float) + XYZ(float*3) = 16 字节
            raw = np.frombuffer(nb[:n_nrm * 16], np.uint8).reshape(-1, 16)
            nrm = raw[:, 4:].copy().view("<f4").reshape(-1, 3).astype(np.float32)
        else:
            nrm = np.zeros_like(pos)

        n_tan, tb = _array(attrs.get("TANGENTS", b""), 12)
        tn = np.frombuffer(tb[:n_tan * 12], np.float32).reshape(-1, 3).copy() if n_tan else None

        ub = attrs.get("TEXCOORDS", b"")
        uv = np.zeros((len(pos), 2), np.float32)
        if ub:
            ur = _R(ub)
            nentry = ur.i32()
            first = True
            for _ in range(max(0, nentry)):
                ur.string()                      # 通道名（UVMap / LightMap …）
                n = ur.i32()
                arr = np.frombuffer(ur.take(n * 8), np.float32).reshape(-1, 2)
                if first:
                    uv[:len(arr)] = arr
                    first = False

        n_idx, ib = _array(attrs.get("INDICES", b""), 4)
        idx = np.frombuffer(ib[:n_idx * 4], "<u4").copy() if n_idx else np.zeros(0, np.uint32)

        mb = attrs.get("MATERIALS", b"")
        sections: List[Section] = []
        if mb:
            mr = _R(mb)
            nmat = mr.i32()
            for _ in range(max(0, nmat)):
                mname = mr.string()
                mpath = mr.string()
                first_i = mr.i32()
                nfaces = mr.i32()
                sections.append(Section(material_path=mpath or mname, first_index=first_i,
                                        num_triangles=nfaces, first_vertex=0,
                                        num_vertices=len(pos)))
        if not sections:
            sections = [Section(material_path=None, first_index=0,
                                num_triangles=len(idx) // 3, first_vertex=0,
                                num_vertices=len(pos))]

        lod = MeshLOD(positions=pos, normals=nrm, uvs=uv,
                      tangents=tn if tn is not None else np.zeros_like(pos),
                      indices=idx.astype(np.uint32), sections=sections)
        mesh.lods.append(lod)
    return mesh, object_name, object_path
