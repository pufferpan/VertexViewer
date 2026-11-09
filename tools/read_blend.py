"""极简 .blend 读取器：只为了把材质节点连线（谁连谁）读出来。

不依赖 Blender.exe —— 直接解 DNA1 的结构定义，按指针把
`bNode` / `bNodeSocket` / `bNodeLink` 连起来打印。

    python -m tools.read_blend "C:\\path\\file.blend"
"""
from __future__ import annotations

import struct
import sys
import zstandard as zstd


def _decompress(raw: bytes) -> bytes:
    if raw[:4] == b"\x28\xb5\x2f\xfd":                 # zstd
        return zstd.ZstdDecompressor().stream_reader(raw).read()
    if raw[:2] == b"\x1f\x8b":                         # gzip
        import gzip
        return gzip.decompress(raw)
    return raw


class Blend:
    def __init__(self, path: str) -> None:
        with open(path, "rb") as fh:
            data = _decompress(fh.read())
        self.data = data
        head = data[:12]
        if head[:7] != b"BLENDER":
            raise SystemExit(f"不是 .blend: {head!r}")
        self.ptr = 4 if head[7:8] == b"_" else 8
        self.endian = "<" if head[8:9] == b"v" else ">"
        self.blocks = []                                # (code, len, oldptr, sdna, count, offset)
        pos = 12
        while pos + 8 <= len(data):
            code = data[pos:pos + 4]
            if code == b"ENDB":
                break
            length, = struct.unpack_from(self.endian + "i", data, pos + 4)
            oldptr, = struct.unpack_from(self.endian + "Q" if self.ptr == 8 else self.endian + "I",
                                         data, pos + 8)
            sdna, = struct.unpack_from(self.endian + "i", data, pos + 8 + self.ptr)
            count, = struct.unpack_from(self.endian + "i", data, pos + 12 + self.ptr)
            body = pos + 16 + self.ptr
            self.blocks.append((code, length, oldptr, sdna, count, body))
            pos = body + length
        self._parse_dna()

    # ---- DNA --------------------------------------------------------------
    def _parse_dna(self) -> None:
        dna = next((b for b in self.blocks if b[0] == b"DNA1"), None)
        if dna is None:
            raise SystemExit("找不到 DNA1")
        _, length, _, _, _, body = dna
        buf = self.data[body:body + length]
        p = 0
        assert buf[p:p + 4] == b"SDNA"
        p += 4
        assert buf[p:p + 4] == b"NAME"
        p += 4
        n_names, = struct.unpack_from(self.endian + "i", buf, p)
        p += 4
        self.names = []
        for _ in range(n_names):
            end = buf.index(b"\0", p)
            self.names.append(buf[p:end].decode("ascii", "replace"))
            p = end + 1
        while p % 4:
            p += 1
        assert buf[p:p + 4] == b"TYPE"
        p += 4
        n_types, = struct.unpack_from(self.endian + "i", buf, p)
        p += 4
        self.types = []
        for _ in range(n_types):
            end = buf.index(b"\0", p)
            self.types.append(buf[p:end].decode("ascii", "replace"))
            p = end + 1
        while p % 4:
            p += 1
        assert buf[p:p + 4] == b"TLEN"
        p += 4
        self.type_len = list(struct.unpack_from(self.endian + "%dh" % n_types, buf, p))
        p += 2 * n_types
        while p % 4:
            p += 4 - (p % 4)
        assert buf[p:p + 4] == b"STRC"
        p += 4
        n_structs, = struct.unpack_from(self.endian + "i", buf, p)
        p += 4
        self.structs = {}
        for _ in range(n_structs):
            t_idx, n_fields = struct.unpack_from(self.endian + "hh", buf, p)
            p += 4
            fields = []
            for _ in range(n_fields):
                f_type, f_name = struct.unpack_from(self.endian + "hh", buf, p)
                p += 4
                fields.append((self.types[f_type], self.names[f_name]))
            self.structs[self.types[t_idx]] = fields
        # 尺寸表
        self.size = {}
        for name, fields in self.structs.items():
            off = 0
            for f_type, _f_name in fields:
                if f_type.startswith("*") or f_type.startswith("(*"):
                    off += self.ptr
                else:
                    off += self.type_len[self.types.index(f_type)]
                # 简化：不做对齐处理（.blend 的 DNA 本身就是按 struct 对齐的读取格式）
            self.size[name] = off

    def offsets(self, struct_name: str) -> dict:
        """字段名 -> 偏移（按 DNA 顺序累加，指针 8/4 字节）。"""
        fields = self.structs[struct_name]
        out, off = {}, 0
        for f_type, f_name in fields:
            out[f_name] = (off, f_type)
            if f_type.startswith("*") or f_type.startswith("(*"):
                off += self.ptr
            else:
                off += self.type_len[self.types.index(f_type)]
        return out

    def array(self, code: bytes) -> list:
        """某 code 的所有块，按 (count, 每条记录长度) 拆开。"""
        out = []
        for b_code, length, _oldptr, sdna, count, body in self.blocks:
            if b_code != code:
                continue
            out.append((sdna, count, body, length))
        return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    b = Blend(argv[0])
    print("指针宽度", b.ptr, "字节序", b.endian)
    print("blocks", len(b.blocks))
    for code, length, _p, sdna, count, _b in b.blocks:
        if code in (b"DATA", b"DNA1", b"ENDB"):
            continue
        sname = b.types[sdna] if 0 <= sdna < len(b.types) else "?"
        if count:
            print(f"  {code.decode('latin1')}  count={count:<6}  sdna[{sdna:3d}]={sname}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
