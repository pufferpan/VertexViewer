"""Read DF's cooked skeletal materials and LOD sections in serialization order.

Layout cross-checked against CUE4Parse's USkeletalMesh/FSkelMeshSection and
the actual game assets. DF adds three bytes after the tangent-mask channel;
sections also contain variable-length duplicate-vertex buffers.
"""
from __future__ import annotations

import struct
import numpy as np
from .types import Mesh, Section, ue_to_gl


class SkeletalLayoutError(ValueError):
    pass


class Reader:
    def __init__(self, data, start, end):
        self.data, self.pos, self.end = data, start, end

    def skip(self, size):
        if size < 0 or self.pos + size > self.end:
            raise SkeletalLayoutError('skeletal field exceeds export')
        self.pos += size

    def read(self, fmt):
        size = struct.calcsize(fmt)
        self.skip(size)
        return struct.unpack_from(fmt, self.data, self.pos-size)

    def int(self):
        return self.read('<i')[0]

    def boolean(self):
        value = self.int()
        if value not in (0, 1):
            raise SkeletalLayoutError('invalid skeletal boolean')
        return bool(value)

    def count(self, limit):
        value = self.int()
        if not 0 <= value <= limit:
            raise SkeletalLayoutError('invalid skeletal array length')
        return value

    def array(self, stride, limit):
        count = self.count(limit)
        self.skip(count*stride)
        return count

    def name(self, names):
        index, number = self.read('<ii')
        if not 0 <= index < len(names) or not 0 <= number < 100000:
            raise SkeletalLayoutError('invalid skeletal slot/bone name')
        return names[index] + ('_%d' % (number-1) if number else '')


def _section(r):
    _, class_flags = r.read('<BB')
    material = r.read('<h')[0]
    base, triangles = r.read('<ii')
    r.boolean()                      # recompute tangent
    r.skip(4)                        # mask channel + DF's three extra bytes
    r.boolean()                      # casts shadow (this build has no RT bool)
    vertex = r.int()
    r.array(64, 2_000_000)            # cloth mapping, not vertex positions
    bone_count = r.count(4096)
    bone_map = np.frombuffer(r.data, '<u2', bone_count, r.pos).copy()
    r.skip(bone_count * 2)            # local-to-skeleton bone map
    vertices, influences = r.read('<ii')
    if material < 0 or min(base, triangles, vertex, vertices) < 0 or base % 3:
        raise SkeletalLayoutError('invalid skeletal section range')
    if not 0 <= influences <= 16:
        raise SkeletalLayoutError('invalid skeletal bone influence count')
    r.skip(22)                       # cloth asset index, GUID and LOD
    if not class_flags & 1:
        r.array(4, 20_000_000)        # duplicated vertices
        r.array(8, 20_000_000)        # duplicate ranges
    disabled = r.boolean()
    return material, base, triangles, vertex, vertices, disabled, bone_map


def _skin_weights(raw, start, end, vertices, sections, bone_count):
    """DF UE4.27 fixed influence buffer, in native serialization order."""
    r = Reader(raw, start, end)
    r.skip(2)                       # FStripDataFlags
    extra = r.boolean()
    stride, count = r.read('<II')
    influences = 8 if extra else 4
    size, bulk_count = r.read('<ii')
    if count != vertices or bulk_count != vertices or stride != influences * 2 or size != stride:
        raise SkeletalLayoutError('unsupported skin weight buffer layout')
    r.skip(size * count)
    values = np.frombuffer(raw, np.uint8, size * count, r.pos-size*count).reshape(count, size)
    local = values[:, :influences]
    weights = values[:, influences:].astype(np.float32) / 255.0
    indices = np.zeros((count, influences), np.uint16)
    for _, _, _, first, length, _, mapping in sections:
        active = weights[first:first+length] > 0
        section_indices = local[first:first+length]
        if (section_indices[active] >= len(mapping)).any() or (mapping >= bone_count).any():
            raise SkeletalLayoutError('skin weight bone map out of range')
        safe = np.where(active, section_indices, 0)
        if len(mapping): indices[first:first+length] = mapping[safe]
    totals = weights.sum(axis=1, keepdims=True)
    if (totals < 0.9).any() or (totals > 1.1).any():
        raise SkeletalLayoutError('skin weight totals invalid')
    return indices, weights / totals


def decode(pkg, export, props, native_start):
    from .mesh import _parse_blob, _assemble_lod, _to_asset_path
    raw = pkg.virtual()
    r = Reader(raw, native_start, min(len(raw), export.serial_offset+export.serial_size))
    if r.boolean():                  # UObject's optional GUID
        r.skip(16)
    r.skip(2)                        # FStripDataFlags
    bounds = r.read('<7f')
    if not np.isfinite(bounds).all() or min(bounds[3:]) < 0:
        raise SkeletalLayoutError('invalid skeletal bounds')
    materials = []
    for slot in range(r.count(256)):
        ref = r.int()
        r.name(pkg.names)
        if r.boolean():
            r.name(pkg.names)
        r.boolean()                  # UV densities initialized
        r.boolean()                  # UV densities overridden
        r.skip(16)
        path = _to_asset_path(pkg.object_path(ref), pkg) if ref else ''
        materials.append(path or f'vertexviewer://missing-skeletal-material/{slot}')
    if not materials:
        raise SkeletalLayoutError('skeletal asset has no material slots')
    bones, parents = [], []
    for index in range(r.count(4096)):
        bones.append(r.name(pkg.names))
        parent = r.int()
        parents.append(parent)
        if not -1 <= parent < index:
            raise SkeletalLayoutError('invalid reference-bone parent')
    pose_count = r.count(4096)
    if pose_count != len(bones):
        raise SkeletalLayoutError('reference pose count mismatch')
    poses = np.frombuffer(raw, '<f4', pose_count*10, r.pos).reshape(pose_count, 10).copy()
    r.skip(pose_count * 40)
    r.array(12, 4096)                 # bone-name/index map
    if not r.boolean():
        raise SkeletalLayoutError('editor-only skeletal asset')
    lod_count = r.count(32)
    if not lod_count:
        raise SkeletalLayoutError('skeletal asset has no LODs')
    lods = []
    lod_info = props.get('LODInfo', [])
    for level in range(lod_count):
        flags, _ = r.read('<BB')
        cooked_out, inlined = r.boolean(), r.boolean()
        r.array(2, 4096)              # required bones
        if cooked_out or flags & 2:
            continue
        sections = [_section(r) for _ in range(r.count(256))]
        if not sections:
            raise SkeletalLayoutError('skeletal LOD has no sections')
        r.array(2, 4096)              # active bones
        buffer_size = r.count(r.end-r.pos)
        stream_start = r.pos
        r.skip(buffer_size)
        stream_end = r.pos
        if not inlined:
            raise SkeletalLayoutError('external skeletal stream is not inline')
        s = Reader(raw, stream_start, stream_end)
        s.skip(2)
        element = s.read('<B')[0]
        stride = s.int()
        if element not in (2, 4) or stride != element:
            raise SkeletalLayoutError('invalid skeletal index width')
        count = s.count(30_000_000)
        if not count or count % 3:
            raise SkeletalLayoutError('invalid skeletal triangle count')
        offset = s.pos
        s.skip(count*element)
        indices = np.frombuffer(raw, dtype='<u2' if element == 2 else '<u4',
                                count=count, offset=offset).astype(np.uint32)
        blob = _parse_blob(raw, stream_start, stream_end, s.pos)
        vertices = blob['num_vertices']
        if indices.max() >= vertices or not np.isfinite(blob['positions']).all():
            raise SkeletalLayoutError('skeletal indices/positions out of range')
        if blob['uvs'] is None or blob['tangents'] is None:
            raise SkeletalLayoutError('skeletal vertex attributes unavailable')
        info = lod_info[level] if level < len(lod_info) else {}
        mapping = info.get('LODInfo', info).get('LODMaterialMap', [])
        draws = []
        previous = 0
        for number, (material, base, triangles, vertex, num_vertices, disabled, _bone_map) in enumerate(sections):
            if base != previous or base+triangles*3 > count or vertex+num_vertices > vertices:
                raise SkeletalLayoutError('skeletal sections do not cover their buffers')
            local = indices[base:base+triangles*3]
            if local.size and (local.min() < vertex or local.max() >= vertex+num_vertices):
                raise SkeletalLayoutError('skeletal section references another section')
            previous = base+triangles*3
            if number < len(mapping) and 0 <= mapping[number] < len(materials):
                material = mapping[number]
            if material >= len(materials):
                raise SkeletalLayoutError('skeletal material slot out of range')
            if not disabled and triangles:
                draws.append(Section(material_path=materials[material], first_index=base,
                                     num_triangles=triangles, first_vertex=vertex,
                                     num_vertices=num_vertices))
        if previous != count:
            raise SkeletalLayoutError('incomplete skeletal section coverage')
        lod = _assemble_lod(blob, indices, draws)
        lod.bones = list(bones)
        # Unsupported optional animation data never changes the static mesh parser.
        try:
            lod.bone_indices, lod.bone_weights = _skin_weights(
                raw, blob['index_offset'], stream_end, vertices, sections, len(bones))
        except SkeletalLayoutError:
            pass
        lods.append(lod)
    if not lods:
        raise SkeletalLayoutError('no resident skeletal LODs')
    center = ue_to_gl(np.asarray([bounds[:3]], np.float32))[0]
    extent = np.abs(ue_to_gl(np.asarray([bounds[3:6]], np.float32))[0])
    return Mesh(name=export.name, pak_path=pkg.path, lods=lods,
                material_paths=materials, bounds_center=tuple(center),
                bounds_extent=tuple(extent), source_format='UE/DF-skeletal-sections',
                bone_parents=parents, reference_pose=poses)
