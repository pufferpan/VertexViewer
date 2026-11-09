"""Index the paks that `tools/list_all.py` never reached.

Writes `work/fileindex_extra.json` ({vpath: [pakname, location]}) so that
`core.loader.index()` (which merges fileindex.json + fileindex_extra.json)
sees the full game.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from core.pak import PakFile, load_keyvault  # noqa: E402

PAK_DIR = r"G:\Game\Game\Game\Content\Paks"
WORK = os.path.abspath(os.path.join(ROOT, "..", "work"))
IDX = os.path.join(WORK, "fileindex.json")
OUT = os.path.join(WORK, "fileindex_extra.json")
VAULT = os.path.join(WORK, "AESKey1.json")


def main():
    base = {}
    if os.path.exists(IDX):
        base = json.load(open(IDX, encoding="utf-8"))
    done_paks = {v[0] for v in base.values()}
    all_paks = [f for f in os.listdir(PAK_DIR) if f.lower().endswith(".pak")]
    todo = sorted(p for p in all_paks if p not in done_paks)
    print(f"{len(all_paks)} paks, {len(done_paks)} already indexed, {len(todo)} to go")

    extra = {}
    if os.path.exists(OUT):
        extra = json.load(open(OUT, encoding="utf-8"))

    vault = load_keyvault(VAULT)
    t0 = time.time()
    for i, name in enumerate(todo, 1):
        path = os.path.join(PAK_DIR, name)
        try:
            pak = PakFile(path, vault)
            info = pak.info()
            mount = pak.mount_point
            entries = pak.entries
            for rel, loc in entries.items():
                extra[mount + rel] = [name, loc]
            print(f"[{i}/{len(todo)}] {name}: {len(entries)} files "
                  f"({info.get('key')}, mask=0x{info.get('mask', 0):02x}) "
                  f"{time.time() - t0:.0f}s")
            pak.close()
        except Exception as exc:                                   # noqa: BLE001
            print(f"[{i}/{len(todo)}] {name}: FAILED {exc}")
        if i % 5 == 0:
            json.dump(extra, open(OUT, "w", encoding="utf-8"))

    json.dump(extra, open(OUT, "w", encoding="utf-8"))
    print(f"done: {len(extra)} extra entries -> {OUT}")


if __name__ == "__main__":
    main()
