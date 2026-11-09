"""Grab a .uasset + .uexp + .ubulk triple from the paks into work/samples/."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.pak import PakFile, load_keyvault
from tools.pakpick import oodle, PAK_DIR, VAULT, IDX, Oodle

OUT = r"G:\xmcl-fetch\work\samples"
os.makedirs(OUT, exist_ok=True)

_vault = None
_paks = {}


def _get_pak(name):
    global _vault
    pak = _paks.get(name)
    if pak is None:
        if _vault is None:
            _vault = load_keyvault(VAULT)
        pak = PakFile(os.path.join(PAK_DIR, name), _vault)
        _paks[name] = pak
    return pak


def fetch(vpath: str) -> bytes | None:
    idx = _IDX
    ent = idx.get(vpath)
    if not ent:
        return None
    return _get_pak(ent[0]).read(vpath, oodle())


_IDX = json.load(open(IDX, encoding="utf-8"))


def grab(vpath: str) -> dict:
    """Fetch uasset/uexp/ubulk for `vpath` (must end in .uasset)."""
    base = vpath[:-len(".uasset")]
    out = {}
    for ext in (".uasset", ".uexp", ".ubulk"):
        p = base + ext
        if p not in _IDX:
            out[ext] = None
            continue
        data = fetch(p)
        out[ext] = data
        if data is not None:
            fn = os.path.join(OUT, p.rsplit("/", 1)[-1])
            open(fn, "wb").write(data)
    return out


if __name__ == "__main__":
    for vp in sys.argv[1:]:
        d = grab(vp)
        print(vp)
        for k, v in d.items():
            print("   ", k, len(v) if v else None)
