"""DeltaForce (UE4 pak v11) container reader.

Footer (last 204 bytes of the file):
    u32 magic (0x5A6F12E1) | u32 version(11) | i64 index_offset | i64 index_size
    | u8 sha1[20] | char compression_method_names[5][32]

Every index region on disk is  AES-256-ECB( plaintext XOR mask )  where `mask`
is a single byte repeated over the whole region.  The correct (key, mask) pair
is found empirically: the plaintext index always starts with
``u64 PathHashSeed == 0`` followed by a plausible file count, so after AES
decryption the first bytes are all equal to the mask byte.

Primary index layout (after decryption):
    u64 path_hash_seed | u32 file_count | FString mount_point
    | u32 has_path_hash_index  [+ i64 offset, i64 size, u8[20] hash]
    | u32 has_full_directory_index [+ i64 offset, i64 size, u8[20] hash]
    | u32 encoded_entries_size | u8 encoded_entries[]

FullDirectoryIndex (separate region, same key+mask):
    u32 num_directories, then per directory  FString dir ('/' terminated)
    u32 num_files, per file  FString name, u32 location
"""

from __future__ import annotations

import json
import os
import struct

from Crypto.Cipher import AES

PAK_MAGIC = 0x5A6F12E1
FOOTER_SIZE = 204
COMPRESSED_HEADER = 73
STORED_HEADER = 53
FLAG_ENCRYPTED = 0x01
FLAG_COMPRESSED = 0x02


class PakError(Exception):
    pass


def load_keyvault(path: str):
    """Load an AESKey1.json style vault into [(name, key_bytes)]."""
    data = json.load(open(path, encoding="utf-8"))
    out = [("MainKey", bytes.fromhex(data["MainKey"][2:]))]
    for k in data.get("Keys", []):
        out.append((k["guid"].upper(), bytes.fromhex(k["key"][2:])))
    return [kv for kv in out if len(kv[1]) == 32]


def _fstring(buf: bytes, off: int):
    if off + 4 > len(buf):
        return None, off
    n = struct.unpack_from("<i", buf, off)[0]
    if n <= 0 or n > 65536 or off + 4 + n > len(buf):
        return None, off
    raw = buf[off + 4:off + 4 + n - 1]
    return raw.decode("utf-8", "replace"), off + 4 + n


def _check_head(p: bytes) -> int | None:
    """Return file_count when `p` starts a plausible primary index."""
    if len(p) < 24:
        return None
    seed, = struct.unpack_from("<Q", p, 0)
    if seed != 0:
        return None
    cnt, = struct.unpack_from("<i", p, 8)
    if not (0 < cnt <= 5_000_000):
        return None
    n, = struct.unpack_from("<i", p, 12)
    if not (2 <= n <= 4096) or 16 + n > len(p):
        return None
    try:
        mp = p[16:16 + n - 1].decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not all(32 <= ord(c) < 127 for c in mp):
        return None
    if "/" not in mp and "\\" not in mp and ".." not in mp:
        return None
    return cnt




def _xor_mask(blob: bytes, mask: int) -> bytes:
    """整段 XOR 单字节 mask（numpy 版；纯 Python 的生成器在 100MB 索引上要好几秒）。"""
    if not blob or not mask:
        return blob
    try:
        import numpy as np
        arr = np.frombuffer(blob, dtype=np.uint8) ^ np.uint8(mask)
        return arr.tobytes()
    except Exception:                                          # noqa: BLE001
        return bytes(b ^ mask for b in blob)


class PakFile:
    """Random-access reader for one DeltaForce .pak."""

    _key_cache: dict[str, tuple[str, bytes, int]] = {}

    def __init__(self, path: str, keyvault, verbose=False):
        self.path = path
        self.name = os.path.basename(path)
        self.size = os.path.getsize(path)
        self.verbose = verbose
        self._fh = open(path, "rb")
        self._keyvault = keyvault
        try:
            self._read_footer()
            self._open_index()
        except Exception:
            self._fh.close()
            raise

    # ------------------------------------------------------------------ #
    def close(self):
        if self._fh and not self._fh.closed:
            self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def read_at(self, off: int, n: int) -> bytes:
        self._fh.seek(off)
        return self._fh.read(n)

    # ------------------------------------------------------------------ #
    def _read_footer(self):
        if self.size < FOOTER_SIZE:
            raise PakError("file too small")
        foot = self.read_at(self.size - FOOTER_SIZE, FOOTER_SIZE)
        magic, ver, ioff, isz = struct.unpack_from("<IIqq", foot, 0)
        if magic != PAK_MAGIC:
            raise PakError("bad magic 0x%08X" % magic)
        if ver != 11:
            raise PakError("unsupported version %d" % ver)
        if not (0 < ioff < self.size) or isz <= 0 or ioff + isz > self.size:
            raise PakError("implausible index %d/%d" % (ioff, isz))
        self.version, self.index_offset, self.index_size = ver, ioff, isz
        # compression method name table: 5 slots of 32 bytes, index 0 is "None"
        names = []
        for i in range(5):
            raw = foot[44 + 32 * i:44 + 32 * (i + 1)].split(b"\0", 1)[0]
            if raw:
                names.append(raw.decode("ascii", "replace"))
        self.methods = ["None"] + names

    def _find_key(self, head: bytes):
        cached = PakFile._key_cache.get(self.path)
        if cached:
            name, key, mask = cached
            if _check_head(bytes(b ^ mask for b in AES.new(key, AES.MODE_ECB).decrypt(head[:64]))):
                return name, key, mask
        for name, key in self._keyvault:
            try:
                dec = AES.new(key, AES.MODE_ECB).decrypt(head[:64])
            except ValueError:
                continue
            for mask in range(256):
                if _check_head(bytes(b ^ mask for b in dec)):
                    PakFile._key_cache[self.path] = (name, key, mask)
                    return name, key, mask
        raise PakError("no key/mask matched %s" % self.name)

    def _decode_region(self, off: int, size: int, mask: int | None = None):
        blob = self.read_at(off, size)
        if len(blob) != size:
            raise PakError("short read of index region")
        cut = size - (size % 16)
        dec = AES.new(self.key, AES.MODE_ECB).decrypt(blob[:cut]) + blob[cut:]
        if mask is None:
            if not dec:
                raise PakError("empty region")
            mask = dec[0]
        return _xor_mask(dec, mask), mask

    def _open_index(self):
        head = self.read_at(self.index_offset, 64)
        self.key_name, self.key, self.mask = self._find_key(head)
        plain, _ = self._decode_region(self.index_offset, self.index_size, self.mask)
        o = 0
        self.path_hash_seed, = struct.unpack_from("<Q", plain, o); o += 8
        self.file_count, = struct.unpack_from("<i", plain, o); o += 4
        self.mount_point, o = _fstring(plain, o)
        if self.mount_point is None:
            raise PakError("mount point unparsable")
        # optional path hash index
        has_phi, = struct.unpack_from("<I", plain, o); o += 4
        if has_phi:
            o += 8 + 8 + 20
        has_fdi, = struct.unpack_from("<I", plain, o); o += 4
        if not has_fdi:
            raise PakError("no FullDirectoryIndex")
        self.fdi_offset, self.fdi_size = struct.unpack_from("<qq", plain, o); o += 16
        o += 20
        self.encoded_size, = struct.unpack_from("<i", plain, o); o += 4
        if self.encoded_size < 0 or o + self.encoded_size > len(plain):
            raise PakError("bad encoded entries size")
        self.encoded = plain[o:o + self.encoded_size]

        fdi, _ = self._decode_region(self.fdi_offset, self.fdi_size, self.mask)
        self.entries = self._parse_fdi(fdi)

    def _parse_fdi(self, b: bytes) -> dict:
        ndir, = struct.unpack_from("<I", b, 0)
        if ndir > 2_000_000:
            raise PakError("bad dir count")
        out = {}
        p = 4
        for _ in range(ndir):
            dname, p = _fstring(b, p)
            if dname is None:
                raise PakError("dir unparsable")
            n, = struct.unpack_from("<i", b, p); p += 4
            if n < 0 or n > 5_000_000:
                raise PakError("bad file count")
            for _ in range(n):
                fname, p = _fstring(b, p)
                if fname is None or p + 4 > len(b):
                    raise PakError("file unparsable")
                loc, = struct.unpack_from("<I", b, p); p += 4
                out[(dname + fname)] = loc
        return out

    # ------------------------------------------------------------------ #
    def _lookup(self, path: str):
        loc = self.entries.get(path)
        if loc is None and path.startswith(self.mount_point):
            loc = self.entries.get(path[len(self.mount_point):])
        if loc is None:
            loc = self.entries.get(path.lstrip(".").lstrip("/"))
        return loc

    def record(self, path: str):
        """Decode the bit-packed FPakEntry record for `path` (UE4 FPakFile::DecodePakEntry)."""
        loc = self._lookup(path)
        enc = self.encoded
        if loc is None or loc < 0 or loc + 4 > len(enc):
            return None
        p = loc
        bitfield, = struct.unpack_from("<I", enc, p); p += 4
        if (bitfield & 0x3F) == 0x3F:
            if p + 4 > len(enc):
                return None
            block_size, = struct.unpack_from("<I", enc, p); p += 4
        else:
            block_size = (bitfield & 0x3F) << 11
        method_index = (bitfield >> 23) & 0x3F
        method = self.methods[method_index] if method_index < len(self.methods) else "?"
        off32 = (bitfield >> 31) & 1
        usz32 = (bitfield >> 30) & 1
        csz32 = (bitfield >> 29) & 1
        encrypted = (bitfield >> 22) & 1
        block_count = (bitfield >> 6) & 0xFFFF

        compressed = method.lower() != "none"
        need = (4 if off32 else 8) + (4 if usz32 else 8)
        if compressed:
            need += 4 if csz32 else 8
        need += block_count * 4 if block_count > 1 else 0
        if p + need > len(enc):
            return None
        if off32:
            offset, = struct.unpack_from("<I", enc, p); p += 4
        else:
            offset, = struct.unpack_from("<q", enc, p); p += 8
        if usz32:
            usize, = struct.unpack_from("<I", enc, p); p += 4
        else:
            usize, = struct.unpack_from("<q", enc, p); p += 8
        if compressed:
            if csz32:
                csize, = struct.unpack_from("<I", enc, p); p += 4
            else:
                csize, = struct.unpack_from("<q", enc, p); p += 8
        else:
            csize = usize

        header_size = 53 + ((4 + block_count * 16) if compressed else 0)
        blocks = []
        if compressed and block_count == 1 and not encrypted:
            blocks = [(offset + header_size, offset + header_size + csize)]
        elif block_count > 0:
            base = offset + header_size
            align = 16 if encrypted else 1
            for _ in range(block_count):
                if p + 4 > len(enc):
                    return None
                length, = struct.unpack_from("<I", enc, p); p += 4
                blocks.append((base, base + length))
                base += -(-length // align) * align

        return dict(kind="compressed" if compressed else "stored",
                    flags=1 if encrypted else 0, method=method, usize=usize,
                    offset=offset, csize=csize, header_size=header_size,
                    blocks=blocks, encrypted=bool(encrypted),
                    block_size=block_size)

    def raw(self, path: str) -> bytes | None:
        rec = self.record(path)
        if not rec:
            return None
        return self.read_at(rec["offset"] + rec["header_size"], rec["csize"])

    def _decrypt(self, blob: bytes, size: int | None = None) -> bytes:
        """AES-256-ECB(pak key) then XOR the index mask byte over everything.

        Matches CUE4Parse GameTypes//Encryption/Aes/DeltaForceAes.cs:
            output = Aes.Decrypt(bytes, key); TensorUtils.Xor(output, xorData[0]);
        The on-disk payload is 16-byte padded, so decrypt the padded tail too.
        """
        m = self.mask
        cut = len(blob) - (len(blob) % 16)
        if cut <= 0:
            out = _xor_mask(blob, m)
        else:
            dec = AES.new(self.key, AES.MODE_ECB).decrypt(blob[:cut])
            out = _xor_mask(dec, m) + _xor_mask(blob[cut:], m)
        return out[:size] if size else out

    def read(self, path: str, oodle=None) -> bytes | None:
        rec = self.record(path)
        if not rec:
            return None
        start = rec["offset"] + rec["header_size"]
        if rec["kind"] == "stored":
            if rec["encrypted"]:
                blob = self.read_at(start, -(-rec["csize"] // 16) * 16)
                return self._decrypt(blob, rec["csize"])
            return self.read_at(start, rec["csize"])
        # ---- compressed ----
        if oodle is None:
            return None
        if not rec["encrypted"]:
            if len(rec["blocks"]) <= 1:
                return oodle.decompress(self.read_at(start, rec["csize"]), rec["usize"])
            return self._read_blocks(rec, oodle, None)
        blob = self.read_at(start, -(-rec["csize"] // 16) * 16)
        blob = self._decrypt(blob, rec["csize"])
        if len(rec["blocks"]) <= 1:
            return oodle.decompress(blob, rec["usize"])
        return self._read_blocks(rec, oodle, blob)

    def _read_blocks(self, rec, oodle, decrypted: bytes | None) -> bytes | None:
        """Multi-block (Oodle) payload: every block is an independent stream.

        Encrypted blocks are padded to 16 bytes on disk (Aes::Align), so the
        offsets in the entry header are already aligned and we can slice the
        already-decrypted contiguous buffer when it was passed in.
        """
        out, pos, remain = bytearray(), 0, rec["usize"]
        enc = rec["encrypted"]
        for a, b in rec["blocks"]:
            n = b - a
            want = min(rec["block_size"] or remain, remain)
            if decrypted is not None:
                chunk = decrypted[pos:pos + (-(-n // 16) * 16 if enc else n)]
            else:
                chunk = self.read_at(a, n)
            part = oodle.decompress(chunk[:n], want)
            if part is None:
                return None
            out += part
            remain -= want
            pos += -(-n // 16) * 16 if enc else n
        return bytes(out)

    def info(self):
        return dict(pak=self.name, size=self.size, key=self.key_name,
                    mask=hex(self.mask), files=len(self.entries),
                    mount=self.mount_point, fdi=(self.fdi_offset, self.fdi_size),
                    methods=self.methods)
