"""Search game binaries for the AES keys (raw bytes or hex string)."""
import json
import os
import sys

KEYS = r"G:\xmcl-fetch\work\AESKey1.json"
BIN = r"G:\Game\Game\Game\Binaries\Win64"


def load_keys():
    keys = json.load(open(KEYS, encoding="utf-8"))
    out = [("MainKey", bytes.fromhex(keys["MainKey"][2:]))]
    for k in keys["Keys"]:
        out.append((k["guid"], bytes.fromhex(k["key"][2:])))
    return [kv for kv in out if len(kv[1]) == 32]


def main():
    keys = load_keys()
    print("keys", len(keys))
    targets = []
    for root, dirs, files in os.walk(BIN):
        for f in files:
            if f.lower().endswith((".exe", ".dll")):
                p = os.path.join(root, f)
                sz = os.path.getsize(p)
                if sz > 200_000:
                    targets.append((sz, p))
    targets.sort(reverse=True)
    for sz, p in targets[:8]:
        print(f"\nscanning {os.path.basename(p)} {sz/1e6:.1f}MB")
        with open(p, "rb") as f:
            data = f.read()
        low = data.lower()
        for name, kb in keys:
            hits = []
            i = data.find(kb)
            if i >= 0:
                hits.append(f"raw@{i:#x}")
            j = low.find(kb.hex().encode())
            if j >= 0:
                hits.append(f"hex@{j:#x}")
            if hits:
                print("   ", name, hits)
        # also look for the local XOR mask scheme hints
        for needle in (b"bEncryptedIndex", b"EncryptionKeyGuid", b"pakinternal", b"PakFile",
                       b"Oodle", b"aes", b"AES", b"AesKey"):
            c = data.count(needle)
            if c:
                print(f"    needle {needle!r} x{c}")


if __name__ == "__main__":
    main()
