"""列出某个干员（Hero_HD）下的骨骼模型，以及他皮肤目录里的模型。"""
import os
import re
import sqlite3
import sys

DB = os.path.expandvars(r"%LOCALAPPDATA%\VertexViewer\index.db")
con = sqlite3.connect(DB)
cur = con.cursor()

who = sys.argv[1] if len(sys.argv) > 1 else "m_kai"
pat = f"%hero_hd/{who}%"
rows = [v for (v,) in cur.execute(
    "select vpath from assets where vpath like '%.uasset' and lower(vpath) like ?", (pat,))]
print(f"== hero_hd/{who} 共 {len(rows)} 个 uasset ==")
mesh = [v for v in rows if re.search(r"/(SKM|SK|Chara|Body)", v, re.I)]
for v in sorted(mesh)[:40]:
    print("   ", v.split("Content/")[-1])
print(f"   ... mesh 类 {len(mesh)}")

skins = {}
for v in rows:
    m = re.search(r"Hero_HD/[^/]+/([^/]+)/", v, re.I)
    if m:
        skins.setdefault(m.group(1), 0)
        skins[m.group(1)] += 1
print("\n== 皮肤目录 ==")
for k, n in sorted(skins.items(), key=lambda kv: -kv[1])[:20]:
    print(f"{n:5d}  {k}")
