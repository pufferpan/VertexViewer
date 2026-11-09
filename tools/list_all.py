"""Build a global file index across all DeltaForce paks."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.pak import PakFile, load_keyvault

PAK_DIR = r"G:\Game\Game\Game\Content\Paks"
VAULT = r"G:\xmcl-fetch\work\AESKey1.json"
OUT = r"G:\xmcl-fetch\work\fileindex.json"


def main():
    vault = load_keyvault(VAULT)
    files = {}
    info = {}
    paks = sorted(f for f in os.listdir(PAK_DIR) if f.endswith(".pak"))
    print(f"{len(paks)} paks, {len(vault)} keys")
    ok = fail = 0
    for i, name in enumerate(paks):
        p = os.path.join(PAK_DIR, name)
        try:
            with PakFile(p, vault) as pak:
                for rel, loc in pak.entries.items():
                    files[pak.mount_point + rel] = [name, loc]
                info[name] = pak.info()
                ok += 1
        except Exception as e:
            fail += 1
            print(f"  [{i}] {name}: {type(e).__name__} {e}")
        if (i + 1) % 50 == 0:
            print(f"  ...{i+1}/{len(paks)} ok={ok} fail={fail} entries={len(files)}")
    json.dump(files, open(OUT, "w", encoding="utf-8"))
    json.dump(info, open(r"G:\xmcl-fetch\work\pakinfo.json", "w", encoding="utf-8"), indent=1)
    print(f"ok={ok} fail={fail} total entries={len(files)} -> {OUT}")


if __name__ == "__main__":
    main()
