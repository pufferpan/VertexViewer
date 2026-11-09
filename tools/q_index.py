"""快速查询索引库（只读）：python tools/q_index.py "LIKE 模式" ..."""
import os
import sqlite3
import sys

p = os.path.join(os.environ["LOCALAPPDATA"], "VertexViewer", "index.db")
uri = "file:" + p.replace("\\", "/") + "?mode=ro"
c = sqlite3.connect(uri, uri=True)
print("db:", p, os.path.getsize(p))
print("assets:", c.execute("select count(*) from assets").fetchone(),
      "models:", c.execute("select count(*) from models").fetchone())

pats = sys.argv[1:] or ["%Socket%", "%Sock%", "%Attach%", "%GunPreset%",
                        "%PartTable%", "%WeaponPart%", "%GunMod%"]
for pat in pats:
    rows = c.execute("select vpath from assets where vpath like ? limit 200",
                     (pat,)).fetchall()
    print("==", pat, len(rows))
    for r in rows[:60]:
        print("   ", r[0])
