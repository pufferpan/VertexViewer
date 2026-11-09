"""Geometry extraction for Game (UE5 cooked) static / skeletal meshes.

The format was reverse engineered byte by byte on real game packages; see
``NOTES.md`` for the measured offsets.  Two independent sources of truth are
used and cross-validated:

* the ``.uexp`` export payload carries the tagged property block (material
  slots, bounds) and the per-LOD ``FStaticMeshSection`` metadata;
* the ``.ubulk`` file carries one self-describing blob per LOD.  Every blob
  starts with a 2 byte ``FStripDataFlags`` followed by
  ``FPositionVertexBuffer``::

      i32 stride (=12) | i32 num_vertices | i32 12 | i32 num_vertices | positions

  then ``FStaticMeshVertexBuffer`` (strip flags, num_texcoords, num_vertices,
  two bools, 4 unknown bytes, tangents bulk, uv bulk), then the raw index
  buffers.

Because the exact length of the object level native prefix (``bCooked`` etc.)
is not needed, the meshes are located by scanning for their section records and
matched against the ubulk blobs by vertex count.  That makes the parser immune
to the ``FDeltaForceNaniteResources`` skip whose length is unknown.

Inline (no ``.ubulk``) skeletal flavour
---------------------------------------
Head / equipment skeletal meshes under ``Models/Equipments_HD/**`` are cooked
completely into ``.uexp`` (``ubulk`` absent).  Their per LOD layout is::

    [FMultisizeIndexContainer]  u32 elem_size=2 | u32 count | count*u16
    [FPositionVertexBuffer]     i32 12 | i32 num_vertices | i32 12 | i32 num_vertices
                                | num_vertices * 3 * f32
    [FStaticMeshVertexBuffer]   tangents (num_vertices * 8 bytes), uvs (n * 2 * f32)

so the index container *precedes* the position buffer of the same LOD, and its
data ends exactly at the position header.  The 9 bytes before ``elem_size`` are
``01 01 02 02 00 00 00`` in every sampled asset of this flavour.  Because the
``.uasset`` part of the virtual payload has an odd length (e.g. 4025 for
``M_Head_Head_Helmet_HAAVK_094_3P_HD``), every ``.uexp``-aligned u16 lands on an
*odd* virtual offset: both byte parities must be scanned.

Note on ``M_Head_Head_Helmet_HAAVK_094_3P_HD`` (and ``_LAY_HD`` / ``_UI_HD``):
it decodes to a *multi patch* mesh (360 connected components, largest 411 of
4948 triangles, boundary ratio 0.399) at every LOD.  This was verified to be the
asset itself, not a decode error: only 4 all-valid index windows exist in the
whole 507 KB payload and the one actually used is the best of them; the
independent ubulk path (``_LAY_HD``) yields the same topology; interior edges are
100% consistently wound (5574/5574); vertex normals agree with face normals
(median dot 0.91); and welding coincident positions (4666 -> 2945) drops the
boundary ratio to 0.103 without changing the component structure.  The
fragmentation is therefore not fixed by any loader change -- do not chase it.

Two loader pitfalls this flavour exposed (both fixed here):
``_scan_container_list`` used to truncate its candidate list to the 48 largest
containers *before* the ``max index < num_vertices`` screen, so the tiny index
list of a small LOD was crowded out by the big lists of the other LODs (094 LOD3
/ LOD5 decoded as 300/2 triangles instead of 699/100); and a candidate whose
length was not a multiple of 3 reached ``_index_quality`` and raised
``cannot reshape array of size 127 into shape (3)``.
"""

from __future__ import annotations

import struct

import numpy as np

from . import uasset
from .types import Mesh, MeshLOD, Section, ue_dir_to_gl, ue_to_gl

__all__ = ["load_mesh_from_blobs", "load_mesh_from_bytes", "MeshError"]

POS_STRIDE = 12
MATERIAL_ROOT = "../../../DeltaForce/Content"


class MeshError(Exception):
    """Raised when a package does not contain a decodable mesh."""


# --------------------------------------------------------------------------- #
# entry points
# --------------------------------------------------------------------------- #
def load_mesh_from_blobs(vpath: str, blobs: dict) -> Mesh:
    """Preferred entry point used by ``core.loader``."""
    return load_mesh_from_bytes(
        blobs.get("uasset") or b"",
        blobs.get("uexp"),
        blobs.get("ubulk"),
        vpath,
    )


def load_mesh_from_bytes(uasset_bytes, uexp, ubulk, pak_path) -> Mesh:
    if not uasset_bytes:
        raise MeshError("empty .uasset")
    pkg = uasset.Package(uasset_bytes, uexp, ubulk, pak_path)
    exports = pkg.find_exports("StaticMesh")
    skeletal = pkg.find_exports("SkeletalMesh")
    if not exports and skeletal:
        return _load_skeletal(pkg, skeletal[0], pak_path)
    if not exports:
        raise MeshError("no StaticMesh/SkeletalMesh export in %s" % pak_path)

    export = exports[0]
    for candidate in exports:          # prefer the root object
        if candidate.outer_index == 0:
            export = candidate
            break

    r = pkg.export_reader(export)
    props = {}
    prop_start = r.pos
    try:
        props = pkg.read_properties(r)
    except Exception:                  # property block is optional for geometry
        props = {}
        r.pos = prop_start             # the reader may be mid-tag on failure
    materials = _material_paths(pkg, props)

    virtual = pkg.virtual()
    blobs = _analyse_ubulk(ubulk or b"")
    if not blobs:
        # cooked without a separate bulk file: the buffers live inline in .uexp
        heads = _find_position_headers(virtual, export.serial_offset, r.end)
        for i, (pos_off, _num) in enumerate(heads):
            blob_end = heads[i + 1][0] if i + 1 < len(heads) else r.end
            try:
                blobs.append(_parse_blob(virtual, max(export.serial_offset,
                                                      pos_off - 2),
                                         blob_end, pos_off))
            except Exception:              # noqa: BLE001
                blobs.append(None)
    expected = [b["num_vertices"] for b in blobs if b is not None]
    # scanning is anchor driven, so start at the export head: some packages carry
    # property types we do not decode and the scan does not care about them.
    section_lods = _scan_lod_sections(virtual, export.serial_offset, r.end, expected)
    if not section_lods:
        raise MeshError("no FStaticMeshSection records in %s" % pak_path)

    lods = _build_lods(blobs, section_lods, materials)
    if not lods:
        raise MeshError("no LOD buffers decoded for %s" % pak_path)

    center, extent = _bounds(props, lods)
    return Mesh(
        name=export.name or _asset_name(pak_path),
        pak_path=pak_path,
        lods=lods,
        bounds_center=center,
        bounds_extent=extent,
        source_format="UE5.0/DF",
    )


def _asset_name(path):
    base = str(path).replace("\\", "/").rsplit("/", 1)[-1]
    return base.split(".", 1)[0]


# --------------------------------------------------------------------------- #
# materials
# --------------------------------------------------------------------------- #
def _material_paths(pkg, props):
    """``StaticMaterials`` -> ``../../../DeltaForce/Content/...`` asset paths."""
    out = []
    raw = props.get("StaticMaterials") if isinstance(props, dict) else None
    if not isinstance(raw, list):
        return out
    for entry in raw:
        if isinstance(entry, dict):
            # measured layout: [{'StaticMaterials': {...}}]
            inner = entry.get("StaticMaterials", entry)
            if isinstance(inner, dict):
                path = inner.get("MaterialInterface")
                if isinstance(path, str) and path:
                    out.append(_to_asset_path(path, pkg))
                    continue
        out.append(None)
    return out


def _to_asset_path(path, pkg=None):
    """``/Game/Foo/Bar.Bar`` -> ``../../../DeltaForce/Content/Foo/Bar.uasset``."""
    if not path:
        return None
    full = path
    if pkg is not None and not path.startswith("/"):
        try:
            full = pkg.object_path(int(path)) if path.lstrip("-").isdigit() else path
        except Exception:
            full = path
    full = full.replace("\\", "/")
    if full.startswith("/Game/"):
        full = full[len("/Game/"):]
    elif "/Game/" in full:
        full = full.split("/Game/", 1)[1]
    elif full.startswith("/Script/"):
        return full
    # strip the trailing ".ObjectName"
    if "." in full.rsplit("/", 1)[-1]:
        full = full.rsplit(".", 1)[0]
    if full.startswith("/"):
        full = full.lstrip("/")
    return "%s/%s.uasset" % (MATERIAL_ROOT, full)


# --------------------------------------------------------------------------- #
# section metadata (lives in the .uexp export payload)
# --------------------------------------------------------------------------- #
class _SectionInfo:
    __slots__ = ("material_index", "first_index", "num_triangles",
                 "min_vertex", "max_vertex")

    def __init__(self, material_index, first_index, num_triangles,
                 min_vertex, max_vertex):
        self.material_index = material_index
        self.first_index = first_index
        self.num_triangles = num_triangles
        self.min_vertex = min_vertex
        self.max_vertex = max_vertex

    def __repr__(self):
        return "<Section m=%d tri=%d maxv=%d>" % (
            self.material_index, self.num_triangles, self.max_vertex)


def _scan_lod_sections(buf, start, end, expected_verts=()):
    """Scan for ``FStripDataFlags + TArray<FStaticMeshSection>`` records.

    The native object prefix that precedes the LOD array has an unknown length
    (``FDeltaForceNaniteResources``), so the records are located by shape.  The
    strongest discriminator is the *vertex count*: Game writes
    ``MaxVertexIndex == num_vertices - 1`` for every LOD, and the vertex counts
    are already known from the ``.ubulk`` position buffers.

    ``expected_verts`` is the list of per-LOD vertex counts in file order.
    Returns ``[(offset, [sections]), ...]`` ordered like the package.
    """
    mv = memoryview(buf)
    strict = bool(expected_verts)
    for anchor in ((True, False) if strict else (False,)):
        for require_order in ((True, False) if anchor else (False,)):
            found = _scan_pass(mv, buf, start, end,
                               expected_verts if anchor else (), require_order)
            if found:
                return _pick_best(found)
    return []


def _pick_best(found):
    """同一份 uexp 里常能扫到多个「形状像 sections」的记录。

    该游戏的 1P 模型（比如 HoneycombSmoke）其实有 4 个 section（4 个材质），
    但扫描时会先撞上一个 count=1 的近似记录 —— 只有一个 section 就意味着整网格
    用第 0 个材质渲染，四个部件贴同一张图 = 用户说的「1P 贴图乱、3P 正常」。
    所以按顶点数分组后，**section 多的候选优先**（真正的 LOD 记录一定是完整的一套）。
    """
    by_verts = {}
    order = []
    for pos, secs in found:
        n = max(s.max_vertex for s in secs) + 1
        if n not in by_verts:
            by_verts[n] = []
            order.append(n)
        by_verts[n].append((pos, secs))
    out = []
    for n in order:
        cands = by_verts[n]
        best = max(cands, key=lambda c: (len(c[1]), sum(s.num_triangles for s in c[1])))
        out.append(best[1])
    return out


def _scan_pass(mv, buf, start, end, expected, require_order):
    found = []
    pos = start
    lod_index = 0
    while pos + 6 <= end:
        # FStripDataFlags: two small bytes (0x01 0x00 / 0x01 0x01 / 0x00 0x00)
        if buf[pos] > 3 or buf[pos + 1] > 3:
            pos += 1
            continue
        count = struct.unpack_from("<i", mv, pos + 2)[0]
        if count < 1 or count > 64:
            pos += 1
            continue
        sections, num_vertices = _read_sections(mv, pos + 6, end, count)
        ok = sections
        if ok and expected:
            # a LOD's triangles always cover at least half of its vertices; this
            # rejects the tiny 20-byte look-alikes that live in the bulk table
            triangles = sum(s.num_triangles for s in sections)
            has_indices = triangles * 3 >= num_vertices * 0.5
            if require_order and lod_index < len(expected):
                # the vertex count of a LOD record always equals its position
                # buffer size: partial records (only the first sections of a big
                # LOD) are rejected here instead of being matched to a blob later
                ok = num_vertices == expected[lod_index]
            else:
                ok = num_vertices in expected
            ok = ok and has_indices
        if not ok:
            pos += 1
            continue
        found.append((pos, sections))
        lod_index += 1
        pos += 6 + count * 20
    return found


def _read_sections(mv, off, end, count):
    """Parse ``count`` 20-byte section records; also return ``max_vertex + 1``."""
    secs = []
    expect_first = 0
    max_vertex = -1
    for i in range(count):
        base = off + i * 20
        if base + 20 > end:
            return [], 0
        mat, first, tris, minv, maxv = struct.unpack_from("<5i", mv, base)
        if mat < 0 or mat > 512:
            return [], 0
        if tris <= 0 or tris > 4_000_000:
            return [], 0
        if first < 0 or minv < 0 or maxv < minv or maxv > 4_000_000:
            return [], 0
        if first != expect_first:      # sections must tile the index buffer
            return [], 0
        expect_first = first + tris * 3
        max_vertex = max(max_vertex, maxv)
        secs.append(_SectionInfo(mat, first, tris, minv, maxv))
    if max_vertex < 0:
        return [], 0
    return secs, max_vertex + 1


# --------------------------------------------------------------------------- #
# ubulk buffers
# --------------------------------------------------------------------------- #
class _Blob:
    """One LOD worth of serialized vertex/index buffers."""

    def __init__(self, offset, end):
        self.offset = offset
        self.end = end


def _find_blobs(buf):
    """Locate every ``FPositionVertexBuffer`` header in the ubulk stream."""
    mv = memoryview(buf)
    n = len(buf)
    hits = []
    for i in range(0, n - 16):
        stride, num, _, num2 = struct.unpack_from("<4i", mv, i)
        if stride != POS_STRIDE or num != num2 or num <= 0 or num > 4_000_000:
            continue
        if i + 16 + num * POS_STRIDE > n:
            continue
        if not hits or i - hits[-1] > 16:
            hits.append(i)
    return hits


def _analyse_ubulk(ubulk):
    """Split the ``.ubulk`` stream into per-LOD blobs and decode each one."""
    if not ubulk:
        return []
    hits = _find_blobs(ubulk)
    if not hits:
        return []
    starts = [max(0, h - 2) for h in hits]
    ends = starts[1:] + [len(ubulk)]
    out = []
    for blob_start, blob_end, pos_off in zip(starts, ends, hits):
        try:
            out.append(_parse_blob(ubulk, blob_start, blob_end, pos_off))
        except Exception:                                          # noqa: BLE001
            out.append(None)
    return out


def _build_lods(blobs, section_lods, materials):
    """Pair every decoded blob with its section metadata (or infer its indices)."""
    if not blobs:
        return []
    by_blob = {}
    for secs in section_lods:
        num_vertices = max(s.max_vertex for s in secs) + 1
        for j, blob in enumerate(blobs):
            if blob is None or j in by_blob:
                continue
            if blob["num_vertices"] != num_vertices:
                continue
            lod = _make_lod(blob, secs, materials,
                            triangles_texture_hint=sum(s.num_triangles for s in secs))
            if lod is not None:
                by_blob[j] = lod
            break
    # Sections found but their vertex count does not match any blob (the last
    # LOD often reuses a trimmed section record): pair them by order instead, so
    # the material paths are still correct.
    if len(section_lods) == len(blobs):
        for j, blob in enumerate(blobs):
            if blob is None or j in by_blob:
                continue
            secs = section_lods[j]
            lod = _make_lod(blob, secs, materials,
                            triangles_texture_hint=sum(s.num_triangles for s in secs))
            if lod is not None:
                by_blob[j] = lod
    # LODs whose section record was not located: take the whole index run of the
    # blob, which yields the correct triangle count (sections become one bucket)
    for j, blob in enumerate(blobs):
        if blob is None or j in by_blob:
            continue
        indices = _resolve_indices(blob["raw"],
                                   max(blob.get("blob_start", 0),
                                       blob["index_offset"] - 64),
                                   blob["blob_end"],
                                   blob.get("blob_start", 0), blob["blob_end"],
                                   blob["num_vertices"], blob["positions"],
                                   pos_off=blob.get("pos_off"))
        if indices is None:
            indices = _find_index_run(blob["raw"], blob["index_offset"],
                                      blob["blob_end"], blob["num_vertices"],
                                      blob["positions"])
        if indices is None or indices.size < 3:
            continue
        section = Section(
            material_path=materials[0] if materials else None,
            first_index=0,
            num_triangles=int(indices.size // 3),
            first_vertex=0,
            num_vertices=blob["num_vertices"],
        )
        lod = _assemble_lod(blob, indices, [section])
        if lod is not None:
            by_blob[j] = lod
    return [by_blob[j] for j in sorted(by_blob)]


def _parse_blob(buf, blob_start, blob_end, pos_off):
    mv = memoryview(buf)
    stride, num_vertices, _, _ = struct.unpack_from("<4i", mv, pos_off)
    pos_start = pos_off + 16
    pos_end = pos_start + num_vertices * POS_STRIDE
    if pos_end > blob_end:
        raise MeshError("position buffer overruns blob")
    positions = np.frombuffer(buf, dtype="<f4", count=num_vertices * 3,
                              offset=pos_start).reshape(num_vertices, 3)

    # FStaticMeshVertexBuffer
    vb = pos_end
    num_texcoords, num_vertices2, tangents, uvs = _parse_vertex_buffer(
        buf, vb, blob_end, num_vertices)

    tan_arr = None
    if tangents is not None:
        tan_arr = np.frombuffer(buf, dtype=np.uint8,
                                count=tangents[1] * tangents[2],
                                offset=tangents[0]).reshape(tangents[1], tangents[2])
    uv_arr = None
    if uvs is not None:
        uv_start, item_count, item_size = uvs
        if item_size == 4:
            uv_arr = np.frombuffer(buf, dtype="<f2", count=item_count * 2,
                                   offset=uv_start).astype(np.float32)
            uv_arr = uv_arr.reshape(item_count, 2)
        elif item_size == 8:
            uv_arr = np.frombuffer(buf, dtype="<f4", count=item_count * 2,
                                   offset=uv_start).reshape(item_count, 2)
        else:
            uv_arr = np.frombuffer(buf, dtype="<f4", count=item_count,
                                   offset=uv_start).reshape(item_count, -1)

    index_off = uvs[0] + uvs[1] * uvs[2] if uvs is not None else pos_end
    return {
        "raw": buf,
        "blob_start": blob_start,
        "num_vertices": num_vertices,
        "positions": positions,
        "num_texcoords": num_texcoords,
        "tangents": tan_arr,
        "uvs": uv_arr,
        "index_offset": index_off,
        "blob_end": blob_end,
        "pos_off": pos_off,
    }


def _parse_vertex_buffer(buf, start, blob_end, num_vertices):
    """Return ``(num_texcoords, num_vertices, tangents, uvs)``.

    ``tangents``/``uvs`` are ``(data_offset, element_count, element_size)``.
    The measured layout (see module docstring) leaves a few unknown bytes
    between ``num_vertices`` and the tangent bulk header, so the header is
    located by validating ``element_count == num_vertices``.
    """
    mv = memoryview(buf)
    best = None
    for base in (start, start + 2):
        if base + 10 > blob_end:
            continue
        num_texcoords = struct.unpack_from("<i", mv, base + 2)[0]
        num = struct.unpack_from("<i", mv, base + 6)[0]
        if num != num_vertices or num_texcoords < 1 or num_texcoords > 8:
            continue
        for gap in range(8, 40, 2):
            hdr = base + 10 + gap
            if hdr + 8 > blob_end:
                break
            item_size, item_count = struct.unpack_from("<2i", mv, hdr)
            if item_count != num_vertices or item_size not in (4, 8, 16):
                continue
            if hdr + 8 + item_size * item_count > blob_end:
                continue
            uv_hdr = hdr + 8 + item_size * item_count
            if uv_hdr + 8 > blob_end:
                continue
            uv_size, uv_count = struct.unpack_from("<2i", mv, uv_hdr)
            if uv_size not in (2, 4, 8, 12, 16) or uv_count <= 0:
                continue
            if uv_count not in (num_vertices * num_texcoords,
                               (num_vertices + num_texcoords % 2) * num_texcoords,
                               (num_vertices + num_vertices % 2) * num_texcoords):
                continue
            if uv_hdr + 8 + uv_size * uv_count > blob_end:
                continue
            best = (num_texcoords, num,
                    (hdr + 8, item_count, item_size),
                    (uv_hdr + 8, uv_count, uv_size))
            break
        if best is not None:
            break
    if best is None:
        return 0, num_vertices, None, None
    return best


# --------------------------------------------------------------------------- #
# LOD assembly
# --------------------------------------------------------------------------- #
def _make_lod(blob, secs, materials, triangles_texture_hint=0):
    num_vertices = blob["num_vertices"]
    need = triangles_texture_hint * 3
    positions = blob["positions"]
    start = max(blob.get("blob_start", blob["index_offset"]),
                blob["index_offset"] - 64)
    indices = _resolve_indices(blob["raw"], start, blob["blob_end"],
                               blob.get("blob_start", start), blob["blob_end"],
                               num_vertices, positions,
                               pos_off=blob.get("pos_off"))
    if indices is None:
        indices = _find_indices(blob["raw"], blob["index_offset"],
                                blob["blob_end"], num_vertices, need, positions)
    if indices is None:
        return None
    if need > 0 and indices.size == need:
        indices = indices[:need]
    return _assemble_lod(blob, indices, _sections_from(secs, materials))


def _triangle_areas(indices, positions):
    """Per-triangle area (m^2 units of *positions*) for an index array."""
    if indices.size == 0:
        return np.zeros((0,), np.float64)
    tri = positions[indices.reshape(-1, 3)]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    return 0.5 * np.linalg.norm(cross, axis=1)


def _index_quality(indices, positions):
    """``(degenerate_ratio, max/median area)`` -- lower is better."""
    indices = np.asarray(indices).ravel()
    if indices.size % 3:                   # partial triangle -> score complete ones
        indices = indices[: indices.size - indices.size % 3]
    if indices.size < 3 or positions.size == 0:
        return 1.0, 1e9
    # 这个函数在容器扫描里会被调上万次，**绝不能**每次都 astype 复制整张
    # 顶点表（20k 顶点 × 14900 次 = 十几秒全花在复制上）。
    pos64 = positions if positions.dtype == np.float64 else \
        np.asarray(positions, dtype=np.float64)
    idx = indices.astype(np.int64, copy=False)
    if idx.dtype != np.int64:
        idx = idx.astype(np.int64)
    areas = _triangle_areas(idx, pos64)
    if areas.size == 0:
        return 1.0, 1e9
    good = areas[areas > 1e-12]
    degenerate = 1.0 - good.size / float(areas.size)
    if good.size == 0:
        return 1.0, 1e9
    median = float(np.median(good))
    spread = float(good.max()) / median if median > 0 else 1e9
    return degenerate, spread


def _locate_leading_container(raw, pos_off, min_start, num_vertices):
    """索引容器紧挨在位置缓冲**前面**的那种布局。

    该游戏的干员网格（`M_*_Body_3P_HD` 之类）把索引写在顶点缓冲之前：
    ``i32 element_count`` 紧跟 ``element_count`` 个 u16，最后一个索引正好顶到
    位置缓冲的起始位置。判据只有一个等式 —— ``头部偏移 + 4 + count * 2 == pos_off``，
    再验证所有索引都小于顶点数，命中率极高（实测 M_Kai/M_Elio/Grimes 全部命中）。

    返回 ``(data_offset, element_size=2, element_count)``，找不到返回 ``None``。
    """
    if not pos_off or pos_off <= min_start:
        return None
    try:
        mv = memoryview(raw)
        lo = max(int(min_start), int(pos_off) - 12_000_000)
        span = int(pos_off) - lo
        if span < 8:
            return None
        best = None
        total = len(raw)
        # Virtual offsets include the variable-length uasset header. A u32
        # count can therefore start on ANY byte parity, even for weapon LODs.
        for shift in range(4):
            base = lo + shift
            avail = total - base
            count_words = min((span - shift) // 4, avail // 4)
            if count_words <= 0:
                continue
            words = np.frombuffer(raw, dtype="<u4", count=int(count_words),
                                  offset=base)
            offs = lo + shift + np.arange(count_words, dtype=np.int64) * 4
            for elem, dt in ((2, "<u2"), (4, "<u4")):
                remaining = int(pos_off) - offs - 4
                need = remaining // elem
                hit = np.flatnonzero((remaining % elem == 0) &
                                     (need > 0) & (need % 3 == 0) &
                                     (words.astype(np.int64) == need))
                for i in hit:
                    data_off = int(offs[i]) + 4
                    count = int(words[i])
                    if count < 3:
                        continue
                    sample = np.frombuffer(raw, dtype=dt,
                                           count=int(min(count, 512)), offset=data_off)
                    if sample.size and sample.max() >= num_vertices:
                        continue
                    tail_n = min(count, 256)
                    tail = np.frombuffer(raw, dtype=dt, count=int(tail_n),
                                         offset=data_off + (count - tail_n) * elem)
                    if tail.size and tail.max() >= num_vertices:
                        continue
                    if best is None or count > best[2]:
                        best = (data_off, elem, count)
        return best
    except Exception:                                          # noqa: BLE001
        return None


def _resolve_indices(raw, start_here, blob_end, chunk_start, chunk_end,
                     num_vertices, positions, pos_off=None, leading_only=False):
    """Pick the best index list for one skeletal LOD blob.

    Three locators are tried -- the tail anchored one (the usual layout), the
    whole chunk scan (index container stored inside the LOD header) and the
    *leading* container that sits immediately before the position buffer
    (character meshes) -- and the winner is the one that references more of the
    vertices with fewer degenerate triangles.  This rejects the truncated buffers
    that a plain tail anchor returns when a mesh has no trailing index data.

    ``leading_only``：已经确认这个资产是「索引在位置缓冲前面」的干员布局时传
    ``True``，跳过整段候选扫描（那样一个 5MB 资产要算 4 万多个候选，十几秒）。
    """
    best = None
    pos64 = positions if getattr(positions, "dtype", None) == np.float64 else         np.asarray(positions, dtype=np.float64)

    def _try(found):
        """解一个候选并算质量；好的直接返回。"""
        nonlocal best
        if found is None:
            return None
        if len(found) > 3:                 # screened list entry
            found = (found[5], found[6], found[7])
        indices = _indices_from_container(raw, found, num_vertices)
        if indices is None:
            return None
        degenerate, spread = _index_quality(indices, positions)
        referenced = np.unique(indices).size / float(num_vertices)
        good = degenerate <= 0.05 and referenced >= 0.40
        key = (not good, -referenced, degenerate, -indices.size, spread)
        if best is None or key < best[0]:
            best = (key, indices)
        return indices if (degenerate <= 0.02 and referenced >= 0.50) else None

    # 便宜的定位器先上：只有「紧挨位置缓冲之前」的容器可以当场采信 —— 它的数据
    # 末尾精确顶到位置缓冲，几乎不可能误判；尾部定位器经常给出被截断的半截缓冲，
    # 必须让它和整段扫描的结果一起比。
    hit = _try(_locate_leading_container(raw, pos_off, chunk_start, num_vertices))
    if hit is not None:
        return hit
    _try(_locate_index_buffer(raw, start_here, blob_end, num_vertices, pos64))
    if leading_only:
        return best[1] if best is not None else None
    for min_count in (3000, 300):
        for entry in _scan_container_list(raw, chunk_start, chunk_end,
                                          num_vertices, pos64,
                                          min_count=min_count):
            _try(entry)
        if best is not None and not best[0][0]:
            break
    return best[1] if best is not None else None


def _scan_containers(buf, start, end, num_vertices, positions, min_count=300):
    """Return the best self-describing index container of a chunk, or ``None``."""
    for entry in _scan_container_list(buf, start, end, num_vertices, positions,
                                      min_count):
        return entry[5], entry[6], entry[7]
    return None


def _scan_container_list(buf, start, end, num_vertices, positions,
                         min_count=300):
    """Scan a whole chunk for self-describing index containers.

    Unlike :func:`_locate_index_buffer` this does not require the data to end at
    ``end``: some cooked skeletal meshes keep the index container inside the LOD
    header (before the vertex buffers).  Candidates must pass the triangle area
    test, so random ``element_size``/``element_count`` pairs in the skin weight or
    tangent data are rejected.

    Returns the screened candidates, best first, as
    ``(bad, not_at_tail, -count, degenerate, spread, offset, element_size, count)``.
    """
    if end - start < 32 or num_vertices <= 0:
        return None
    screened = []
    # flavour 0: (element_size, element_count) -- FMultisizeIndexContainer
    # flavour 1: (0, 1, byte_size)          -- FRawStaticIndexBuffer byte bulk
    for shift in range(4):
        base = start + shift
        n = (end - base) // 4 - 2
        if n <= 1:
            continue
        arr = np.frombuffer(buf, dtype="<i4", count=n, offset=base)
        for elem_size in (2, 4):
            hits = np.nonzero(arr == elem_size)[0]
            hits = hits[hits + 1 < n]
            if hits.size:
                counts = arr[hits + 1].astype(np.int64)
                data_off = base + hits.astype(np.int64) * 4 + 8
                ok = ((counts >= min_count) & (counts % 3 == 0)
                      & (data_off + counts * elem_size <= end))
                dtype = "<u2" if elem_size == 2 else "<u4"
                ok_idx = np.nonzero(ok)[0]
                if ok_idx.size > 512:                 # biggest containers first
                    # the cap must stay well above the number of real
                    # containers: a small LOD's list (e.g. 300 indices) was
                    # crowded out by the big ones of the other LODs before the
                    # max-id / area screen could look at it, so LOD5 of
                    # M_Head_Head_Helmet_HAAVK_094_3P_HD decoded as 2 triangles.
                    ok_idx = ok_idx[np.argsort(-counts[ok_idx])[:512]]
                for i in ok_idx:
                    off = int(data_off[i])
                    count = int(counts[i])
                    head = np.frombuffer(buf, dtype=dtype,
                                         count=min(count, 3000), offset=off)
                    if head.size and int(head.max()) >= num_vertices:
                        continue
                    # 只拿前 1200 个索引估质量：容器扫描一秒要跑几千次，
                    # 全量算面积是纯浪费（最终选中的那个稍后还会全量复核）。
                    degenerate, spread = _index_quality(head[:1200], positions)
                    if degenerate > 0.05:
                        continue
                    at_tail = (off + count * elem_size) >= (end - 16)
                    screened.append((degenerate > 0.005, not at_tail, -count,
                                     degenerate, spread, off, elem_size, count))
        # flavour 1: (1, byte_size) -- FRawStaticIndexBuffer byte bulk
        zs = np.nonzero(arr == 1)[0]
        zs = zs[zs + 1 < n]
        if zs.size:
            sizes = arr[zs + 1].astype(np.int64)
            for k in range(zs.size):
                size = int(sizes[k])
                if size <= 0 or size > (end - start):
                    continue
                data_off = base + int(zs[k]) * 4 + 8
                if data_off < start or data_off + size > end:
                    continue
                for elem_size in (2, 4):
                    if size % elem_size:
                        continue
                    count = size // elem_size
                    if count % 3 or count < min_count:
                        continue
                    dtype = "<u2" if elem_size == 2 else "<u4"
                    head = np.frombuffer(buf, dtype=dtype,
                                         count=min(count, 3000), offset=data_off)
                    if head.size and int(head.max()) >= num_vertices:
                        continue
                    # 只拿前 1200 个索引估质量：容器扫描一秒要跑几千次，
                    # 全量算面积是纯浪费（最终选中的那个稍后还会全量复核）。
                    degenerate, spread = _index_quality(head[:1200], positions)
                    if degenerate > 0.05:
                        continue
                    at_tail = (data_off + size) >= (end - 16)
                    screened.append((degenerate > 0.005, not at_tail, -count,
                                     degenerate, spread, data_off, elem_size,
                                     count))
    if not screened:
        return []
    screened.sort()
    accepted = []
    for entry in screened[:16]:
        off, elem_size, count = entry[5], entry[6], entry[7]
        dtype = "<u2" if elem_size == 2 else "<u4"
        arr = np.frombuffer(buf, dtype=dtype, count=count, offset=off)
        if int(arr.max()) >= num_vertices:
            continue
        degenerate, spread = _index_quality(arr, positions)
        if degenerate > 0.05:
            continue
        accepted.append((entry[0], entry[1], entry[2], degenerate, spread, off,
                         elem_size, count))
    return accepted


def _locate_index_buffer(buf, start, end, num_vertices, positions):
    """Find the index container that is anchored at the end of a LOD blob.

    In a cooked LOD the index buffer is the last thing serialised, so its header
    can be pinned down exactly: the bulk header is ``element_size``/``element_count``
    followed by ``element_count * element_size`` bytes that stop at ``end``.
    Two flavours exist:

    * ``FMultisizeIndexContainer`` -- one byte ``DataSize`` (2 or 4), then the
      bulk header whose ``element_size`` repeats ``DataSize``;
    * ``FRawStaticIndexBuffer``   -- ``is32bit`` bool plus a ``byte`` bulk array,
      so ``element_size`` is 1 and ``element_count`` is the *byte* count.

    Returns ``(data_offset, element_size, element_count)`` or ``None``.
    """
    span = end - start
    if span < 16 or num_vertices <= 0:
        return None
    found = []
    tails = [end]
    for delta in (1, 2, 3, 4, 6, 8):
        tails.append(end - delta)
    for delta in (2, 4, 6):
        tails.append(end + delta)
    for tail in tails:
        if tail > len(buf):
            continue
        if tail - start < 16:
            continue
        for shift in range(4):
            base = start + shift
            n = (tail - base) // 4 - 1
            if n <= 0:
                continue
            arr = np.frombuffer(buf, dtype="<i4", count=n, offset=base)
            for elem_size in (1, 2, 4):
                hits = np.nonzero(arr == elem_size)[0]
                if hits.size == 0:
                    continue
                hits = hits[hits + 1 < n]
                if hits.size == 0:
                    continue
                data_off = base + hits * 4 + 8
                remaining = tail - data_off
                usable = (remaining > 0) & (remaining % elem_size == 0)
                if not usable.any():
                    continue
                counts = np.where(usable, remaining // elem_size, -1)
                ok = usable & (arr[hits + 1] == counts)
                if not ok.any():
                    continue
                for i in np.nonzero(ok)[0]:
                    header_off = int(base + hits[i] * 4)
                    data_off = header_off + 8
                    count = int(counts[i])
                    if count < 3:
                        continue
                    flavour = 0
                    if header_off - 1 >= start and buf[header_off - 1] in (2, 4):
                        flavour = 1 if buf[header_off - 1] == elem_size else 0
                    found.append((data_off, elem_size, count, flavour))
    if not found:
        return None
    # Prefer a real FMultisizeIndexContainer header, then the largest buffer.
    quality = []
    for off, elem_size, count, flavour in found:
        dtype = "<u2" if elem_size == 2 else ("<u4" if elem_size == 4 else np.uint8)
        take = count if elem_size != 1 else count // 2
        if take < 3:
            continue
        arr = np.frombuffer(buf, dtype=dtype, count=min(take, 3000), offset=off)
        if arr.size % 3:                   # keep whole triangles only
            arr = arr[: arr.size - arr.size % 3]
        if arr.size < 3:
            continue
        if arr.size and int(arr.max()) >= num_vertices:
            continue
        degenerate, spread = _index_quality(arr, positions)
        quality.append((degenerate > 0.0005, -flavour, degenerate, -take, spread,
                        off, elem_size, count))
    if not quality:
        return None
    quality.sort()
    _bad, _fl, _deg, _neg, _spread, off, elem_size, count = quality[0]
    if elem_size == 1:                     # byte bulk -> u16 indices
        return off, 2, count // 2
    return off, elem_size, count


def _indices_from_container(buf, found, num_vertices):
    """Decode the indices of a located container, or ``None`` when out of range."""
    off, elem_size, count = found
    dtype = "<u2" if elem_size == 2 else "<u4"
    arr = np.frombuffer(buf, dtype=dtype, count=count, offset=off)
    arr = arr[: arr.size - arr.size % 3]
    if arr.size < 3 or int(arr.max()) >= num_vertices:
        return None
    return arr.astype(np.uint32)


def _find_indices(raw, tail_start, tail_end, num_vertices, need, positions):
    """Locate the ``need``-long index run that follows the vertex buffers.

    The tail of a LOD blob may contain a colour buffer and up to four index
    buffers (index / reversed / depth-only / reversed depth-only), each with its
    own header, so the data offset is not fixed.  Every maximal run of values
    below ``num_vertices`` is a candidate; for each one a few shifted starts are
    tried as well (the run start often lands inside the preceding header).  The
    best candidate is the longest one whose triangles are all non degenerate --
    a header offset or a wrong width turns the triangles into slivers, which the
    area test rejects.
    """
    if need <= 0 or tail_end <= tail_start:
        return None
    return _choose_indices(raw, tail_start, tail_end, num_vertices, positions, need)


def _index_candidates(raw, start, end, num_vertices, max_shift=24, min_len=300):
    """Yield ``(data_offset, element_size, element_count)`` index candidates."""
    out = []
    for dtype, size in (("<u2", 2), ("<u4", 4)):
        for align in range(size):
            off = start + align
            count = (end - off) // size
            if count < min_len:
                continue
            win = np.frombuffer(raw, dtype=dtype, count=count, offset=off)
            valid = win < num_vertices
            if not valid.any():
                continue
            edges = np.diff(np.concatenate(([0], valid.astype(np.int8), [0])))
            starts = np.nonzero(edges == 1)[0]
            stops = np.nonzero(edges == -1)[0]
            for a, b in zip(starts, stops):
                length = int(b - a)
                if length < min_len:
                    continue
                for shift in range(0, min(max_shift, length - min_len) + 1):
                    count_here = ((length - shift) // 3) * 3
                    if count_here < min_len:
                        continue
                    out.append((off + (int(a) + shift) * size, size, count_here))
    return out


def _choose_indices(raw, start, end, num_vertices, positions, need=None):
    """Pick the most plausible index run in ``[start, end)``.

    ``need`` (when known) is used as the exact element count; otherwise the whole
    run is taken.  Ranking: non degenerate first, then the longest run, then the
    tightest triangle area distribution -- so a header shifted start never wins
    over the real buffer, and the real buffer never loses against its own
    truncated suffix.
    """
    candidates = _index_candidates(raw, start, end, num_vertices)
    if not candidates:
        return None
    if need:
        fitting = [c for c in candidates if c[2] >= need]
        candidates = fitting or candidates
    screen = []
    for off, size, count in candidates:
        take = need if (need and count >= need) else count
        arr = np.frombuffer(raw, dtype=("<u2" if size == 2 else "<u4"),
                            count=min(take, 3000), offset=off)
        degenerate, spread = _index_quality(arr, positions)
        screen.append((degenerate > 0.0005, -take, spread, off, size, take))
    screen.sort()
    best = None
    for _bad, _neg, _spread, off, size, take in screen[:20]:
        arr = np.frombuffer(raw, dtype=("<u2" if size == 2 else "<u4"),
                            count=take, offset=off)
        degenerate, spread = _index_quality(arr, positions)
        key = (degenerate > 0.0005, -take, spread)
        if best is None or key < best[0]:
            best = (key, arr)
    return best[1].astype(np.uint32) if best is not None else None


def _decode_packed(raw):
    """FPackedNormal (4 signed bytes) -> normalized float32 (N, 3).

    Measured encoding: 127 == +1.0, 0 == 0.0, 129 == -1.0, i.e. plain
    ``int8 / 127``.  The 4th byte of a tangent half carries the bitangent sign
    (127 == +1, 128..255 == -1) and is unused for the normal half.
    """
    signed = raw if raw.dtype.itemsize == 2 else raw.astype(np.int8)
    v = signed.astype(np.float32) / (32767.0 if signed.dtype.itemsize == 2 else 127.0)
    xyz = v[:, :3]
    norm = np.linalg.norm(xyz, axis=1, keepdims=True)
    norm[norm < 1e-6] = 1.0
    return xyz / norm


def _unpack_normal(raw):
    """FPackedNormal (4 bytes) -> float32 (N, 3) unit normals."""
    return _decode_packed(raw)


def _pack_tangent(raw_x, normals):
    """8-bit tangent basis -> float32 (N, 4) with the bitangent sign in w."""
    tx = _decode_packed(raw_x)
    out = np.empty((tx.shape[0], 4), dtype=np.float32)
    out[:, :3] = tx
    sign = raw_x[:, 3] if raw_x.dtype.itemsize == 2 else raw_x[:, 3].astype(np.int8)
    out[:, 3] = np.where(sign < 0, -1.0, 1.0)
    return out


# --------------------------------------------------------------------------- #
# bounds
# --------------------------------------------------------------------------- #
def _bounds(props, lods):
    ext = props.get("ExtendedBounds") if isinstance(props, dict) else None
    if isinstance(ext, dict) and "Origin" in ext and "BoxExtent" in ext:
        origin = np.asarray(ext["Origin"], dtype=np.float32)
        extent = np.asarray(ext["BoxExtent"], dtype=np.float32)
        center = ue_to_gl(origin.reshape(1, 3))[0]
        ext_gl = ue_to_gl(extent.reshape(1, 3))[0]
        return center.astype(np.float32), np.abs(ext_gl).astype(np.float32)
    lod = lods[0]
    if lod.positions.size:
        lo = lod.positions.min(axis=0)
        hi = lod.positions.max(axis=0)
        return ((lo + hi) * 0.5).astype(np.float32), ((hi - lo) * 0.5).astype(np.float32)
    return np.zeros(3, np.float32), np.zeros(3, np.float32)


# --------------------------------------------------------------------------- #
# skeletal meshes (best effort)
# --------------------------------------------------------------------------- #
def _find_position_headers(buf, start, end):
    """Locate every ``FPositionVertexBuffer`` header inside ``[start, end)``."""
    mv = memoryview(buf)
    hits = []
    pat = b"\x0c\x00\x00\x00"
    for i in range(start, max(start, end - 16)):
        if buf[i:i + 4] != pat:
            continue
        num = struct.unpack_from("<i", mv, i + 4)[0]
        num2 = struct.unpack_from("<i", mv, i + 12)[0]
        if num != num2 or num < 32 or num > 4_000_000:
            continue
        if i + 16 + num * POS_STRIDE > end:
            continue
        hits.append((i, num))
    return hits


def _find_index_run(raw, start, end, num_vertices, positions):
    """Locate an index buffer without knowing its triangle count.

    Skeletal meshes do not carry ``FStaticMeshSection`` records, so the number of
    indices is unknown: the whole run is taken.  See :func:`_choose_indices`.
    """
    if end <= start or num_vertices <= 0:
        return None
    return _choose_indices(raw, start, end, num_vertices, positions)


def _load_skeletal(pkg, export, pak_path):
    """Decode the cooked (bind pose) LOD render data of a ``USkeletalMesh``.

    Game inlines the buffers in the export payload: for every LOD a
    ``FPositionVertexBuffer`` header, the static vertex buffers (tangents, uvs),
    the skin weight buffer and finally an index list.  The vertex data is already
    in component space, so it can be rendered without touching the skeleton.
    """
    r = pkg.export_reader(export)
    props = {}
    prop_start = r.pos
    try:
        props = pkg.read_properties(r)
    except Exception:                  # noqa: BLE001 - properties are optional
        props = {}
        r.pos = prop_start
    del prop_start
    from .skeletal import decode, SkeletalLayoutError
    try:
        return decode(pkg, export, props, r.pos)
    except (SkeletalLayoutError, ValueError, IndexError, struct.error):
        # Other cooked layouts retain the existing bounded buffer parser.
        pass
    materials = _material_paths(pkg, props)

    buf = pkg.virtual()
    start = export.serial_offset
    end = min(export.serial_offset + export.serial_size, len(buf))
    heads = _find_position_headers(buf, start, end)
    if not heads:
        raise MeshError("no position buffers in skeletal export %s" % pak_path)

    blobs = []
    for i, (pos_off, _num) in enumerate(heads):
        blob_start = pos_off - 2 if pos_off >= 2 else pos_off
        blob_end = heads[i + 1][0] if i + 1 < len(heads) else end
        try:
            blobs.append(_parse_blob(buf, blob_start, blob_end, pos_off))
        except Exception:              # noqa: BLE001
            blobs.append(None)
    blobs = [b for b in blobs if b is not None]
    if not blobs:
        raise MeshError("no decodable skeletal LOD in %s" % pak_path)

    # 干员/角色网格的索引容器紧挨在位置缓冲之前；这种布局下导出体里没有
    # `FStaticMeshSection` 表，整段扫描纯属浪费（5MB 要扫好几秒，模型一直转圈）。
    # 先确认是不是这种布局，是就跳过 section 扫描。
    char_layout = _locate_leading_container(buf, blobs[0].get("pos_off"),
                                            start, blobs[0]["num_vertices"])
    if char_layout is not None:
        section_lods = []
    else:
        section_lods = _scan_lod_sections(buf, start, end,
                                          [b["num_vertices"] for b in blobs])
    lods = []
    for i, blob in enumerate(blobs):
        num_vertices = blob["num_vertices"]
        positions = blob["positions"]
        secs = section_lods[i] if i < len(section_lods) else None
        start_here = max(blob.get("blob_start", 0), blob["index_offset"] - 64)
        candidates = []
        found = _resolve_indices(blob["raw"], start_here, blob["blob_end"],
                                 start, end, num_vertices, positions,
                                 pos_off=blob.get("pos_off"),
                                 leading_only=char_layout is not None)
        if found is not None:
            candidates.append(found)
        # 2) the section records pin the triangle count down exactly
        if secs:
            need = sum(s.num_triangles for s in secs) * 3
            found = _find_indices(blob["raw"], blob["index_offset"],
                                  blob["blob_end"], num_vertices, need, positions)
            if found is not None:
                candidates.append(found)
        # 3) any plausible run of small integers (the buffer may be longer than
        #    what an incomplete section record claims)
        if char_layout is None:
            found = _find_index_run(blob["raw"], blob["index_offset"],
                                    blob["blob_end"], num_vertices, positions)
            if found is not None:
                candidates.append(found)
        indices = None
        best_key = None
        for cand in candidates:
            degenerate, _spread = _index_quality(cand, positions)
            referenced = np.unique(cand).size / float(num_vertices)
            key = (degenerate > 0.05, -referenced, -int(cand.size))
            if best_key is None or key < best_key:
                best_key, indices = key, cand
        if indices is None or indices.size < 3:
            continue
        degenerate, _spread = _index_quality(indices, positions)
        if degenerate > 0.01:
            # every candidate of this LOD is noise: the buffer was cooked out
            continue
        if secs and sum(s.num_triangles for s in secs) * 3 == indices.size:
            lod = _assemble_lod(blob, indices, _sections_from(secs, materials))
        else:
            lod = _assemble_lod(blob, indices, [Section(
                material_path=materials[0] if materials else None,
                first_index=0,
                num_triangles=int(indices.size // 3),
                first_vertex=0,
                num_vertices=num_vertices,
            )])
        if lod is not None:
            lods.append(lod)
    if not lods:
        raise MeshError("no skeletal LOD with indices in %s" % pak_path)

    center, extent = _bounds(props, lods)
    return Mesh(
        name=export.name or _asset_name(pak_path),
        pak_path=pak_path,
        lods=lods,
        bounds_center=center,
        bounds_extent=extent,
        source_format="UE5.0/DF-skeletal",
    )


def _sections_from(secs, materials):
    out = []
    for s in secs:
        material_path = None
        if 0 <= s.material_index < len(materials):
            material_path = materials[s.material_index]
        out.append(Section(
            material_path=material_path,
            first_index=s.first_index,
            num_triangles=s.num_triangles,
            first_vertex=s.min_vertex,
            num_vertices=max(0, s.max_vertex - s.min_vertex + 1),
        ))
    return out


def _assemble_lod(blob, indices, sections):
    """Turn decoded buffers plus an index list into a :class:`MeshLOD`."""
    num_vertices = blob["num_vertices"]
    normals = None
    tangents = None
    if blob["tangents"] is not None:
        raw = blob["tangents"].reshape(num_vertices, -1)
        if raw.shape[1] == 16:
            packed_z = np.ascontiguousarray(raw[:, 8:16]).view('<i2')
            packed_x = np.ascontiguousarray(raw[:, :8]).view('<i2')
            normals = ue_dir_to_gl(_unpack_normal(packed_z)).astype(np.float32)
            tangents = _pack_tangent(packed_x, normals)
            tangents[:, :3] = ue_dir_to_gl(tangents[:, :3])
        elif raw.shape[1] >= 8:
            normals = ue_dir_to_gl(_unpack_normal(raw[:, 4:8])).astype(np.float32)
            tangents = _pack_tangent(raw[:, 0:4], normals)
            tangents[:, :3] = ue_dir_to_gl(tangents[:, :3])
        elif raw.shape[1] >= 4:
            normals = ue_dir_to_gl(_unpack_normal(raw[:, 0:4])).astype(np.float32)

    uvs = None
    uv_sets = None
    if blob["uvs"] is not None:
        num_texcoords = blob["num_texcoords"]
        flat = blob["uvs"].reshape(-1)
        need = num_vertices * num_texcoords * 2
        # UE 的顶点缓冲两种排布都出现过：默认是「逐顶点连续 UV0,UV1…」
        # （FStaticMeshVertexBuffer 的 UVs 就是这种）；只有一种情况例外 ——
        # 顶点数为奇数且 UV 通道数为奇数时 UE 会补一个空顶点，此时数组长度是
        # (n + 顶点数%2)*tc。长度对得上就按逐顶点切片，对不上就先截断。
        if flat.size >= need:
            table = flat[:need].reshape(num_vertices, num_texcoords, 2)
        else:                                  # 兼容旧口径的 (n*tc, 2) 平铺
            table = flat.reshape(-1, 2)[: num_vertices * num_texcoords]
            table = table.reshape(num_vertices, num_texcoords, 2)
        uv_sets = np.ascontiguousarray(table, dtype=np.float32)
        uvs = uv_sets[:, 0, :]
        blob["uv_channels"] = num_texcoords
        blob["uv_padded"] = flat.size > need

    gl_positions = ue_to_gl(blob["positions"])
    lod = MeshLOD(
        positions=gl_positions.astype(np.float32),
        normals=normals,
        uvs=uvs,
        tangents=tangents,
        indices=indices,
        sections=sections,
        uv_sets=uv_sets,
    )
    # 诊断用：这套几何到底带几套 UV（导出/排查时能一眼看出通道选没选错）
    try:
        lod.uv_channels = int(blob.get("uv_channels", 1) or 1)
    except Exception:                                          # noqa: BLE001
        lod.uv_channels = 1
    return lod
