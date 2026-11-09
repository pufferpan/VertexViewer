"""Minimal UE4/UE5 package (.uasset + .uexp) reader for  textures/materials.

Empirically verified against Game: LegacyFileVersion, FileVersionUE4=522,
split packages (uasset = header only, payload in .uexp, bulk in .ubulk),
export SerialOffset is in combined space (uexp_offset = serial_offset - TotalHeaderSize).

Only what texture/material parsing needs:
  * FPackageFileSummary (flags / name table / import table / export table)
  * FName resolution
  * FObjectExport -> data slice in .uexp
  * FPropertyTag list parsing
"""
import struct

MAGIC = 0x9E2A83C1

# FPropertyTag type names we may meet
PROP_EXTRA = {
    "StructProperty": ("struct_name", "struct_guid"),
    "BoolProperty": ("bool_value",),
    "ByteProperty": ("enum_name",),
    "EnumProperty": ("enum_name",),
    "ArrayProperty": ("inner_type",),
    "SetProperty": ("inner_type",),
    "MapProperty": ("inner_type", "value_type"),
}


class Reader:
    __slots__ = ("b", "o")

    def __init__(self, b, o=0):
        self.b = b
        self.o = o

    def eof(self):
        return self.o >= len(self.b)

    def rem(self):
        return len(self.b) - self.o

    def u8(self):
        v = self.b[self.o]
        self.o += 1
        return v

    def i32(self):
        v = struct.unpack_from("<i", self.b, self.o)[0]
        self.o += 4
        return v

    def u32(self):
        v = struct.unpack_from("<I", self.b, self.o)[0]
        self.o += 4
        return v

    def i64(self):
        v = struct.unpack_from("<q", self.b, self.o)[0]
        self.o += 8
        return v

    def f32(self):
        v = struct.unpack_from("<f", self.b, self.o)[0]
        self.o += 4
        return v

    def raw(self, n):
        v = self.b[self.o:self.o + n]
        self.o += n
        return v

    def fstring(self):
        n = self.i32()
        if n == 0:
            return ""
        if n < 0:
            raw = self.raw(-n * 2)
            return raw.decode("utf-16-le", "replace").rstrip("\0")
        raw = self.raw(n)
        return raw.decode("utf-8", "replace").rstrip("\0")


class Import:
    __slots__ = ("class_package", "class_name", "outer", "name")

    def __init__(self, cp, cn, outer, name):
        self.class_package = cp
        self.class_name = cn
        self.outer = outer
        self.name = name

    def __repr__(self):
        return f"<Import {self.class_name!r} {self.name!r} outer={self.outer}>"


class Export:
    __slots__ = ("class_index", "super_index", "template_index", "outer_index",
                 "name", "object_flags", "serial_size", "serial_offset",
                 "forced_export", "not_for_client", "not_for_server",
                 "package_guid", "package_flags", "not_always_loaded",
                 "is_asset", "deps")

    def __repr__(self):
        return f"<Export {self.name!r} size={self.serial_size} off={self.serial_offset}>"


class Upk:
    """Parse a split package.  uexp may be None for monolithic assets."""

    def __init__(self, uasset, uexp=None, ubulk=None):
        self.uasset = uasset
        self.uexp = uexp if uexp is not None else b""
        self.ubulk = ubulk
        self._parse_summary()

    # ---------------- summary ----------------
    def _parse_summary(self):
        b = self.uasset
        if len(b) < 0x30 or struct.unpack_from("<I", b, 0)[0] != MAGIC:
            raise ValueError("not a UE package (bad magic)")
        r = Reader(b, 4)
        legacy = r.i32()
        self.legacy_version = legacy
        # Game writes a LegacyFileVersion that is not one of UE's
        # canonical -4..-8 values, so the pre-header layout is fixed empirically:
        #   0x04 legacy, 0x08 LegacyUE3Version, 0x0C FileVersionUE4,
        #   0x10 FileVersionLicenseeUE4, 0x14 customversion count (0),
        #   0x18 TotalHeaderSize, 0x1C FolderName
        self.legacy_ue3 = r.i32()
        self.ver_ue4 = r.i32()
        self.ver_lic = r.i32()
        self.ver_ue5 = 0
        self.custom_versions = []
        n = r.i32()
        if 0 < n < 4096:
            for _ in range(n):
                if r.rem() < 20:
                    break
                r.raw(16)
                r.i32()
        self.total_header_size = r.i32()
        self.folder_name = r.fstring()
        self.package_flags = r.u32()
        self.name_count = r.i32()
        self.name_offset = r.i32()
        # Two layouts exist depending on the build: with / without a
        # LocalizationId FString between NameOffset and the gatherable pair.
        best = None
        for has_locid in (False, True):
            cand = Reader(b, r.o)
            try:
                if has_locid:
                    cand.fstring()
                    if cand.o > len(b):
                        continue
                fields = [cand.i32() for _ in range(9)]
            except struct.error:
                continue
            gcount, goff, ecount, eoff, icount, ioff, doff = fields[0], fields[1], fields[2], fields[3], fields[4], fields[5], fields[6]
            score = self._score_layout(ecount, eoff, icount, ioff, doff)
            if best is None or score > best[0]:
                best = (score, has_locid, fields, cand.o)
        if best is None:
            raise ValueError("cannot parse package summary")
        score, self.has_locid, fields, self._after_depends = best[0], best[1], best[2], best[3]
        (self.gatherable_count, self.gatherable_offset, self.export_count,
         self.export_offset, self.import_count, self.import_offset,
         self.depends_offset) = fields[:7]
        self._post_depends = fields[7:]
        self.names = self._parse_names()
        self.imports = self._parse_imports()
        self.exports = self._parse_exports()

    def _score_layout(self, ecount, eoff, icount, ioff, doff):
        """Sanity score for a candidate summary field interpretation."""
        size = len(self.uasset)
        if not (0 <= ecount < 100000 and 0 <= icount < 100000):
            return -1
        if not (0 < eoff < size and 0 < ioff < size):
            return -1
        if eoff + ecount * 104 > size:
            return -1
        if ioff + icount * 28 > size:
            return -1
        if not (0 <= doff <= size):
            return -1
        score = 10
        if self.name_offset > 0 and self.name_offset < min(ioff, eoff):
            score += 5
        if ioff + icount * 28 <= eoff:
            score += 3
        if eoff + ecount * 104 <= doff or doff == 0:
            score += 3
        return score

    def _parse_names(self):
        names = []
        r = Reader(self.uasset, self.name_offset)
        for _ in range(self.name_count):
            if r.rem() < 4:
                break
            names.append(r.fstring())
            r.raw(4)  # two u16 hashes
        return names

    def name(self, idx):
        if 0 <= idx < len(self.names):
            return self.names[idx]
        return f"<name#{idx}>"

    def fname(self, r):
        idx = r.i32()
        num = r.i32()
        s = self.name(idx)
        if num:
            s = f"{s}_{num - 1}"
        return s

    def _parse_imports(self):
        out = []
        if self.import_offset <= 0 or self.import_count <= 0:
            return out
        r = Reader(self.uasset, self.import_offset)
        for _ in range(self.import_count):
            if r.rem() < 28:
                break
            cp = self.fname(r)
            cn = self.fname(r)
            outer = r.i32()
            name = self.fname(r)
            out.append(Import(cp, cn, outer, name))
        return out

    def _parse_exports(self):
        out = []
        if self.export_offset <= 0 or self.export_count <= 0:
            return out
        r = Reader(self.uasset, self.export_offset)
        for _ in range(self.export_count):
            if r.rem() < 80:
                break
            e = Export()
            e.class_index = r.i32()
            e.super_index = r.i32()
            e.template_index = r.i32()
            e.outer_index = r.i32()
            e.name = self.fname(r)
            e.object_flags = r.u32()
            e.serial_size = r.i64()
            e.serial_offset = r.i64()
            e.forced_export = r.i32()
            e.not_for_client = r.i32()
            e.not_for_server = r.i32()
            e.package_guid = r.raw(16)
            e.package_flags = r.u32()
            e.not_always_loaded = r.i32()
            e.is_asset = r.i32()
            e.deps = (r.i32(), r.i32(), r.i32(), r.i32(), r.i32())
            out.append(e)
        return out

    # ---------------- accessors ----------------
    def import_of(self, package_index):
        """FPackageIndex -> Import|None (negative = import, positive = export)."""
        if package_index < 0:
            i = -package_index - 1
            return self.imports[i] if 0 <= i < len(self.imports) else None
        return None

    def export_of(self, package_index):
        if package_index > 0:
            i = package_index - 1
            return self.exports[i] if 0 <= i < len(self.exports) else None
        return None

    def path_of(self, package_index):
        """Best-effort object path string for an import index."""
        imp = self.import_of(package_index)
        if imp is None:
            exp = self.export_of(package_index)
            return exp.name if exp else None
        parts = [imp.name]
        outer = imp.outer
        seen = 0
        while outer and seen < 16:
            seen += 1
            o = self.import_of(outer)
            if o is None:
                break
            parts.append(o.name)
            outer = o.outer
        return "/".join(reversed(parts))

    def class_name_of(self, export):
        imp = self.import_of(export.class_index)
        return imp.name if imp else ""

    def export_data(self, export):
        """Slice of the export payload (property data) from .uexp."""
        if export.serial_size <= 0:
            return b""
        start = export.serial_offset - self.total_header_size
        if start < 0:
            # monolithic package: payload lives in the uasset itself
            start = export.serial_offset
            buf = self.uasset
        else:
            buf = self.uexp
        if start > len(buf):
            return b""
        return buf[start:start + export.serial_size]

    def exports_of_class(self, cls):
        return [e for e in self.exports if self.class_name_of(e) == cls]


# ---------------- property list ----------------
class Prop:
    __slots__ = ("name", "type", "size", "array_index", "extra", "value", "offset")

    def __init__(self, name, ptype, size, array_index, extra, value, offset):
        self.name = name
        self.type = ptype
        self.size = size
        self.array_index = array_index
        self.extra = extra
        self.value = value
        self.offset = offset

    def __repr__(self):
        return f"<Prop {self.name}:{self.type} size={self.size}>"


def parse_properties(upk, data, start=0, limit=None, has_guid_byte=True):
    """Parse a UE property tag list.  Returns (list_of_Prop, end_offset)."""
    r = Reader(data, start)
    end = len(data) if limit is None else min(len(data), start + limit)
    out = []
    while r.o + 8 <= end:
        off = r.o
        name = upk.fname(r)
        if name == "None" or name.startswith("None_"):
            return out, r.o
        ptype = upk.fname(r)
        if r.o + 8 > end:
            break
        size = r.i32()
        array_index = r.i32()
        extra = {}
        spec = PROP_EXTRA.get(ptype)
        if spec:
            for field in spec:
                if field.endswith("_name") or field.endswith("_type"):
                    extra[field] = upk.fname(r)
                elif field == "struct_guid":
                    extra[field] = r.raw(16)
                elif field == "bool_value":
                    extra[field] = r.u8()
        if has_guid_byte:
            if r.rem() < 1:
                break
            extra["has_property_guid"] = r.u8()
        if size < 0 or r.o + size > len(data):
            break
        value = r.raw(size)
        out.append(Prop(name, ptype, size, array_index, extra, value, off))
    return out, r.o


def prop_map(upk, data):
    props, _ = parse_properties(upk, data)
    m = {}
    for p in props:
        key = p.name
        if p.array_index:
            key = f"{p.name}[{p.array_index}]"
        m[key] = p
    return m
