"""Search the pak trailer for any known encryption GUID from AESKey1.json."""
import json
import os
import struct

from Crypto.Cipher import AES

PAK_DIR = r"G:\Game\Game\Game\Content\Paks"
KEYS = r"G:\xmcl-fetch\work\AESKey1.json"
MAGIC = b"\xe1\x12\x6f\x5a"


def main():
    keys = json.load(open(KEYS, encoding="utf-8"))
    main_key = bytes.fromhex(keys["MainKey"][2:])
    # guid hex string -> key bytes ; also reversed byte order variant
    guids = {}
    for k in keys["Keys"]:
        g = k["guid"].upper()
        kb = bytes.fromhex(g)
        guids[g] = bytes.fromhex(k["key"][2:])
    print("guids loaded", len(guids))

    paks = sorted((os.path.join(PAK_DIR, f) for f in os.listdir(PAK_DIR) if f.endswith(".pak")),
                  key=lambda p: -os.path.getsize(p))
    for pak in paks[:8]:
        n = os.path.getsize(pak)
        with open(pak, "rb") as f:
            f.seek(n - 512)
            tail = f.read()
        pos = tail.rfind(MAGIC)
        print(f"\n{os.path.basename(pak)}  size={n}  magic_rel_eof={n-512+pos}")
        hit = False
        for g, kb in guids.items():
            if kb in tail:
                print("   GUID FOUND (raw bytes):", g, "at", n - 512 + tail.find(kb))
                hit = True
            if bytes.fromhex(g)[::-1] in tail:
                print("   GUID FOUND (reversed):", g, "at", n - 512 + tail.find(bytes.fromhex(g)[::-1]))
                hit = True
        if not hit:
            print("   no known guid in last 512 bytes")
        # print structure again, clean
        ver, = struct.unpack_from("<i", tail, pos + 4)
        off, size = struct.unpack_from("<qq", tail, pos + 8)
        sha = tail[pos + 24:pos + 44]
        print(f"   ver={ver} off={off} size={size} sha={sha.hex()}")
        rest = tail[pos + 44:]
        print(f"   after_sha({len(rest)}B): {rest[:40].hex(' ')}  {rest[:16]!r}")


if __name__ == "__main__":
    main()
