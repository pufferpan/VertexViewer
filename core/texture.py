"""Texture2D decoding for Game (UE4.26 cooked, split packages).

Container facts established empirically (see NOTES.md / tools/mini_upk.py):

* ``.uasset``  -- package header only (TotalHeaderSize == file size)
* ``.uexp``    -- export payload: property list, then FTexturePlatformData,
                  then (for a streamed texture) the *small* mip levels inline
* ``.ubulk``   -- intermediate mip levels (BULKDATA_PayloadInSeperateFile)
* ``.uptnl``   -- optional payload: the *largest* mip level (streamed "HD"
                  texture data).  Present for most ``GenTexDirHD`` textures.

Mip levels are distributed across three streams, highest resolution first:

    512x512   -> .uptnl  (BULKDATA_OptionalPayload, flags 0x0D01)
    256x256   -> .ubulk  (flags 0x0501)
    128x128   -> .ubulk
    64x64..1  -> inline in .uexp, each preceded by a 20 byte mip record
                 (u32 flags==0x48, u32 element_count, u32 size_on_disk, u64 x)

Because the exact FByteBulkData record layout differs between engine builds we
locate the inline level by *validating* candidate record headers instead of
blindly trusting offsets, and we pick the largest level that a stream can hold.
Decoding itself is done by ``texture2ddecoder`` (BC1-BC7, ASTC) with a pure
Python BC1/BC3 fallback and Pillow for the uncompressed formats.
"""
from __future__ import annotations

import io
import os
import re
import struct
import zlib

import numpy as np

from core.types import Texture

try:  # the verified minimal package reader (shared with tools/probe_tex.py)
    from tools.mini_upk import Upk, parse_properties
except Exception:  # pragma: no cover - package layout fallback
    Upk = None
    parse_properties = None

try:
    import texture2ddecoder as _tdd
except Exception:  # pragma: no cover - optional accelerator
    _tdd = None

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None


# --------------------------------------------------------------------------- #
# pixel format table
# --------------------------------------------------------------------------- #
# name -> (blocks: bytes per 4x4 block | 0 for raw, bytes per pixel for raw)
_FORMATS = {
    "BC1": (8, 0),
    "BC2": (16, 0),
    "BC3": (16, 0),
    "BC4": (8, 0),
    "BC5": (16, 0),
    "BC6H": (16, 0),
    "BC7": (16, 0),
    "R8G8B8A8": (0, 4),
    "B8G8R8A8": (0, 4),
    "R8G8B8A8_SRGB": (0, 4),
    "B8G8R8A8_SRGB": (0, 4),
    "R8G8": (0, 2),
    "R8": (0, 1),
    "G8": (0, 1),
    "A8": (0, 1),
    "R16F": (0, 2),
    "G16R16F": (0, 4),
    "R16G16B16A16F": (0, 8),
    "R32F": (0, 4),
    "R32G32B32A32F": (0, 16),
}

# PF_* -> our name.  Anything else keeps its PF_ suffix.
PF_ALIASES = {
    "PF_BC1": "BC1", "PF_DXT1": "BC1",
    "PF_BC2": "BC2", "PF_DXT3": "BC2",
    "PF_BC3": "BC3", "PF_DXT5": "BC3",
    "PF_BC4": "BC4", "PF_BC5": "BC5",
    "PF_BC6H": "BC6H", "PF_BC7": "BC7",
    "PF_B8G8R8A8": "B8G8R8A8",
    "PF_R8G8B8A8": "R8G8B8A8",
    "PF_R8G8B8A8_SNORM": "R8G8B8A8",
    "PF_R8G8": "R8G8", "PF_R8": "R8", "PF_G8": "G8", "PF_A8": "A8",
    "PF_R16F": "R16F", "PF_G16R16F": "G16R16F",
    "PF_FloatRGBA": "R16G16B16A16F", "PF_R16G16B16A16_FLOAT": "R16G16B16A16F",
    "PF_R32_FLOAT": "R32F", "PF_R32G32B32A32_FLOAT": "R32G32B32A32F",
}

# DDS fourCC / DXGI format for the Pillow fallback path
_DDS_FOURCC = {
    "BC1": b"DXT1", "BC2": b"DXT3", "BC3": b"DXT5",
    "BC4": b"ATI1", "BC5": b"BC5S",
}
_DXGI = {"BC6H": 95, "BC7": 98, "R8G8B8A8": 28, "B8G8R8A8": 87, "R8": 61, "G8": 61,
         "R8G8": 49, "A8": 65}

# formats that are single/dual channel -> linear data, never sRGB
_LINEAR_FORMATS = {"BC4", "BC5", "BC6H", "R8", "G8", "A8", "R8G8", "R16F",
                   "G16R16F", "R32F"}

_CAMEL_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_HASH_TAIL = re.compile(r"[0-9a-f]{8,}$")

# kind -> keywords.  Keywords longer than 3 chars match as substrings, short
# ones (``ar``, ``nr``, ``or m``) must equal a whole token, otherwise
# "BaseColorMap" matches "orm" through "colORM" -- which really happened.
_KIND_RULES = (
    ("normal", ("normal", "_nrm", "nrm", "nr")),
    ("orm", ("orm", "mra", "arm", "rma", "mac", "ao", "occlusion", "ar")),
    ("mask", ("mask",)),
    ("rm", ("rough", "metalness", "metallic", "specular", "gloss")),
    ("height", ("height", "displace")),
    ("alpha", ("opacity", "alpha", "mask")),
    ("emissive", ("emissi", "glow")),
    ("basecolor", ("basecolor", "basecolour", "albedo", "diffuse")),
)

_LINEAR_KINDS = {"normal", "orm", "mask", "rm", "height", "alpha"}


def name_tokens(name: str) -> list:
    """``T_VMGen_BaseColorMap_<hash>`` -> ``['t', 'vm', 'gen', 'base', 'color', 'map']``."""
    stem = (name or "").rsplit(".", 1)[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem = _HASH_TAIL.sub("", stem)
    stem = _CAMEL_SPLIT.sub(" ", stem)
    return [t for t in re.split(r"[^A-Za-z0-9]+", stem.lower()) if t]


def texture_kind(name: str) -> str:
    """Best-effort semantic kind of a texture from its asset name."""
    toks = name_tokens(name)
    joined = "".join(toks)
    for kind, keys in _KIND_RULES:
        for k in keys:
            if len(k) <= 3:
                if k in toks or k == joined:
                    return kind
            elif k in joined:
                return kind
    if "ui" in toks:
        return "ui"
    return ""


# --------------------------------------------------------------------------- #
# sizing helpers
# --------------------------------------------------------------------------- #
def format_from_pf(pf_name: str) -> str:
    """``PF_BC7`` -> ``BC7``; unknown formats keep their raw name."""
    pf = (pf_name or "").upper()
    if pf in PF_ALIASES:
        return PF_ALIASES[pf]
    if pf.startswith("PF_ASTC"):
        return pf.replace("PF_", "")
    if pf.startswith("PF_ETC"):
        return pf.replace("PF_", "")
    return pf.replace("PF_", "") if pf.startswith("PF_") else pf


def mip_size(fmt: str, w: int, h: int) -> int:
    """Bytes a single mip level of ``fmt`` occupies."""
    blocks, raw = _FORMATS.get(fmt, (16, 0))
    if raw:
        return int(w) * int(h) * raw
    bx = max(1, (int(w) + 3) // 4)
    by = max(1, (int(h) + 3) // 4)
    return bx * by * blocks


def mip_chain(w: int, h: int, count: int | None = None):
    """[(w, h), ...] for every level down to 1x1."""
    out = [(int(w), int(h))]
    while out[-1][0] > 1 or out[-1][1] > 1:
        nw, nh = max(1, out[-1][0] // 2), max(1, out[-1][1] // 2)
        if (nw, nh) == out[-1]:
            break
        out.append((nw, nh))
        if count and len(out) >= count:
            break
    return out


def chain_size(fmt: str, chain) -> int:
    return sum(mip_size(fmt, w, h) for w, h in chain)


# --------------------------------------------------------------------------- #
# DDS (used by the Pillow fallback + as a debugging artefact)
# --------------------------------------------------------------------------- #
def dds_header(fmt: str, w: int, h: int, mip_count: int = 1,
               srgb: bool = False) -> bytes:
    """Build a DDS header (128 bytes, +20 when a DX10 block is needed)."""
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000 | (0x20000 if mip_count > 1 else 0)
    pitch = mip_size(fmt, w, h) // max(1, h) if fmt not in _DDS_FOURCC else 0
    caps = 0x1000 | (0x400000 if mip_count > 1 else 0x8)

    pf_flags = 0x4
    fourcc = b"\0\0\0\0"
    rgb_bits = 0
    masks = (0, 0, 0, 0)
    dx10 = b""

    if fmt in _DDS_FOURCC:
        fourcc = _DDS_FOURCC[fmt]
    elif fmt in _DXGI:
        fourcc = b"DX10"
        dxgi = _DXGI[fmt] + (1 if srgb and fmt in ("BC7",) else 0)
        dx10 = struct.pack("<5I", dxgi, 3, 0, 1, 0)
        caps |= 0x8
    else:
        pf_flags = 0x40 | 0x1
        rgb_bits = _FORMATS.get(fmt, (0, 4))[1] * 8
        masks = {
            "R8G8B8A8": (0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000),
            "B8G8R8A8": (0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000),
            "R8G8": (0x000000FF, 0x0000FF00, 0, 0),
            "R8": (0x000000FF, 0, 0, 0),
            "G8": (0x000000FF, 0, 0, 0),
            "A8": (0, 0, 0, 0x000000FF),
        }.get(fmt, (0xFF, 0xFF00, 0xFF0000, 0xFF000000))

    # layout: magic, size, flags, height, width, pitch, depth, mip count
    out = bytearray(b"DDS ")
    out += struct.pack("<7I", 124, flags, int(h), int(w), pitch, 0, mip_count)
    out += b"\0" * 44                                            # reserved
    out += struct.pack("<2I4s5I", 32, pf_flags, fourcc, rgb_bits,
                       masks[0], masks[1], masks[2], masks[3])
    out += struct.pack("<5I", caps, caps, 0, 0, 0)               # caps..reserved2
    out += dx10
    assert len(out) == 128 + len(dx10), (len(out), len(dx10))
    return bytes(out)


# --------------------------------------------------------------------------- #
# decoders
# --------------------------------------------------------------------------- #
def _flip(a: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(a[::-1])


def _rebuild_normal(a: np.ndarray) -> np.ndarray:
    """BC5/BC4 normal data stores only X and Y -- rebuild Z for display.

    ``x = R * 2 - 1``, ``y = G * 2 - 1``, ``z = sqrt(1 - x^2 - y^2)``, then back
    to ``[0, 255]`` in the blue channel so the map looks like a normal map in the
    viewer (and so the renderer can use it directly).
    """
    out = a.copy()
    x = a[..., 0].astype(np.float32) / 127.5 - 1.0
    y = a[..., 1].astype(np.float32) / 127.5 - 1.0
    z = np.sqrt(np.clip(1.0 - x * x - y * y, 0.0, 1.0))
    out[..., 2] = np.clip(z * 127.5 + 127.5, 0, 255).astype(np.uint8)
    out[..., 3] = 255
    return out


def _bc1_py(data: bytes, w: int, h: int) -> np.ndarray:
    """Minimal BC1 (DXT1) decoder used when texture2ddecoder is missing."""
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    out = np.zeros((bh * 4, bw * 4, 4), np.uint8)
    out[:, :, 3] = 255
    for by in range(bh):
        for bx in range(bw):
            o = (by * bw + bx) * 8
            c0, c1, bits = struct.unpack_from("<HHI", data, o)
            def expand(c):
                return np.array([((c >> 11) & 31) * 255 // 31,
                                 ((c >> 5) & 63) * 255 // 63,
                                 (c & 31) * 255 // 31], np.float32)
            e0, e1 = expand(c0), expand(c1)
            pal = [e0, e1]
            if c0 > c1:
                pal += [e0 * 2 / 3 + e1 / 3, e0 / 3 + e1 * 2 / 3]
            else:
                pal += [(e0 + e1) / 2, np.zeros(3, np.float32)]
            blk = out[by * 4:by * 4 + 4, bx * 4:bx * 4 + 4]
            for py in range(4):
                for px in range(4):
                    idx = (bits >> (2 * (py * 4 + px))) & 3
                    blk[py, px, :3] = pal[idx].astype(np.uint8)
            if c0 <= c1 and (bits >> 30) & 0:  # transparent mode unused here
                pass
    return out[:h, :w]


def _bc3_py(data: bytes, w: int, h: int) -> np.ndarray:
    """Minimal BC3 (DXT5) decoder: BC1 colour blocks + BC4 alpha blocks."""
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    rgba = np.zeros((bh * 4, bw * 4, 4), np.uint8)
    color = np.zeros((bh * 4, bw * 4, 4), np.uint8)
    for by in range(bh):
        for bx in range(bw):
            o = (by * bw + bx) * 16
            a0, a1 = data[o], data[o + 1]
            abits = int.from_bytes(data[o + 2:o + 8], "little")
            if a0 > a1:
                alphas = [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
            else:
                alphas = [a0, a1] + [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255]
            cblk = data[o + 8:o + 16]
            sub = _bc1_py(cblk, 4, 4).reshape(4, 4, 4)
            color[by * 4:by * 4 + 4, bx * 4:bx * 4 + 4, :3] = sub[:, :, :3]
            for py in range(4):
                for px in range(4):
                    idx = (abits >> (3 * (py * 4 + px))) & 7
                    rgba[by * 4 + py, bx * 4 + px, :3] = sub[py, px, :3]
                    rgba[by * 4 + py, bx * 4 + px, 3] = alphas[idx]
    return rgba[:h, :w]


def _raw_fmt(fmt: str, data: bytes, w: int, h: int) -> np.ndarray | None:
    n = w * h
    arr = np.frombuffer(data[:mip_size(fmt, w, h)], dtype=np.uint8)
    if fmt in ("R8G8B8A8", "R8G8B8A8_SRGB"):
        out = np.zeros((n, 4), np.uint8)
        out[:, :] = arr[:n * 4].reshape(n, 4)
        return out.reshape(h, w, 4)
    if fmt in ("B8G8R8A8", "B8G8R8A8_SRGB"):
        out = np.zeros((n, 4), np.uint8)
        out[:, :] = arr[:n * 4].reshape(n, 4)
        out[:, [0, 2]] = out[:, [2, 0]]
        return out.reshape(h, w, 4)
    if fmt in ("R8", "G8", "A8"):
        out = np.zeros((n, 4), np.uint8)
        out[:, 0] = out[:, 1] = out[:, 2] = arr[:n]
        out[:, 3] = 255
        if fmt == "A8":
            out[:, 3] = arr[:n]
        return out.reshape(h, w, 4)
    if fmt == "R8G8":
        out = np.zeros((n, 4), np.uint8)
        out[:, :2] = arr[:n * 2].reshape(n, 2)
        out[:, 2] = 255
        out[:, 3] = 255
        return out.reshape(h, w, 4)
    if fmt in ("R16F", "G16R16F", "R16G16B16A16F"):
        chans = {"R16F": 1, "G16R16F": 2, "R16G16B16A16F": 4}[fmt]
        vals = np.frombuffer(data[:n * 2 * chans], dtype=np.float16).astype(np.float32)
        vals = vals.reshape(n, chans)
        out = np.zeros((n, 4), np.uint8)
        for c in range(min(chans, 3)):
            v = np.nan_to_num(vals[:, c])
            out[:, c] = np.clip(v, 0, 1) * 255
        out[:, 3] = 255 if chans < 4 else np.clip(np.nan_to_num(vals[:, 3]), 0, 1) * 255
        return out.reshape(h, w, 4)
    if fmt == "R32F":
        vals = np.frombuffer(data[:n * 4], dtype=np.float32).reshape(n)
        out = np.zeros((n, 4), np.uint8)
        v = np.clip(np.nan_to_num(vals), 0, 1) * 255
        out[:, 0] = out[:, 1] = out[:, 2] = v
        out[:, 3] = 255
        return out.reshape(h, w, 4)
    return None


def _dds_pil(fmt: str, data: bytes, w: int, h: int) -> np.ndarray | None:
    """Pillow fallback for BC1/BC2/BC3 (no BC5/BC7 support)."""
    if Image is None or fmt not in _DDS_FOURCC:
        return None
    try:
        im = Image.open(io.BytesIO(dds_header(fmt, w, h, 1) + data))
        im.load()
        return np.asarray(im.convert("RGBA"), dtype=np.uint8)
    except Exception:
        return None


def decode_mip(fmt: str, blob: bytes, w: int, h: int) -> np.ndarray | None:
    """Decode one mip level into a top-down (h, w, 4) uint8 array."""
    need = mip_size(fmt, w, h)
    if len(blob) < need or w <= 0 or h <= 0:
        return None
    blob = bytes(blob[:need])
    if fmt in ("R8G8B8A8", "B8G8R8A8", "R8G8B8A8_SRGB", "B8G8R8A8_SRGB",
               "R8", "G8", "A8", "R8G8", "R16F", "G16R16F", "R16G16B16A16F",
               "R32F", "R32G32B32A32F"):
        return _raw_fmt(fmt, blob, w, h)
    if _tdd is not None:
        try:
            fn = {
                "BC1": lambda b, x, y: _tdd.decode_bc1(b, x, y),
                "BC2": lambda b, x, y: _tdd.decode_bc2(b, x, y),
                "BC3": lambda b, x, y: _tdd.decode_bc3(b, x, y),
                "BC4": lambda b, x, y: _tdd.decode_bc4(b, x, y),
                "BC5": lambda b, x, y: _tdd.decode_bc5(b, x, y),
                "BC6H": lambda b, x, y: _tdd.decode_bc6(b, x, y),
                "BC7": lambda b, x, y: _tdd.decode_bc7(b, x, y),
            }.get(fmt)
            if fn is not None:
                raw = fn(blob, w, h)
                a = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 4).copy()
                # texture2ddecoder hands back BGRA (verified against Pillow's
                # DDS/BC7 decoder: only R and B differ, and the row order is
                # already top-down, so no flip)
                a = a[..., [2, 1, 0, 3]]
                if fmt == "BC5":
                    return _rebuild_normal(a)
                if fmt == "BC4":
                    a[..., 1] = a[..., 0]
                    a[..., 2] = a[..., 0]
                    a[..., 3] = 255
                return a
        except Exception:
            pass
        if fmt.startswith("ASTC"):
            try:
                bx, by = [int(t) for t in fmt.split("_")[-2:]]
                raw = _tdd.decode_astc(blob, w, h, bx, by)
                a = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 4).copy()
                return a[..., [2, 1, 0, 3]]
            except Exception:
                return None
    if fmt in ("BC1", "BC3"):
        try:
            a = _bc1_py(blob, w, h) if fmt == "BC1" else _bc3_py(blob, w, h)
            return a.astype(np.uint8)
        except Exception:
            pass
    return _dds_pil(fmt, blob, w, h)


# --------------------------------------------------------------------------- #
# platform data discovery
# --------------------------------------------------------------------------- #
def _find_pixel_format(data: bytes):
    """Locate the ``PF_xxx`` FString in an export payload.

    Returns ``(pf_name, length_field_pos)`` or ``(None, None)``.
    """
    start = 0
    while True:
        i = data.find(b"PF_", start)
        if i < 4:
            return None, None
        ln = struct.unpack_from("<i", data, i - 4)[0]
        if 4 <= ln <= 40:
            body = data[i:i + ln - 1]
            if (len(body) == ln - 1 and body.isascii()
                    and data[i + ln - 1] == 0 and b"_" in body):
                return body.decode("ascii", "replace"), i - 4
        start = i + 1


def _platform_dims(data: bytes, pf_pos: int):
    """SizeX/SizeY/PackedData precede the PixelFormat FString.

    DF writes ``SizeX, SizeY, PackedData`` right before the FString length, but
    the exact gap depends on the build, so probe a few candidates and keep the
    pair that looks like a texture size.
    """
    cands = []
    for delta in (12, 16, 20, 24):
        p = pf_pos - delta
        if p < 0:
            continue
        sx, sy = struct.unpack_from("<II", data, p)
        if 1 < sx <= 16384 and 1 < sy <= 16384:
            cands.append((sx, sy, p))
    # prefer power-of-two squares (all DF model textures are), largest first
    def rank(c):
        sx, sy = c[0], c[1]
        pow2 = (sx & (sx - 1)) == 0 and (sy & (sy - 1)) == 0
        return (0 if (pow2 and sx == sy) else 1, -sx * sy)
    if not cands:
        return None
    cands.sort(key=rank)
    return cands[0]


def _inline_mip_start(data: bytes, after: int, fmt: str, chain):
    """Find the first inline mip level by validating record headers.

    A level is preceded by ``[u32 flags][u32 element_count][u32 size_on_disk]
    [8 bytes]`` (20 bytes).  The records are *not* 4-byte aligned inside the
    platform data (the FString before them shifts everything by a byte), so
    every byte offset is a candidate.
    """
    sizes = {mip_size(fmt, w, h): (w, h, i) for i, (w, h) in enumerate(chain)}
    best = None
    start = max(0, after - 16)
    for p in range(start, min(len(data) - 20, after + 4096)):
        flags, ec, sod = struct.unpack_from("<III", data, p)
        if flags not in (0x48, 0x40, 0x20, 0x08, 0x28, 0x00, 0x2C, 0x4C):
            continue
        if ec != sod or ec not in sizes:
            continue
        if p + 20 + ec > len(data):
            continue
        w, h, idx = sizes[ec]
        # prefer the largest level (smallest index)
        if best is None or idx < best[0]:
            best = (idx, p + 20, w, h)
    if best is None:
        return None
    return {"index": best[0], "offset": best[1], "width": best[2], "height": best[3]}


def _fit_stream(data: bytes, fmt: str, chain, limit_index: int | None = None):
    """Largest mip level index whose payload fits in ``data``."""
    for i, (w, h) in enumerate(chain):
        if limit_index is not None and i > limit_index:
            break
        if mip_size(fmt, w, h) <= len(data):
            return i
    return None


_ZLIB_HDRS = {(0x78, 0x01), (0x78, 0x5E), (0x78, 0x9C), (0x78, 0xDA)}


def inflate_stream(blob):
    """Undo per-block zlib compression of a bulk stream.

    Most DF textures store raw BC7 mips in ``.ubulk``/``.uptnl``, but the
    environment "HD" set (e.g. Morocco structures) stores the same payload as a
    chain of independent zlib members, ~18 KB of output each.  Returns
    ``(data, was_compressed)``; on any failure the input comes back untouched.
    """
    if not blob or len(blob) < 4 or (blob[0], blob[1]) not in _ZLIB_HDRS:
        return blob, False
    if ((blob[0] << 8) | blob[1]) % 31:
        return blob, False
    out = bytearray()
    buf = blob
    guard = 0
    while buf and guard < 65536:
        d = zlib.decompressobj()
        try:
            out += d.decompress(buf)
            out += d.flush()
        except Exception:
            return blob, False
        buf = d.unused_data
        guard += 1
    if not out:
        return blob, False
    return bytes(out), True


def _dims_from_stream(fmt: str, uptnl: bytes | None, ubulk: bytes | None):
    """Infer the top mip dimensions from the size of an external stream.

    A ``.uptnl`` normally holds exactly one level, so ``mip_size(fmt, d, d)``
    matches its length for exactly one power-of-two ``d`` -- a very strong
    signal.  ``.ubulk`` holds a run of levels, so we take the largest square
    that fits.
    """
    for stream, exact in ((uptnl, True), (ubulk, False)):
        if not stream:
            continue
        n = len(stream)
        best = None
        for d in (16384, 8192, 4096, 2048, 1024, 512, 256, 128, 64, 32, 16, 8, 4):
            if exact:
                if mip_size(fmt, d, d) == n:
                    return (d, d)
            elif mip_size(fmt, d, d) <= n:
                best = (d, d)
                break
        if best:
            return best
    return None


def inspect_texture(uasset: bytes, uexp: bytes | None, ubulk: bytes | None,
                    uptnl: bytes | None = None) -> dict:
    """Parse a Texture2D package without decoding pixels (diagnostics)."""
    info = {"ok": False, "error": "", "pixel_format": "", "format": "",
            "sx": 0, "sy": 0, "dims": None, "mip_count": 0, "has_bulk": False,
            "has_uptnl": False, "ubulk_len": len(ubulk or b""),
            "uptnl_len": len(uptnl or b""),
            "source": "", "chosen": None, "inline_offset": None,
            "imported": None, "stream_dims": None,
            "compression": "", "lod_group": ""}
    if Upk is None:
        info["error"] = "mini_upk unavailable"
        return info
    try:
        upk = Upk(uasset, uexp, ubulk)
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
        return info
    exports = upk.exports_of_class("Texture2D")
    exp = exports[0] if exports else (upk.exports[0] if upk.exports else None)
    if exp is None:
        info["error"] = "no export"
        return info
    data = upk.export_data(exp)
    if not data:
        info["error"] = "empty export payload"
        return info
    props, _end = parse_properties(upk, data)
    pm = {p.name: p for p in props}
    if "CompressionSettings" in pm:
        raw = pm["CompressionSettings"].value
        try:
            idx = struct.unpack_from("<i", raw, 0)[0]
            info["compression"] = upk.name(idx)
        except Exception:
            pass
    if "LODGroup" in pm:
        raw = pm["LODGroup"].value
        try:
            info["lod_group"] = upk.name(struct.unpack_from("<i", raw, 0)[0])
        except Exception:
            pass
    if "ImportedSize" in pm:
        try:
            info["imported"] = struct.unpack_from("<2i", pm["ImportedSize"].value, 0)
        except Exception:
            pass

    # some sets (environment HD) zlib-compress the bulk payload per block
    up_raw, ub_raw = uptnl, ubulk
    up_d, up_z = inflate_stream(uptnl)
    ub_d, ub_z = inflate_stream(ubulk)
    info["_uptnl"], info["_ubulk"] = up_d, ub_d
    info["stream_compression"] = "zlib" if (up_z or ub_z) else ""
    info["has_bulk"] = bool(ub_d)
    info["has_uptnl"] = bool(up_d)
    info["ubulk_len"] = len(ub_d or b"")
    info["uptnl_len"] = len(up_d or b"")
    info["ubulk_raw_len"] = len(ub_raw or b"")
    info["uptnl_raw_len"] = len(up_raw or b"")
    uptnl, ubulk = up_d, ub_d

    pf, pf_pos = _find_pixel_format(data)
    if not pf:
        info["error"] = "no PixelFormat found"
        return info
    info["pixel_format"] = pf
    fmt = format_from_pf(pf)
    info["format"] = fmt
    dims = _platform_dims(data, pf_pos)
    stream_dims = _dims_from_stream(fmt, uptnl, ubulk)
    info["stream_dims"] = stream_dims
    if dims:
        info["sx"], info["sy"], _pd = dims
        # .uptnl carries exactly mip0 in essentially every DF package, so when
        # the header pair disagrees with the stream length we trust the stream
        if (uptnl and stream_dims
                and mip_size(fmt, info["sx"], info["sy"]) != len(uptnl)
                and mip_size(fmt, *stream_dims) == len(uptnl)):
            info["sx"], info["sy"] = stream_dims
    elif stream_dims:
        info["sx"], info["sy"] = stream_dims
    elif info["imported"]:
        info["sx"], info["sy"] = info["imported"]
    if not info["sx"] or not info["sy"]:
        info["error"] = "no dimensions"
        return info
    chain = mip_chain(info["sx"], info["sy"])
    info["dims"] = chain
    info["has_bulk"] = bool(ubulk)
    info["has_uptnl"] = bool(uptnl)

    # 1) the big level lives in .uptnl when present and large enough
    if uptnl and mip_size(fmt, *chain[0]) <= len(uptnl):
        info.update(source="uptnl", chosen=(0, chain[0]), mip_count=len(chain), ok=True)
        return info
    # 2) otherwise the first level inside .ubulk
    if ubulk:
        idx = _fit_stream(ubulk, fmt, chain)
        if idx is not None:
            info.update(source="ubulk", chosen=(idx, chain[idx]),
                        mip_count=len(chain), ok=True)
            return info
    # 3) inline fallback
    cand = _inline_mip_start(data, pf_pos, fmt, chain)
    if cand:
        info.update(source="inline", chosen=(cand["index"], (cand["width"], cand["height"])),
                    inline_offset=cand["offset"], mip_count=len(chain), ok=True)
        return info
    # 4) small textures keep the whole chain inline: it ends exactly at the end
    #    of the export payload, so walk backwards from there
    total = chain_size(fmt, chain)
    if 0 < total <= len(data) - pf_pos:
        info.update(source="inline-tail", chosen=(0, chain[0]),
                    inline_offset=len(data) - total, mip_count=len(chain), ok=True)
        return info
    # 5) last resort: treat the whole payload as the biggest square that fits
    idx = _fit_stream(data[pf_pos:], fmt, chain)
    if idx is not None:
        info.update(source="uexp-raw", chosen=(idx, chain[idx]), mip_count=len(chain),
                    inline_offset=pf_pos, ok=True)
        return info
    info["error"] = "no mip payload found"
    return info


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def _texture_name(pak_path: str) -> str:
    base = os.path.basename((pak_path or "").replace("\\", "/"))
    return base.rsplit(".", 1)[0] if "." in base else base


def _export_payload(uasset: bytes, uexp: bytes | None, ubulk: bytes | None) -> bytes:
    """Export payload bytes of the Texture2D export (property list + platform data)."""
    if Upk is None:
        return b""
    try:
        upk = Upk(uasset, uexp, ubulk)
    except Exception:
        return b""
    exps = upk.exports_of_class("Texture2D")
    exp = exps[0] if exps else (upk.exports[0] if upk.exports else None)
    return upk.export_data(exp) if exp is not None else b""


def _srgb_for(name: str, fmt: str, info: dict) -> bool:
    if fmt in _LINEAR_FORMATS:
        return False
    comp = (info.get("compression") or "").upper()
    if comp in ("TC_NORMALMAP", "TC_MASKS", "TC_GRAYSCALE", "TC_ALPHAMASK",
                "TC_DISPLACEMENTMAP", "TC_SINGLECHANNEL"):
        return False
    # note: pass the original name -- texture_kind() splits CamelCase itself,
    # lowercasing first would turn "MRAMap" into one token and lose "mra"
    return texture_kind(name or "") not in _LINEAR_KINDS


def load_texture(uasset: bytes, uexp: bytes | None, ubulk: bytes | None,
                 pak_path: str = "", uptnl: bytes | None = None) -> Texture:
    """Decode a cooked UTexture2D into a :class:`core.types.Texture`.

    ``uptnl`` is the optional payload stream (``.uptnl``); pass it whenever
    available -- it holds the largest and sharpest mip level.
    """
    name = _texture_name(pak_path)
    tex = Texture(name=name, pak_path=pak_path)
    info = inspect_texture(uasset, uexp, ubulk, uptnl)
    if not info.get("ok"):
        tex.source_format = info.get("format", "") or "?"
        return tex
    fmt = info["format"]
    idx, (w, h) = info["chosen"]
    # use the de-chunked (zlib) views when the payload was compressed
    uptnl = info.get("_uptnl") if info.get("_uptnl") else uptnl
    ubulk = info.get("_ubulk") if info.get("_ubulk") else ubulk
    blob = b""
    if info["source"] == "uptnl":
        blob = uptnl or b""
    elif info["source"] == "ubulk":
        blob = ubulk or b""
    elif info["source"] == "inline":
        data = _export_payload(uasset, uexp, ubulk)
        blob = data[info["inline_offset"]:]
    else:
        blob = (_export_payload(uasset, uexp, ubulk))[info.get("inline_offset") or 0:]

    rgba = decode_mip(fmt, blob, w, h) if blob else None
    if rgba is None and ubulk:
        boff = 0
        for i in range(idx + 1):
            if i == idx:
                rgba = decode_mip(fmt, ubulk[boff:], *((w, h)))
                break
            boff += mip_size(fmt, *info["dims"][i])
    if rgba is None and uptnl:
        rgba = decode_mip(fmt, uptnl, *info["dims"][0])
    if rgba is None:
        tex.source_format = fmt
        return tex
    tex.width, tex.height = int(rgba.shape[1]), int(rgba.shape[0])
    tex.rgba = np.ascontiguousarray(rgba)
    tex.source_format = fmt
    tex.srgb = _srgb_for(name, fmt, info)
    return tex


def load_texture_from_path(vpath: str, read_fn, oodle=None, uptnl: bool = True) -> Texture:
    """Convenience wrapper: read the package + bulk siblings through ``read_fn``.

    ``read_fn(vpath) -> bytes | None`` so it can be backed by the pak reader.
    """
    vpath = vpath.replace("\\", "/")
    stem = vpath.rsplit(".", 1)[0]
    uasset = read_fn(stem + ".uasset") or b""
    uexp = read_fn(stem + ".uexp")
    ubulk = read_fn(stem + ".ubulk")
    up = read_fn(stem + ".uptnl") if uptnl else None
    return load_texture(uasset, uexp, ubulk, stem + ".uasset", uptnl=up)


def save_png(tex: Texture, path: str) -> str:
    """Write a texture to ``path`` as 8 bit RGBA PNG."""
    if Image is None:
        raise RuntimeError("Pillow unavailable")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if tex.rgba is None:
        im = Image.new("RGBA", (max(1, tex.width), max(1, tex.height)), (0, 0, 0, 255))
    else:
        im = Image.fromarray(np.ascontiguousarray(tex.rgba, dtype=np.uint8), "RGBA")
    im.save(path)
    return path


def load_dds(data: bytes) -> np.ndarray | None:
    """Decode a DDS file (debug helper, uses Pillow)."""
    if Image is None:
        return None
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
        return np.asarray(im.convert("RGBA"), dtype=np.uint8)
    except Exception:
        return None


# The UI calls ``texture.save_png(path)``; core/types.py stays untouched.
if not hasattr(Texture, "save_png"):
    Texture.save_png = lambda self, path: save_png(self, path)  # type: ignore[attr-defined]
