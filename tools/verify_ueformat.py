"""按 DeltaModelViewer/DeltaCore/UemodelReader.cs 的读法校验我们写的 .uemodel。

    python -m tools.verify_ueformat out.uemodel
"""
from __future__ import annotations

import struct
import sys

MAGIC = "UEFORMAT"


class R:
    def __init__(self, b: bytes) -> None:
        self.b, self.p = b, 0

    @property
    def rem(self) -> int:
        return len(self.b) - self.p

    def take(self, n: int) -> bytes:
        v = self.b[self.p:self.p + n]
        if len(v) != n:
            raise SystemExit(f"越界：想要 {n} 字节，只剩 {self.rem}")
        self.p += n
        return v

    def i32(self) -> int:
        return struct.unpack("<i", self.take(4))[0]

    def u8(self) -> int:
        return self.take(1)[0]

    def f2(self):
        return struct.unpack("<2f", self.take(8))

    def f3(self):
        return struct.unpack("<3f", self.take(12))

    def f4(self):
        return struct.unpack("<4f", self.take(16))

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def string(self) -> str:
        n = self.i32()
        if n <= 0 or n > 1 << 20:
            raise SystemExit(f"字符串长度异常 {n} @ {self.p - 4}")
        raw = self.take(n)
        return raw.rstrip(b"\x00").decode("utf-8", "replace")

    def skip(self, n: int) -> None:
        self.take(n)


def check(path: str) -> None:
    data = open(path, "rb").read()
    r = R(data)
    magic = r.take(8).decode("ascii", "replace")
    assert magic == MAGIC, f"魔数不对: {magic!r}"
    otype = r.string()
    version = r.u8()
    name = r.string()
    compressed = r.u8()
    print(f"magic={magic} type={otype} version={version} name={name!r} compressed={compressed}")
    assert not compressed, "本文件应未压缩"

    lods = 0
    while r.rem > 0:
        sec = r.string()
        count = r.i32()
        size = r.i32()
        print(f"section {sec} count={count} size={size}")
        if sec == "LODS":
            for _ in range(count):
                lod_name = r.string()
                lod_size = r.i32()
                start = r.p
                nV = nI = nM = 0
                uv_channels = 0
                while r.p - start < lod_size:
                    s2 = r.string()
                    c2 = r.i32()
                    b2 = r.i32()
                    here = r.p
                    if s2 == "VERTICES":
                        nV = c2
                        r.skip(b2)
                    elif s2 == "INDICES":
                        nI = c2
                        r.skip(b2)
                    elif s2 == "NORMALS":
                        for _i in range(c2):
                            r.f4()
                    elif s2 == "TANGENTS":
                        for _i in range(c2):
                            r.f3()
                    elif s2 == "TEXCOORDS":
                        uv_channels = c2
                        for _c in range(c2):
                            n = r.i32()
                            for _i in range(n):
                                r.f2()
                    elif s2 == "MATERIALS":
                        nM = c2
                        for _i in range(c2):
                            mn = r.string()
                            mp = r.string()
                            fi = r.i32()
                            nf = r.i32()
                            if _i < 3:
                                print(f"    material {mn!r} path={mp[-40:]!r} first={fi} faces={nf}")
                    else:
                        r.skip(b2)
                    assert r.p - here == b2, f"{s2} 实际吃掉 {r.p - here} 字节，声明 {b2}"
                print(f"  {lod_name}: verts={nV} idx={nI} uv_channels={uv_channels} "
                      f"materials={nM} lodSize={lod_size}")
                lods += 1
        else:
            r.skip(size)
    print(f"OK  共 {lods} 个 LOD，文件 {len(data)} 字节")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    check(sys.argv[1])
