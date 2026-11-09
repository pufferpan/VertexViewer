"""Recon: parse DeltaForce pak footer + index, try AES keys from AESKey1.json."""
import json
import struct
import sys
from pathlib import Path

MAGIC = 0x5A6F12E1
PAK_DIR = Path(r"G:\Game\Game\Game\Content\Paks")


def footer(buf: bytes):
    pos = buf.rfind(struct.pack("<I", MAGIC))
    if pos < 0:
        return None
    ver, = struct.unpack_from("<i", buf, pos + 4)
    off, size = struct.unpack_from("<qq", buf, pos + 8)
    sha = buf[pos + 28:pos + 48]
    enc = buf[pos + 48]
    guid = buf[pos + 49:pos + 65]
    frozen = buf[pos + 65] if pos + 65 < len(buf) else 0
    return dict(ver=ver, off=off, size=size, sha=sha.hex(), enc=enc,
                guid=guid.hex().upper(), frozen=frozen, footer_pos=pos)


def main():
    keys = json.load(open(r"G:\xmcl-fetch\work\AESKey1.json", encoding="utf-8"))
    main_key = bytes.fromhex(keys["MainKey"][2:])
    kmap = {k["guid"].upper(): bytes.fromhex(k["key"][2:]) for k in keys["Keys"]}

    paks = sorted(PAK_DIR.glob("*.pak"))
    print(f"{len(paks)} paks")
    # small ones first for speed
    paks.sort(key=lambda p: p.stat().st_size)
    for p in paks[:6]:
        with open(p, "rb") as f:
            f.seek(0, 2)
            fsize = f.tell()
            f.seek(max(0, fsize - 4096))
            tail = f.read()
        ft = footer(tail)
        if not ft:
            print(p.name, "NO MAGIC")
            continue
        print(f"{p.name} size={p.stat().st_size/1e6:.1f}MB ver={ft['ver']} enc={ft['enc']} "
              f"guid={ft['guid']} frozen={ft['frozen']} idx=({ft['off']},{ft['size']})")
        print("   guid in map:", ft["guid"] in kmap, " idx_aligned:", ft["size"] % 16)


if __name__ == "__main__":
    main()
