"""批量对比：40 个预设，逐件找偏差最大的部件。"""
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
for _p in (os.path.join(BASE, "work"), os.path.join(BASE, "tools")):
    if _p not in sys.path: sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import verify_assembly as V
from core import loader

sock, item_mesh, sid2name, desc, bounds = V.load_tables()
cache = {}
rows = []
for des, nodes in desc.items():
    if str(des) not in bounds: continue
    if not all(V.mesh_of(item_mesh, n["item"]) for n in nodes): continue
    uniq = {}
    for n in nodes:
        if n["idx"] is None: continue
        cur = uniq.get(n["idx"])
        if cur is None: uniq[n["idx"]] = dict(n)
        elif cur["pidx"] in (0, None) and n["pidx"] not in (0, None): uniq[n["idx"]] = dict(n)
    r = V.assemble_branch(list(uniq.values()), sock, item_mesh, sid2name, cache)
    if not r: continue
    lo, hi = r
    ob, eb = bounds[str(des)]
    ue_lo = np.array([-hi[2], lo[0], lo[1]]) * 100
    ue_hi = np.array([-lo[2], hi[0], hi[1]]) * 100
    o = (ue_lo + ue_hi) / 2; e = (ue_hi - ue_lo) / 2
    d = max(float(np.abs(o - ob).max()), float(np.abs(e - eb).max()))
    rows.append((d, des, len(uniq), ob, eb, o, e, sorted({sid2name.get(n["psock"]) for n in uniq.values()} - {None})))
    if len(rows) >= 40: break
rows.sort()
for d, des, n, ob, eb, o, e, s in rows:
    tag = "OK " if d < 1.5 else "BAD"
    print("%s d=%5.2f des=%-12s n=%d game_o=%s game_e=%s mine_o=%s mine_e=%s"
          % (tag, d, des, n, np.round(ob, 1), np.round(eb, 1), np.round(o, 1), np.round(e, 1)))
bad = [r for r in rows if r[0] >= 1.5]
print("\nBAD %d / %d" % (len(bad), len(rows)))
