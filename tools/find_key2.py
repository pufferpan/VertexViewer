"""Find which AESKey1.json key decrypts each pak index (AES-256-ECB + 1-byte XOR mask)."""
import json
import os
import struct
import sys

from Crypto.Cipher import AES

PAK_DIR = r"G:\Game\Game\Game\Content\Paks"
KEYS = r"G:\xmcl-fetch\work\AESKey1.json"


def load_keys():
    keys = json.load(open(KEYS, encoding="utf-8"))
    out = [("MainKey", bytes.fromhex(keys["MainKey"][2:]))]
    for k in keys["Keys"]:
        out.append((k["guid"], bytes.fromhex(k["key"][2:])))
    return [kv for kv in out if len(kv[1]) == 32]


def check(dec: bytes, total: int):
    """Return (mask, filecount, mountpoint) if this looks like a valid index head."""
    if len(dec) < 16:
        return None
    if len(set(dec[:4])) != 1:
        return None
    mask = dec[0]
    plain = bytes(b ^ mask for b in dec)
    seed, = struct.unpack_from("<Q", plain, 0)
    cnt, = struct.unpack_from("<i", plain, 8)
    if seed != 0 or not (0 < cnt <= 5_000_000):
        return None
    n, = struct.unpack_from("<i", plain, 12)
    if not (1 <= n <= 4096):
        return None
    if 12 + 4 + n > len(plain):
        return None
    try:
        mp = plain[16:16 + n - 1].decode("utf-8")
    except UnicodeDecodeError:
        return None
    return mask, cnt, mp


def main():
    keys = load_keys()
    print("candidate keys:", len(keys))
    paks = sorted((os.path.join(PAK_DIR, f) for f in os.listdir(PAK_DIR) if f.endswith(".pak")),
                  key=lambda p: -os.path.getsize(p))
    targets = paks[:int(sys.argv[1]) if len(sys.argv) > 1 else 6]
    for pak in targets:
        size = os.path.getsize(pak)
        with open(pak, "rb") as f:
            f.seek(size - 204)
            footer = f.read(204)
            magic, ver, ioff, isz = struct.unpack_from("<IIqq", footer, 0)
            f.seek(ioff)
            head = f.read(64)
        print(f"\n{os.path.basename(pak)} idx=({ioff},{isz}) magic={magic:08X} ver={ver}")
        found = 0
        for name, key in keys:
            dec = AES.new(key, AES.MODE_ECB).decrypt(head[:32])
            r = check(dec, size)
            if r:
                print(f"   *** MATCH key={name} mask=0x{r[0]:02x} files={r[1]} mount={r[2]!r}")
                found += 1
                if found >= 3:
                    break
        if not found:
            # report best-effort diagnostics for MainKey
            dec = AES.new(keys[0][1], AES.MODE_ECB).decrypt(head[:32])
            print(f"   no match; MainKey dec heads: {dec[:12].hex(' ')}")


if __name__ == "__main__":
    main()
