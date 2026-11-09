"""把一个分类下的资产列出来（名字 + 路径），挑分类规则时用。

用法： python tools/list_cat.py 容器 [数量]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import cnnames, loader  # noqa: E402

CAT = sys.argv[1] if len(sys.argv) > 1 else "容器"
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 25

seen = {}
for p in loader.index():
    norm = p.replace("\\", "/")
    if "/models/" not in norm.lower() or not norm.lower().endswith(".uasset"):
        continue
    if cnnames.category_of(p) != CAT:
        continue
    stem = norm.split("/")[-1][:-7]
    for suf in ("_1P_HD", "_3P_HD", "_LAY_HD", "_1P", "_3P", "_UI", "_LAY", "_HD"):
        if stem.endswith(suf):
            stem = stem[: -len(suf)]
            break
    if stem in seen:
        continue
    seen[stem] = (cnnames.lookup(p) or {}).get("cn", "")

print(f"{CAT}: {len(seen)} 唯一资产")
for k, v in list(seen.items())[:LIMIT]:
    print(f"  {v or '-':16s} {k}")
