"""分析某个 DesId 的节点树：每件的 socket、父件、局部变换，用来解释偏差。"""
import os, sys, struct
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
for _p in (os.path.join(BASE, "work"), os.path.join(BASE, "tools")):
    if _p not in sys.path: sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import verify_assembly as V
from core import loader

des = int(sys.argv[1])
sock, item_mesh, sid2name, desc, bounds = V.load_tables()
nodes = desc[des]
print("DesId", des, "nodes", len(nodes))
for n in nodes:
    mesh = V.mesh_of(item_mesh, n["item"])
    sm = sid2name.get(n["psock"])
    names = sock.get(mesh, ([], [], []))[0] if mesh else []
    loc = ""
    if mesh and sm in names:
        k = names.index(sm)
        loc = " loc=%s rot=%s" % (np.round(sock[mesh][1][k], 2), np.round(sock[mesh][2][k], 1))
    print(" idx=%-2s pidx=%-2s item=%-12s sock=%-18s mesh=%-46s sockets=%d%s"
          % (n["idx"], n["pidx"], n["item"], sm, (mesh or "-")[:46], len(names), loc))
