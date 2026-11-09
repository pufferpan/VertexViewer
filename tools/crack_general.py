"""General index cracker: known keys x 256 single-byte masks x two layouts."""
import json
import os
import struct

from Crypto.Cipher import AES

PAK_DIR = r"G:\Game\Game\Game\Content\Paks"
KEYS = r"G:\xmcl-fetch\work\AESKey1.json"


def load_keys():
    keys = json.load(open(KEYS, encoding="utf-8"))
    out = [("MainKey", bytes.fromhex(keys["MainKey"][2:]))]
    for k in keys["Keys"]:
        out.append((k["guid"], bytes.fromhex(k["key"][2:])))
    return [kv for kv in out if len(kv[1]) == 32]


def try_layout(p: bytes, idxsize: int):
    """Return description if `p` starts a plausible pak index."""
    # layout A: u64 seed, u32 count, FString mount
    # layout B: FString mount, u32 count
    for variant in ("A", "B"):
        o = 0
        if variant == "A":
            if len(p) < 12:
                continue
            seed, = struct.unpack_from("<Q", p, 0)
            if seed != 0:
                continue
            o = 8
        cnt, = struct.unpack_from("<i", p, o)
        if not (0 < cnt <= 5_000_000):
            continue
        o += 4
        n, = struct.unpack_from("<i", p, o)
        if not (2 <= n <= 512) or o + 4 + n > len(p):
            continue
        raw = p[o + 4:o + 4 + n - 1]
        try:
            mp = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if not all(32 <= ord(c) < 127 for c in mp):
            continue
        if "/" not in mp and "\\" not in mp and ".." not in mp:
            continue
        return f"layout{variant} count={cnt} mount={mp!r}"
    return None


def main():
    keys = load_keys()
    paks = sorted((os.path.join(PAK_DIR, f) for f in os.listdir(PAK_DIR) if f.endswith(".pak")),
                  key=lambda p: -os.path.getsize(p))
    for pak in paks[:3]:
        size = os.path.getsize(pak)
        with open(pak, "rb") as f:
            f.seek(size - 204)
            foot = f.read(204)
            ioff, isz = struct.unpack_from("<qq", foot, 8)
            f.seek(ioff)
            head = f.read(256)
        print(f"\n{os.path.basename(pak)} isz={isz} head={head[:16].hex()}")
        hits = 0
        for name, key in keys:
            dec = AES.new(key, AES.MODE_ECB).decrypt(head[:64])
            for mask in range(256):
                p = bytes(b ^ mask for b in dec[:64])
                r = try_layout(p, isz)
                if r:
                    print(f"  *** {name} mask=0x{mask:02x} {r}")
                    hits += 1
            if hits > 4:
                break
        if not hits:
            print("  no hit with AES keys")
            for mask in range(256):
                p = bytes(b ^ mask for b in head[:64])
                r = try_layout(p, isz)
                if r:
                    print(f"  raw mask=0x{mask:02x} {r}")
                    break


if __name__ == "__main__":
    main()
