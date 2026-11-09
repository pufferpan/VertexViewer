"""Try several plaintext-mask periodicities to crack the pak index head."""
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


def unmask(b: bytes, period: int, mask: bytes) -> bytes:
    return bytes(b[i] ^ mask[i % period] for i in range(len(b)))


def validate(plain: bytes):
    if len(plain) < 24:
        return None
    seed, = struct.unpack_from("<Q", plain, 0)
    if seed != 0:
        return None
    cnt, = struct.unpack_from("<i", plain, 8)
    if not (0 < cnt <= 5_000_000):
        return None
    n, = struct.unpack_from("<i", plain, 12)
    if not (2 <= n <= 4096) or 16 + n > len(plain):
        return None
    raw = plain[16:16 + n - 1]
    try:
        mp = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not all(32 <= ord(c) < 127 for c in mp):
        return None
    return cnt, mp


def main():
    keys = load_keys()
    paks = sorted((os.path.join(PAK_DIR, f) for f in os.listdir(PAK_DIR) if f.endswith(".pak")),
                  key=lambda p: -os.path.getsize(p))
    for pak in paks[:3]:
        size = os.path.getsize(pak)
        with open(pak, "rb") as f:
            f.seek(size - 204)
            footer = f.read(204)
            _m, _v, ioff, isz = struct.unpack_from("<IIqq", footer, 0)
            f.seek(ioff)
            head = f.read(512)
        print(f"\n{os.path.basename(pak)} {isz}")
        for name, key in keys[:60]:
            dec = AES.new(key, AES.MODE_ECB).decrypt(head[:64])
            for period in (1, 2, 4, 8):
                mask = dec[:period]
                plain = unmask(dec, period, mask)
                r = validate(plain)
                if r:
                    print(f"  *** {name} period={period} files={r[0]} mount={r[1]!r}")
        # also print zero-run stats for MainKey
        dec = AES.new(keys[0][1], AES.MODE_ECB).decrypt(head[:64])
        print("  MainKey dec[:16]:", dec[:16].hex(" "))


if __name__ == "__main__":
    main()
