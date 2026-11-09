"""把枪托逐个别挂到机匣的 42 个 socket 上，看哪个能复现官方包围盒后端。"""
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
des = int(sys.argv[1])
uniq = {}
for n in desc[des]:
    cur = uniq.get(n["idx"])
    if cur is None: uniq[n["idx"]] = dict(n)
    elif cur["pidx"] in (0, None) and n["pidx"] not in (0, None): uniq[n["idx"]] = dict(n)
uniq = list(uniq.values())
ob, eb = bounds[str(des)]
stock = [n for n in uniq if n["psock"] == 3][0]
rec = [n for n in uniq if n["pidx"] in (0, None)][0]
recmesh = V.mesh_of(item_mesh, rec["item"])
names, locs, rots = sock[recmesh]
print("game rear y=%.1f  front y=%.1f" % (ob[1]-eb[1], ob[1]+eb[1]))
sid3 = stock["psock"]
orig = sid2name[sid3]
best = []
for k, nm in enumerate(names):
    # 直接改 sock 表里的位置：把 Sto 的名字临时指向该 socket
    sid2name[sid3] = nm
    if nm in names:
        idx = names.index(nm)
        # 用索引而不是名字：临时把 Sto_point 的数据换成第 idx 个 socket 的
        saved = sock[recmesh]
        sock[recmesh] = (["Sto_point"], [locs[idx]], [rots[idx]])
        r = V.assemble_branch(uniq, sock, item_mesh, sid2name, cache)
        sock[recmesh] = saved
        if r:
            best.append((r[0][0]*100, nm))
sid2name[sid3] = orig
best.sort()
for y, nm in best[:6] + best[-3:]:
    print("  rear y=%8.2f  via %-24s%s" % (y, nm, "  <== match" if abs(y-(ob[1]-eb[1])) < 0.6 else ""))
