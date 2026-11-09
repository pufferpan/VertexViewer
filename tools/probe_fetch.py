"""Fetch a uasset trio (uasset/uexp/ubulk) from the pak into work/probe/.

Usage: python tools/probe_fetch.py <vpath.uasset> [...]
       python tools/probe_fetch.py --tag mag <vpath.uasset>
Writes work/probe/<tag>/{uasset,uexp,ubulk}.bin and prints sizes.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.pak import PakFile, load_keyvault  # noqa: E402
from tools.pakpick import oodle  # noqa: E402

PAK_DIR = r"G:\Game\Game\Game\Content\Paks"
VAULT = r"G:\xmcl-fetch\work\AESKey1.json"
IDX = r"G:\xmcl-fetch\work\fileindex.json"
OUT = os.path.join(ROOT, "..", "work", "probe")


def index():
    p = [IDX, os.path.join(ROOT, "..", "work", "fileindex_extra.json")]
    merged = {}
    for f in p:
        if os.path.exists(f):
            with open(f, encoding="utf-8") as fh:
                merged.update(json.load(fh))
    return merged


def fetch(idx, vpath, vault, tag):
    base, ext = os.path.splitext(vpath)
    d = os.path.join(OUT, tag)
    os.makedirs(d, exist_ok=True)
    got = {}
    for kind, suffix in (("uasset", ext), ("uexp", ".uexp"), ("ubulk", ".ubulk"), ("uptnl", ".uptnl")):
        vp = base + suffix
        if vp not in idx:
            continue
        pakname = idx[vp][0]
        with PakFile(os.path.join(PAK_DIR, pakname), vault) as pak:
            data = pak.read(vp, oodle())
        if kind == "uasset":
            data = data  # header file; do not concat anything
        open(os.path.join(d, kind + ".bin"), "wb").write(data)
        got[kind] = len(data)
    open(os.path.join(d, "vpath.txt"), "w", encoding="utf-8").write(vpath)
    return got


def main(argv):
    tag = "t"
    if argv and argv[0] == "--tag":
        tag = argv[1]
        argv = argv[2:]
    idx = index()
    vault = load_keyvault(VAULT)
    for vpath in argv:
        if vpath not in idx and ("../../../" + vpath) in idx:
            vpath = "../../../" + vpath
        missing = [vpath] if vpath not in idx else []
        if missing:
            print("MISSING", vpath)
            continue
        got = fetch(idx, vpath, vault, tag)
        print(tag, got)


if __name__ == "__main__":
    main(sys.argv[1:])
