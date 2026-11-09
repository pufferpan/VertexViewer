"""试探：把枪托挂到不同 socket 上，看哪个能复现官方包围盒的后端。"""
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
nodes = desc[des]
uniq = {}
for n in nodes:
    cur = uniq.get(n["idx"])
    if cur is None: uniq[n["idx"]] = dict(n)
    elif cur["pidx"] in (0, None) and n["pidx"] not in (0, None): uniq[n["idx"]] = dict(n)
uniq = list(uniq.values())
ob, eb = bounds[str(des)]
print("game   y=[%.1f %.1f]" % (ob[1]-eb[1], ob[1]+eb[1]))
# 找枪托节点 + 它的父件（机匣）可用 socket
stock = [n for n in uniq if n["psock"] in (3,)]
rec = [n for n in uniq if n["pidx"] in (0, None)]
recmesh = V.mesh_of(item_mesh, rec[0]["item"]) if rec else None
cands = [nm for nm in sock.get(recmesh, ([], [], []))[0] if "point" in nm.lower()]
cur = sid2name.get(3)
for cand in [cur] + cands:
    if not stock: break
    stock[0]["psock"] = next((k for k, v in sid2name.items() if v == cand), None)
    r = V.assemble_branch(uniq, sock, item_mesh, sid2name, cache)
    if not r: continue
    lo, hi = r
    print("  %-28s y=[%.1f %.1f]" % (cand, lo[0]*100, hi[0]*100))
