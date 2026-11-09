"""Recon 2: real (big) paks, footer + index decrypt test."""
import json
import struct
import sys
from pathlib import Path

MAGIC = b"\xE1\x12\x6F\x5A"
PAK_DIR = Path(r"G:\Game\Game\Game\Content\Paks")


def parse_footer(tail: bytes, filesize: int):
    pos = tail.rfind(MAGIC)
    while pos >= 0:
        try:
            ver, = struct.unpack_from("<i", tail, pos + 4)
            off, size = struct.unpack_from("<qq", tail, pos + 8)
            if 4 <= ver <= 12 and 0 < size < filesize and 0 <= off < filesize:
                sha = tail[pos + 28:pos + 48]
                enc = tail[pos + 48]
                guid = tail[pos + 49:pos + 65]
                return dict(ver=ver, off=off, size=size, sha=sha.hex(), enc=enc,
                            guid=guid.hex().upper(), pos=pos)
        except struct.error:
            pass
        pos = tail.rfind(MAGIC, 0, pos)
    return None


def main():
    keys = json.load(open(r"G:\xmcl-fetch\work\AESKey1.json", encoding="utf-8"))
    main_key = bytes.fromhex(keys["MainKey"][2:])
    kmap = {k["guid"].upper(): bytes.fromhex(k["key"][2:]) for k in keys["Keys"]}
    print("main_key len", len(main_key), "known guids", len(kmap))

    paks = sorted(PAK_DIR.glob("*.pak"), key=lambda p: -p.stat().st_size)
    for p in paks[:4]:
        fsize = p.stat().st_size
        with open(p, "rb") as f:
            f.seek(max(0, fsize - 2048))
            tail = f.read()
        ft = parse_footer(tail, fsize)
        if not ft:
            print(p.name, "no footer", fsize)
            continue
        print(f"\n{p.name} {fsize/1e6:.0f}MB ver={ft['ver']} enc={ft['enc']} "
              f"guid={ft['guid']} idx=({ft['off']},{ft['size']}) frozen_byte={tail[ft['pos']+65:ft['pos']+70].hex()}")
        print("   guid known:", ft["guid"] in kmap)
        # read index bytes
        with open(p, "rb") as f:
            f.seek(ft["off"])
            idx = f.read(ft["size"])
        print("   idx magic(raw):", idx[:4].hex(), "len", len(idx))
        cands = {"main": main_key}
        if ft["guid"] in kmap:
            cands["guidkey"] = kmap[ft["guid"]]
        for name, k in cands.items():
            if len(k) != 32:
                print("   ", name, "bad key len", len(k))
                continue
            try:
                from Crypto.Cipher import AES
                dec = AES.new(k, AES.MODE_ECB).decrypt(idx[: (len(idx) // 16) * 16]) + idx[(len(idx) // 16) * 16:]
            except Exception as e:
                print("   ", name, "aes fail", e)
                continue
            s = dec[:64]
            print(f"   [{name}] {s.hex()}")
            print(f"        ascii: {''.join(chr(c) if 32 <= c < 127 else '.' for c in s)}")


if __name__ == "__main__":
    main()
