"""UE5 package (.uasset/.uexp) reader for Game (GAME_DeltaForce).

Empirically verified against real packages pulled from the game paks.

Summary layout for this game build (measured on
``Models/Weapons/Parts/Mag/Mag_AK74_545x39-30R-Std_004/SM_..._3P.uasset``):

    u32   tag                0x9E2A83C1
    i32   legacy_file_version  raw -4613 == -7 * 659  ->  "real" value -7
    i32   legacy_ue3_version   (present when legacy != -4)
    i32   file_version_ue4     522
    i32   file_version_ue5     (only when legacy <= -8; absent here -> 0)
    i32   licensee_version     1
    ...   custom versions       i32 count + count * (guid[16] + i32 version)
    i32   total_header_size    == len(.uasset)
    fstr  folder_name          "None"
    u32   package_flags        0x80000000 (PKG_FilterEditorOnly)
    ...

``.uexp`` is a *payload* attached at the virtual offset ``len(.uasset)``: an
export's ``serial_offset`` is an offset into the concatenation
``uasset_bytes + uexp_bytes`` (verified: export0 offset 2345 == uasset size,
size 613; export1 offset 2958 == 2345 + 613).

This module only parses structure; geometry lives in :mod:`core.mesh`.
"""

from __future__ import annotations

import struct

MAGIC = 0x9E2A83C1
MAGIC_SWAPPED = 0xC1832A9E

# EPackageFlags
PKG_FILTER_EDITOR_ONLY = 0x80000000


# --------------------------------------------------------------------------- #
# low level reader
# --------------------------------------------------------------------------- #
class Reader:
    """Cursor over an immutable byte buffer (memoryview based, zero copy)."""

    __slots__ = ("buf", "pos", "names", "package", "end")

    def __init__(self, buf, pos=0, names=None, package=None, end=None):
        self.buf = memoryview(buf).cast("B")
        self.pos = pos
        self.names = names or []
        self.package = package
        self.end = len(self.buf) if end is None else end

    # -- primitives ------------------------------------------------------- #
    def _un(self, fmt, size):
        v = struct.unpack_from(fmt, self.buf, self.pos)[0]
        self.pos += size
        return v

    def u8(self):
        v = self.buf[self.pos]
        self.pos += 1
        return v

    def i8(self):
        return self._un("<b", 1)

    def u16(self):
        return self._un("<H", 2)

    def i16(self):
        return self._un("<h", 2)

    def u32(self):
        return self._un("<I", 4)

    def i32(self):
        return self._un("<i", 4)

    def u64(self):
        return self._un("<Q", 8)

    def i64(self):
        return self._un("<q", 8)

    def f32(self):
        return self._un("<f", 4)

    def f64(self):
        return self._un("<d", 8)

    def boolean(self):
        return self.u8() != 0

    def guid(self):
        raw = self.take(16)
        return raw.hex()

    def take(self, n):
        if self.pos + n > self.end:
            raise UnexpectedEnd(self.pos, n, self.end)
        out = self.buf[self.pos:self.pos + n]
        self.pos += n
        return out.tobytes()

    def skip(self, n):
        self.pos += n
        if self.pos > self.end:
            raise UnexpectedEnd(self.pos - n, n, self.end)

    def seek(self, pos):
        self.pos = pos

    # -- strings ---------------------------------------------------------- #
    def fstring(self):
        n = self.i32()
        if n == 0:
            return ""
        if n > 0:
            if n > 4096:                      # garbage guard
                raise ValueError("implausible string length %d @%#x" % (n, self.pos - 4))
            data = self.take(n)
            return data.split(b"\x00", 1)[0].decode("latin-1")
        n = -n
        if n > 4096:
            raise ValueError("implausible wide string length %d @%#x" % (n, self.pos - 4))
        data = self.take(2 * n)
        return data.decode("utf-16-le", "replace").split("\x00", 1)[0]

    def fname(self):
        idx = self.i32()
        num = self.i32()
        return self.name_at(idx, num)

    def name_at(self, idx, num=0):
        if idx < 0:                            # hard coded name
            base = HARDCODED.get(idx, "None" if idx == 0 else "Name_%d" % idx)
        elif idx < len(self.names):
            base = self.names[idx]
        else:
            base = "Name_%d" % idx
        if num > 0:
            return "%s_%d" % (base, num - 1)
        return base

    # -- containers ------------------------------------------------------- #
    def raw_array(self, count, stride):
        return self.take(count * stride)

    def count_array(self, fn):
        n = self.i32()
        if n < 0:
            raise ValueError("negative array count %d @%#x" % (n, self.pos - 4))
        return [fn() for _ in range(n)]


class UnexpectedEnd(Exception):
    def __init__(self, pos, want, end):
        super().__init__("read %d bytes at %#x past end %#x" % (want, pos, end))


# FName hard coded indices (only the ones that matter in practice).
HARDCODED = {0: "None", 1: "ByteProperty", 2: "IntProperty", 3: "BoolProperty",
             4: "FloatProperty", 5: "ObjectProperty", 6: "NameProperty",
             7: "StructProperty", 8: "ArrayProperty", 9: "MapProperty"}

# Game packages write legacy_file_version scaled by this constant.
_DF_LEGACY = 659

# Structs that serialize as raw POD blobs instead of tagged property lists.
RAW_STRUCTS = frozenset({
    "Vector", "Vector2D", "Vector4", "Vector_NetQuantize", "Vector_NetQuantize10",
    "Vector_NetQuantize100", "Vector_NetQuantizeNormal", "Rotator", "Quat", "Plane",
    "Matrix", "Transform", "LinearColor", "Color", "Guid", "DateTime", "Timespan",
    "IntPoint", "IntVector", "FloatRange", "Int32Range", "Box", "Box2D", "Sphere",
})


# --------------------------------------------------------------------------- #
# tables
# --------------------------------------------------------------------------- #
class CustomVersion(tuple):
    @property
    def guid(self):
        return self[0]

    @property
    def version(self):
        return self[1]


class Export:
    """FObjectExport (prefix fields; the tail is skipped by stride)."""

    __slots__ = ("index", "class_index", "super_index", "template_index",
                 "outer_index", "name", "object_flags", "serial_size",
                 "serial_offset", "raw_offset")

    def __init__(self, index, r):
        self.index = index
        self.class_index = r.i32()
        self.super_index = r.i32()
        self.template_index = r.i32()
        self.outer_index = r.i32()
        self.name = r.fname()
        self.object_flags = r.u32()
        self.serial_size = r.i64()
        self.serial_offset = r.i64()
        self.raw_offset = r.pos

    def __repr__(self):
        return "<Export %d %r size=%d off=%d>" % (
            self.index, self.name, self.serial_size, self.serial_offset)


class Import:
    __slots__ = ("index", "class_package", "class_name", "outer_index", "name")

    def __init__(self, index, r):
        self.index = index
        self.class_package = r.fname()
        self.class_name = r.fname()
        self.outer_index = r.i32()
        self.name = r.fname()

    def __repr__(self):
        return "<Import %d %r class=%r>" % (self.index, self.name, self.class_name)


# --------------------------------------------------------------------------- #
# package
# --------------------------------------------------------------------------- #
class Package:
    """Parsed .uasset (+ .uexp/.ubulk payload) package."""

    def __init__(self, uasset: bytes, uexp: bytes | None = None, ubulk: bytes | None = None,
                 path: str = "", verbose: bool = False):
        self.path = path
        self.uasset = bytes(uasset)
        self.uexp = bytes(uexp) if uexp else b""
        self.ubulk = bytes(ubulk) if ubulk else b""
        self.uasset_len = len(self.uasset)
        self.custom_versions = {}
        self.names = []
        self.imports = []
        self.exports = []
        self._parse_summary()
        self._parse_names()
        self._parse_imports()
        self._parse_exports()
        if self.folder_name in ("", "None"):
            self.folder_name = "None"

    # -- summary ---------------------------------------------------------- #
    def _parse_summary(self):
        r = Reader(self.uasset)
        self.tag = r.u32()
        if self.tag not in (MAGIC, MAGIC_SWAPPED):
            raise ValueError("bad uasset magic %#x in %r" % (self.tag, self.path))
        raw_legacy = r.i32()
        self.legacy_file_version_raw = raw_legacy
        legacy = raw_legacy
        if legacy < 0 and legacy % _DF_LEGACY == 0:
            legacy //= _DF_LEGACY                    # DeltaForce: legacy *= 659
        self.legacy_file_version = legacy
        if legacy != -4:
            self.ue3_version = r.i32()
        else:
            self.ue3_version = 0
        self.ue4_version = r.i32()
        if legacy <= -8:
            self.ue5_version = r.i32()
        else:
            self.ue5_version = 0
        self.licensee_version = r.i32()

        # Custom versions (format from legacy_file_version: guids for <= -3).
        if legacy <= -3:
            n = r.i32()
            if not (0 <= n <= 256):
                raise ValueError("implausible custom version count %d @%#x" % (n, r.pos - 4))
            for _ in range(n):
                g = r.guid()
                self.custom_versions[g] = r.i32()
            self.custom_version_count = n
        else:
            self.custom_version_count = 0

        # SavedHash + TotalHeaderSize only for very new versions.
        self.total_header_size = r.i32()
        self.folder_name = r.fstring()
        self.package_flags = r.u32()
        self.name_count = r.i32()
        self.name_offset = r.i32()
        self.gatherable_text_data_count = r.i32()
        self.gatherable_text_data_offset = r.i32()
        self.export_count = r.i32()
        self.export_offset = r.i32()
        self.import_count = r.i32()
        self.import_offset = r.i32()
        self.depends_offset = r.i32()
        self.soft_package_references_count = r.i32()
        self.soft_package_references_offset = r.i32()
        self.searchable_names_offset = r.i32()
        self.thumbnail_table_offset = r.i32()
        self.import_type_hierarchies_count = r.i32()
        self.import_type_hierarchies_offset = r.i32()
        self.guid = r.guid()
        self.generations = r.count_array(lambda: (r.i32(), r.i32()))
        r.i16(), r.i16(), r.i16(), r.u32(), r.fstring()       # SavedByEngineVersion
        r.i16(), r.i16(), r.i16(), r.u32(), r.fstring()       # CompatibleWithEngineVersion
        self.compression_flags = r.u32()
        self.compressed_chunks = r.count_array(lambda: None)
        self.package_source = r.u32()
        r.count_array(lambda: r.fstring())                    # additional packages to cook
        self.asset_registry_data_offset = r.i32()
        self.bulk_data_start_offset = r.i64()
        self.world_tile_info_data_offset = r.i32()
        r.count_array(lambda: r.i32())                        # chunk ids
        self.preload_dependency_count = r.i32()
        self.preload_dependency_offset = r.i32()
        self.summary_end = r.pos

    # -- names ------------------------------------------------------------ #
    def _parse_names(self):
        """UE5 FNamePool entries: FString + N x u8 hashes (size auto detected)."""
        if self.name_count <= 0:
            return
        limit = min(self.import_offset or len(self.uasset), len(self.uasset))
        best = None
        for hash_bytes in (2, 0, 4):
            try:
                names, end = self._try_names(self.name_offset, self.name_count, hash_bytes, limit)
            except (ValueError, UnexpectedEnd, UnicodeDecodeError):
                continue
            score = sum(1 for n in names if n and all(32 <= ord(c) < 127 for c in n))
            cand = (score, -hash_bytes, hash_bytes, names, end)
            if best is None or cand[:2] > best[:2]:
                best = cand
        if best is None:
            raise ValueError("could not parse name table in %r" % self.path)
        self.name_hash_bytes = best[2]
        self.names = best[3]
        self.names_end = best[4]

    def _try_names(self, offset, count, hash_bytes, limit):
        r = Reader(self.uasset, offset)
        r.end = min(limit, len(self.uasset))
        names = []
        for _ in range(count):
            names.append(r.fstring())
            if hash_bytes:
                r.skip(hash_bytes)
            if r.pos > r.end:
                raise UnexpectedEnd(r.pos, 0, r.end)
        return names, r.pos

    # -- imports / exports ------------------------------------------------ #
    def _parse_imports(self):
        if self.import_count <= 0:
            return
        r = Reader(self.uasset, self.import_offset, names=self.names, package=self)
        self.imports = [Import(i, r) for i in range(self.import_count)]

    def _parse_exports(self):
        if self.export_count <= 0:
            return
        r = Reader(self.uasset, self.export_offset, names=self.names, package=self)
        self.exports = []
        stride = None
        if self.depends_offset > self.export_offset and self.export_count:
            d = self.depends_offset - self.export_offset
            if d % self.export_count == 0 and 40 <= d // self.export_count <= 256:
                stride = d // self.export_count
        for i in range(self.export_count):
            start = r.pos
            e = Export(i, r)
            self.exports.append(e)
            if stride:
                r.seek(start + stride)
            else:
                # heuristic tail size (measured 60 bytes on this build)
                r.seek(max(r.pos, start + 104))

    # -- virtual buffer --------------------------------------------------- #
    def virtual(self):
        """uasset + uexp, the coordinate space of ``serial_offset``."""
        return self.uasset + self.uexp

    def export_reader(self, export, extra=b"") -> Reader:
        """Reader positioned at the export data, bounded by serial_size."""
        virt = self.virtual() + extra
        start = export.serial_offset
        if start >= len(virt):
            raise ValueError("export %r offset %d beyond payload %d" % (export.name, start, len(virt)))
        return Reader(virt, start, names=self.names, package=self,
                      end=min(start + export.serial_size, len(virt)))

    # -- lookups ---------------------------------------------------------- #
    def import_name(self, index):
        if index == 0:
            return "None"
        if index < 0:
            i = -index - 1
            if 0 <= i < len(self.imports):
                return self.imports[i].name
        else:
            i = index - 1
            if 0 <= i < len(self.exports):
                return self.exports[i].name
        return "?"

    def import_class(self, index):
        if index < 0:
            i = -index - 1
            if 0 <= i < len(self.imports):
                return self.imports[i].class_name
        return "?"

    def export_class(self, export):
        """Resolve the UClass name of an export.

        ``ClassIndex`` points at an imported class object, and the *object name*
        of that import is the class name (``/Script/Engine`` + ``Class`` +
        ``StaticMesh`` -> ``StaticMesh``).  Blueprint generated classes appear
        the same way (``Blueprint`` + ``BP_Foo_C`` -> ``BP_Foo_C``), so the
        import name is always the right answer.  ``0`` means "this object is a
        class" (a UClass export has no class index).
        """
        index = export.class_index
        if index == 0:
            return "Class"
        if index < 0:
            i = -index - 1
            if 0 <= i < len(self.imports):
                return self.imports[i].name or self.imports[i].class_name or "?"
            return "?"
        if index > 0:
            i = index - 1
            if 0 <= i < len(self.exports):
                return self.exports[i].name or "?"
            return "?"
        return "?"

    # -- tagged properties ------------------------------------------------ #
    KEYS = 8  # bytes per FName

    def read_properties(self, r, depth=0, stop_at_none=True):
        """Read a tagged property list starting at ``r.pos``.

        Measured Game tag layout (see NOTES.md):

            FName name
            FName type
            i32   size          (value byte count, includes struct terminator)
            i32   array_index
            [FName struct_name + 16b struct_guid]  if StructProperty
            [u8    bool_value]                     if BoolProperty
            [FName enum_name]                      if ByteProperty / EnumProperty
            [FName inner_type]                     if ArrayProperty / SetProperty
            [FName inner_type + FName value_type]  if MapProperty
            u8    has_property_guid  [+ 16b guid if set]
            value[size]
        """
        out = {}
        while True:
            if r.pos >= r.end:
                return out
            name = r.fname()
            if name == "None":
                if stop_at_none:
                    return out
                continue
            ptype = r.fname()
            size = r.i32()
            array_index = r.i32()
            info = {}
            if ptype == "StructProperty":
                info["struct_name"] = r.fname()
                info["struct_guid"] = r.guid()
            elif ptype == "BoolProperty":
                info["bool_value"] = r.u8()
            elif ptype in ("ByteProperty", "EnumProperty"):
                info["enum_name"] = r.fname()
            elif ptype in ("ArrayProperty", "SetProperty"):
                info["inner_type"] = r.fname()
            elif ptype == "MapProperty":
                info["inner_type"] = r.fname()
                info["value_type"] = r.fname()
            if r.u8():                       # has_property_guid
                r.guid()
            vpos = r.pos
            value = self._read_value(r, ptype, size, info, depth)
            r.seek(vpos + size)              # trust the size field
            if array_index > 0 and name in out:
                prev = out[name]
                if isinstance(prev, list):
                    prev.append(value)
                else:
                    out[name] = [prev, value]
            else:
                out[name] = value

    def _read_value(self, r, ptype, size, info, depth):
        vstart = r.pos
        vend = vstart + size
        saved_end = r.end
        if vend < r.end:
            r.end = vend                       # no value may run past its size
        try:
            if ptype == "StructProperty":
                sname = info.get("struct_name", "")
                if sname in RAW_STRUCTS or depth >= 6:
                    return self._read_raw_struct(r, sname, size)
                # native structs are raw, the rest are tagged property lists
                try:
                    val = self.read_properties(r, depth + 1)
                    if vstart < r.pos <= vend:
                        return val
                except (ValueError, UnexpectedEnd, struct.error):
                    pass
                r.seek(vstart)
                return self._read_raw_struct(r, sname, size)
            if ptype in ("ArrayProperty", "SetProperty"):
                inner = info.get("inner_type", "")
                count = r.i32()
                if count < 0 or count > 2000000:
                    raise ValueError("bad array count %d @%#x" % (count, r.pos - 4))
                if inner == "StructProperty" and depth < 5:
                    out = []
                    for _ in range(count):
                        try:
                            out.append(self.read_properties(r, depth + 1))
                        except (ValueError, UnexpectedEnd, struct.error):
                            break                 # element layout unknown
                    return out
                return [self._read_simple(r, inner) for _ in range(count)]
            if ptype == "MapProperty":
                count = r.i32()
                ki = info.get("inner_type", "")
                vi = info.get("value_type", "")
                pairs = []
                for _ in range(count):
                    k = self._read_simple(r, ki)
                    v = self._read_simple(r, vi)
                    pairs.append((k, v))
                return pairs
            if ptype == "ByteProperty":
                return {"enum": info.get("enum_name"),
                        "value": r.u8() if size <= 1 else r.fname()}
            if ptype == "BoolProperty":
                return info.get("bool_value")
            return self._read_simple(r, ptype)
        finally:
            r.end = saved_end
            r.seek(min(vend, saved_end))

    def _read_raw_struct(self, r, sname, size):
        data = r.take(min(size, max(0, r.end - r.pos)))
        if sname in ("Vector", "Rotator", "Vector_NetQuantize", "Vector_NetQuantize10",
                     "Vector_NetQuantize100", "Vector_NetQuantizeNormal"):
            if len(data) >= 12:
                return struct.unpack_from("<3f", data, 0)
        if sname in ("Vector2D", "Vector2f", "IntPoint"):
            if len(data) >= 8:
                return struct.unpack_from("<2i", data, 0) if sname == "IntPoint" \
                    else struct.unpack_from("<2f", data, 0)
        if sname in ("Vector4", "Quat", "Plane", "LinearColor", "Vector4f"):
            if len(data) >= 16:
                return struct.unpack_from("<4f", data, 0)
        if sname in ("Color",):
            if len(data) >= 4:
                return tuple(data[:4])
        if sname in ("Guid",):
            if len(data) >= 16:
                return data[:16].hex()
        return {"_raw": data.hex()}

    def _read_simple_array(self, r, inner, count):
        if count < 0 or count > 1000000:
            raise ValueError("bad array count %d @%#x" % (count, r.pos - 4))
        return [self._read_simple(r, inner) for _ in range(count)]

    def _read_simple(self, r, ptype):
        if ptype in ("IntProperty", "Int32Property", "UInt16Property"):
            return r.i32()
        if ptype in ("UInt32Property",):
            return r.u32()
        if ptype in ("Int64Property",):
            return r.i64()
        if ptype in ("UInt64Property",):
            return r.u64()
        if ptype == "FloatProperty":
            return r.f32()
        if ptype == "DoubleProperty":
            return r.f64()
        if ptype == "NameProperty":
            return r.fname()
        if ptype in ("StrProperty", "TextProperty"):
            return r.fstring()
        if ptype in ("ObjectProperty", "WeakObjectProperty", "InterfaceProperty",
                     "ClassProperty", "LazyObjectProperty"):
            return self.object_path(r.i32())
        if ptype in ("SoftObjectProperty",):
            return r.fstring()
        if ptype == "BoolProperty":
            return r.u8() != 0
        if ptype == "ByteProperty":
            return r.u8()
        if ptype == "EnumProperty":
            return r.fname()
        if ptype in ("Vector", "Rotator", "LinearColor"):
            return tuple(r.f32() for _ in range(3))
        if ptype in ("Vector4", "Quat", "Plane"):
            return tuple(r.f32() for _ in range(4))
        raise ValueError("unsupported property type %r" % ptype)

    def object_path(self, index):
        """Full object path for a FPackageIndex (import/export chain)."""
        if index == 0:
            return "None"
        chain = []
        seen = 0
        while index != 0 and seen < 32:
            seen += 1
            if index < 0:
                imp = self.imports[-index - 1]
                chain.append(imp.name)
                index = imp.outer_index
            else:
                exp = self.exports[index - 1]
                chain.append(exp.name)
                index = exp.outer_index
        chain.reverse()
        return ".".join(chain)

    def find_exports(self, class_name):
        return [e for e in self.exports if self.export_class(e) == class_name]

    def export_by_name(self, name):
        for e in self.exports:
            if e.name == name:
                return e
        return None

    def __repr__(self):
        return "<Package %r ue4=%d ue5=%d names=%d imports=%d exports=%d>" % (
            self.path, self.ue4_version, self.ue5_version, len(self.names),
            len(self.imports), len(self.exports))
