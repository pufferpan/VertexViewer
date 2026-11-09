"""批量对比：只取 >=4 个节点的预设，按偏差排序，并打印最大偏差的方向。"""
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
for _p in (os.path.join(BASE, "work"), os.path.join(BASE, "tools")):
    if _p not in sys.path: sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import verify_assembly as V

sock, item_mesh, sid2name, desc, bounds = V.load_tables()
cache = {}
rows = []
for des, nodes in desc.items():
    if str(des) not in bounds: continue
    uniq = {}
    for n in nodes:
        if n["idx"] is None: continue
        cur = uniq.get(n["idx"])
        if cur is None: uniq[n["idx"]] = dict(n)
        elif cur["pidx"] in (0, None) and n["pidx"] not in (0, None): uniq[n["idx"]] = dict(n)
    uniq = list(uniq.values())
    if len(uniq) < 4: continue
    if not all(V.mesh_of(item_mesh, n["item"]) for n in uniq): continue
    r = V.assemble_branch(uniq, sock, item_mesh, sid2name, cache)
    if not r: continue
    lo, hi = r
    ob, eb = bounds[str(des)]
    ue_lo = np.array([-hi[2], lo[0], lo[1]]) * 100
    ue_hi = np.array([-lo[2], hi[0], hi[1]]) * 100
    o = (ue_lo + ue_hi) / 2; e = (ue_hi - ue_lo) / 2
    d = max(float(np.abs(o - ob).max()), float(np.abs(e - eb).max()))
    items = []
    for n in uniq:
        m = V.mesh_of(item_mesh, n["item"]) or "?"
        items.append("%s@%s" % (m.split("/")[-1].replace("models/weapons/parts/", ""), sid2name.get(n["psock"]) or "root"))
    rows.append((d, des, len(uniq), ob, eb, o, e, items))
    if len(rows) >= 120: break
rows.sort()
ok = [r for r in rows if r[0] < 1.5]
print("OK %d / %d  (threshold 1.5cm)" % (len(ok), len(rows)))
for d, des, n, ob, eb, o, e, items in rows[-8:]:
    print("BAD d=%5.2f des=%-12s n=%d\n    game_o=%s game_e=%s\n    mine_o=%s mine_e=%s\n    parts=%s"
          % (d, des, n, np.round(ob, 1), np.round(eb, 1), np.round(o, 1), np.round(e, 1), items))
