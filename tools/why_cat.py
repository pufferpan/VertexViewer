"""看某个资产为什么被分到这个类别（打印命中的规则线索）。

用法： python tools/why_cat.py <资产名片段>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import cnnames, loader  # noqa: E402

NEEDLE = (sys.argv[1] if len(sys.argv) > 1 else "").lower()

for p in loader.index():
    norm = p.replace("\\", "/")
    if "/models/" not in norm.lower() or not norm.lower().endswith(".uasset"):
        continue
    stem = norm.split("/")[-1][:-7]
    if NEEDLE and NEEDLE not in stem.lower() and NEEDLE not in norm.lower():
        continue
    cn = (cnnames.lookup(p) or {}).get("cn", "")
    cat = cnnames.category_of(p)
    low = "/" + norm.lower()
    hits = [w for w in cnnames._CONTAINER_WORDS if w in low]
    print(f"{cat:6s} {cn or '-':16s} {stem}")
    print(f"       hits={hits}")
