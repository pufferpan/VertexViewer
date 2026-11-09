"""Fast regex scan of fileindex.json for texture / material virtual paths."""
import re
import sys
import json

IDX = r"G:\xmcl-fetch\work\fileindex.json"

raw = open(IDX, "rb").read()

pat = re.compile(rb'"([^"]*(?:Textures/|/M_|Material)[^"]*)"\s*:\s*\[\s*"([^"]+)"\s*,\s*(\d+)\s*\]')

tex, mat = [], []
for m in pat.finditer(raw):
    p = m.group(1).decode("utf-8", "replace")
    if "/Textures/" in p and p.endswith(".uasset"):
        tex.append(p)
    elif p.endswith(".uasset") and ("/M_" in p or "MI_" in p):
        mat.append(p)

print("textures:", len(tex), "materials:", len(mat))
json.dump(tex, open(r"G:\xmcl-fetch\vertexviewer\tools\_tex_paths.json", "w"), indent=0)
json.dump(mat, open(r"G:\xmcl-fetch\vertexviewer\tools\_mat_paths.json", "w"), indent=0)

print("\n-- 10 textures --")
for p in tex[:10]:
    print(p)
print("\n-- 10 materials --")
for p in mat[:10]:
    print(p)

# distribution of texture filename suffixes
import collections
c = collections.Counter()
for p in tex:
    name = p.rsplit("/", 1)[-1]
    mm = re.match(r"T_VMGen_([A-Za-z0-9]+)Map_", name)
    c[mm.group(1) if mm else name.split("_")[1:2][0] if "_" in name else name] += 1
print("\n-- name suffix distribution top30 --")
for k, v in c.most_common(30):
    print(f"{v:7d}  {k}")
