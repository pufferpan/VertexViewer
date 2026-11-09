"""统计：每个枪托网格在官方预设里需要额外后移多少（cm），看是否稳定。"""
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
samples = {}
for des, nodes in desc.items():
    if str(des) not in bounds: continue
    uniq = {}
    for n in nodes:
        if n["idx"] is None: continue
        cur = uniq.get(n["idx"])
        if cur is None: uniq[n["idx"]] = dict(n)
        elif cur["pidx"] in (0, None) and n["pidx"] not in (0, None): uniq[n["idx"]] = dict(n)
    uniq = list(uniq.values())
    stocks = [n for n in uniq if n["psock"] == 3]
    if len(stocks) != 1 or len(uniq) < 3: continue
    if not all(V.mesh_of(item_mesh, n["item"]) for n in uniq): continue
    r = V.assemble_branch(uniq, sock, item_mesh, sid2name, cache)
    if not r: continue
    lo, hi = r
    ob, eb = bounds[str(des)]
    front_mine = hi[0] * 100; front_game = ob[1] + eb[1]
    if abs(front_mine - front_game) > 2.0:      # 前部对不上，说明不是枪托问题
        continue
    rear_mine = lo[0] * 100; rear_game = ob[1] - eb[1]
    key = V.mesh_of(item_mesh, stocks[0]["item"])
    samples.setdefault(key, []).append(rear_game - rear_mine)
print("stock meshes:", len(samples))
rows = []
for k, v in samples.items():
    v = np.array(v)
    rows.append((len(v), float(np.median(v)), float(v.std()), k.split("/")[-1]))
rows.sort(reverse=True)
for n, med, std, k in rows[:25]:
    print("n=%-4d med=%7.2f std=%5.2f  %s" % (n, med, std, k[:60]))
print("\nabs(med) < 1cm 的枪托数:", sum(1 for r in rows if abs(r[1]) < 1.0), "/", len(rows))
