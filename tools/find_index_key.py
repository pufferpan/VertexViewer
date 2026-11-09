"""Find which key/transform yields a valid pak index for a given pak."""
import json
import struct
import sys
import os

from Crypto.Cipher import AES

PAK = r"G:\Game\Game\Game\Content\Paks\pak-0-2-pakchunk227-WindowsClient.pak"


def plausible(first16: bytes) -> str | None:
    if len(first16) < 8:
        return None
    n, = struct.unpack_from("<i", first16, 0)
    if not (1 <= n <= 2000):
        return None
    body = first16[4:4 + n]
    if len(body) != n:
        return None
    try:
        s = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if all(32 <= ord(c) < 127 for c in s) and ("/" in s or s.endswith(".")):
        return s
    return None


def main():
    keys = json.load(open(r"G:\xmcl-fetch\work\AESKey1.json", encoding="utf-8"))
    main_key = bytes.fromhex(keys["MainKey"][2:])
    kmap = {k["guid"].upper(): bytes.fromhex(k["key"][2:]) for k in keys["Keys"]}

    n = os.path.getsize(PAK)
    with open(PAK, "rb") as f:
        f.seek(n - 204 - 96)
        d = f.read()
        pos = d.rfind(b"\xe1\x12\x6f\x5a")
        ver, = struct.unpack_from("<i", d, pos + 4)
        off, size = struct.unpack_from("<qq", d, pos + 8)
        sha = d[pos + 28:pos + 48]
        after = d[pos + 48:pos + 76]
        print("ver", ver, "off", off, "size", size)
        print("sha", sha.hex())
        print("after hash:", after.hex(" "), after[:8])
        f.seek(off)
        idx = f.read(64)
    print("raw index:", idx.hex(" "))
    cands = [("main", main_key)] + [(g, k) for g, k in kmap.items()]
    for name, k in cands:
        if len(k) != 32:
            continue
        dec = AES.new(k, AES.MODE_ECB).decrypt(idx[:64])
        p = plausible(dec[:32])
        if p:
            print(f"*** {name} -> {p!r}")
        print(f"    {name[:8]} {dec[:24].hex()}")
    # also try raw
    p = plausible(idx[:32])
    print("raw plausible:", p)


if __name__ == "__main__":
    main()
