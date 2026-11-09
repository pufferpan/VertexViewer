"""打印若干 DesId 每个节点的 TuneIds/TuneValues，找枪托伸缩参数。"""
import os, sys, struct
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
for _p in (os.path.join(BASE, "work"), os.path.join(BASE, "tools")):
    if _p not in sys.path: sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import verify_assembly as V
from core import loader
import dtparse, mini_upk as mu

DESC = V.DESC
ua = loader.read_entry(DESC); ue = loader.read_entry(DESC[:-7] + ".uexp")
upk = mu.Upk(ua, ue); data = upk.export_data(upk.exports[0])
rows, _e, _n = dtparse.walk(data, upk.names)
names = upk.names

def prop(props, key):
    for name, typ, size, aidx, vs, vl in props:
        if name == key: return typ, vs, vl
    return None, 0, 0

def int_arr(props, key):
    typ, vs, vl = prop(props, key)
    if typ is None: return []
    cnt = struct.unpack_from("<i", data, vs)[0]
    # array of int32: 1 tag(49) + count... 用 size 推算
    body = vs + 4
    if vl >= 53 + 4 * cnt: body = vs + 53
    return struct.unpack_from("<%di" % cnt, data, body)

want = {int(a) for a in sys.argv[1:]}
for rn, props in rows:
    typ, vs, vl = prop(props, "DesId")
    des = struct.unpack_from("<Q", data, vs)[0]
    if des not in want: continue
    idx = struct.unpack_from("<h", data, prop(props, "Index")[1])[0]
    ps = struct.unpack_from("<I", data, prop(props, "ParentSocketId")[1])[0]
    item = struct.unpack_from("<Q", data, prop(props, "ItemId")[1])[0]
    ti = int_arr(props, "TuneIds"); tv = int_arr(props, "TuneValues")
    if ps == 3 or ti:
        print("des=%s idx=%s psock=%s item=%s tuneIds=%s tuneVals=%s" % (des, idx, ps, item, ti, tv))
