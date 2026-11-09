"""验证脚本：用 GunDescTable + WeaponPartsMeshSocketNameInfo + PartSocketsTable 拼枪，
和 GunPresetBoundsTable 里的官方 FBoxSphereBounds 对比，确认挂点数学正确。

用法：
    python tools/verify_assembly.py --auto 6          # 自动挑 6 个能全解析的预设
    python tools/verify_assembly.py 10010000014       # 指定 DesId
"""
import os
import struct
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
for _p in (os.path.join(BASE, "work"), os.path.join(BASE, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np                                     # noqa: E402
import dtparse                                         # noqa: E402
import mini_upk as mu                                  # noqa: E402
from core import loader                                # noqa: E402

DT = "../../../DeltaForce/Content/DataTables/WeaponPart/"
SOCK = DT + "WeaponPartsMeshSocketNameInfo.uasset"
PSOCK = DT + "PartSocketsTable.uasset"
DESC = DT + "GunDescTable.uasset"
BOUNDS = DT + "GunPresetBoundsTable.uasset"


def rows_of(vp):
    ua = loader.read_entry(vp)
    ue = loader.read_entry(vp[:-7] + ".uexp")
    upk = mu.Upk(ua, ue)
    data = upk.export_data(upk.exports[0])
    rows, _e, _n = dtparse.walk(data, upk.names)
    return data, upk.names, rows


def prop(data, names, props, key):
    for name, typ, size, aidx, vs, vl in props:
        if name == key:
            return typ, vs, vl
    return None, 0, 0


def val(data, names, props, key):
    typ, vs, vl = prop(data, names, props, key)
    if typ is None:
        return None
    if typ == "UInt64Property":
        return struct.unpack_from("<Q", data, vs)[0]
    if typ == "Int16Property":
        return struct.unpack_from("<h", data, vs)[0]
    if typ == "UInt32Property":
        return struct.unpack_from("<I", data, vs)[0]
    if typ == "ByteProperty":
        return data[vs]
    if typ == "NameProperty":
        return names[struct.unpack_from("<i", data, vs)[0]]
    return None


def arr3(data, names, props, key):
    typ, vs, vl = prop(data, names, props, key)
    if typ is None:
        return []
    cnt = struct.unpack_from("<i", data, vs)[0]
    if vl != 53 + 12 * cnt:
        return []
    off = vs + 53
    return [np.array(struct.unpack_from("<3f", data, off + 12 * k), dtype=np.float64)
            for k in range(cnt)]


def fnames(data, names, props, key):
    typ, vs, vl = prop(data, names, props, key)
    if typ is None:
        return []
    cnt = struct.unpack_from("<i", data, vs)[0]
    return [names[struct.unpack_from("<i", data, vs + 4 + 8 * k)[0]] for k in range(cnt)]


P_MAP = np.array([[0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [-1.0, 0.0, 0.0]])   # GL = P @ UE


def fr_matrix(rot_deg):
    p, y, r = np.radians(rot_deg)
    cp, sp, cy, sy, cr, sr = np.cos(p), np.sin(p), np.cos(y), np.sin(y), np.cos(r), np.sin(r)
    Rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    Ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    Rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def sock_matrix(loc_cm, rot_deg):
    M = np.eye(4)
    M[:3, :3] = P_MAP @ fr_matrix(rot_deg) @ P_MAP.T
    M[:3, 3] = np.array([loc_cm[1], loc_cm[2], -loc_cm[0]]) * 0.01
    return M


_LOWER = {}


def real_vpath(key_lower):
    if not _LOWER:
        for vp in loader.index():
            low = vp.lower()
            if "models/weapons/" in low and low.endswith(".uasset"):
                _LOWER[low] = vp
    return _LOWER.get(("../../../deltaforce/content/" + key_lower + ".uasset").lower())


def load_tables():
    d, n, r = rows_of(SOCK)
    sock, item_mesh = {}, {}
    for rn, props in r:
        key = rn.split(".")[0]
        key = key[len("/Game/"):] if key.startswith("/Game/") else key
        item = val(d, n, props, "ItemId")
        sock[key.lower()] = (fnames(d, n, props, "SocketNames"),
                             arr3(d, n, props, "SocketLocation"),
                             arr3(d, n, props, "SocketRotation"))
        if item:
            item_mesh.setdefault(item, []).append(key.lower())
    d2, n2, r2 = rows_of(PSOCK)
    sid2name = {}
    for rn, props in r2:
        sid = val(d2, n2, props, "SocketId")
        nm = val(d2, n2, props, "SocketName")
        if sid is not None:
            sid2name[sid] = nm
    d3, n3, r3 = rows_of(DESC)
    desc = {}
    for rn, props in r3:
        des = val(d3, n3, props, "DesId")
        desc.setdefault(des, []).append({
            "deskey": val(d3, n3, props, "DesKey"),
            "idx": val(d3, n3, props, "Index"),
            "item": val(d3, n3, props, "ItemId"),
            "psock": val(d3, n3, props, "ParentSocketId"),
            "pidx": val(d3, n3, props, "ParentIndex"),
            "node": val(d3, n3, props, "NodeType"),
        })
    d4, n4, r4 = rows_of(BOUNDS)
    bounds = {}
    for rn, props in r4:
        typ, vs, vl = prop(d4, n4, props, "Bounds")
        if typ is None:
            continue
        r = vs
        vals = []
        for _k in range(2):
            r += 8 + 8
            sz = struct.unpack_from("<i", d4, r)[0]
            r += 4 + 4 + 8 + 16
            r += 1
            vals.append(np.array(struct.unpack_from("<3f", d4, r)))
            r += sz
        bounds[rn] = (vals[0], vals[1])
    return sock, item_mesh, sid2name, desc, bounds


def mesh_of(item_mesh, item):
    ms = item_mesh.get(item) or []
    ms = [m for m in ms if m.endswith("_3p")] or ms
    return ms[0] if ms else None


def bbox_of(vp):
    try:
        mesh = loader.load_mesh(vp, lod=0)
    except Exception:
        return None
    lods = getattr(mesh, "lods", None)
    if not lods:
        return None
    pos = getattr(lods[0], "positions", None)
    if pos is None or not len(pos):
        return None
    pos = np.asarray(pos, dtype=np.float64)
    return pos.min(axis=0), pos.max(axis=0)


def assemble_branch(nodes, sock, item_mesh, sid2name, cache):
    by_idx = {n["idx"]: n for n in nodes}
    world = {}
    pending = list(nodes)
    for _ in range(16):
        nxt = []
        for n in pending:
            if n["pidx"] in (-1, 32767, None):
                world[n["idx"]] = np.eye(4)
                continue
            p = by_idx.get(n["pidx"])
            if p is None or p["idx"] == n["idx"]:
                world[n["idx"]] = np.eye(4)
                continue
            if p["idx"] not in world:
                nxt.append(n)
                continue
            mesh = mesh_of(item_mesh, p["item"])
            sm = sid2name.get(n["psock"])
            M = np.eye(4)
            if mesh and sm and mesh in sock:
                names, locs, rots = sock[mesh]
                if sm in names:
                    k = names.index(sm)
                    if k < len(locs) and k < len(rots):
                        M = sock_matrix(locs[k], rots[k])
            world[n["idx"]] = world[p["idx"]] @ M
        pending = nxt
        if not pending:
            break
    lo = np.array([1e9] * 3)
    hi = np.array([-1e9] * 3)
    used = 0
    for n in nodes:
        mesh = mesh_of(item_mesh, n["item"])
        if not mesh:
            return None
        vp = real_vpath(mesh)
        if not vp:
            return None
        bb = cache.get(vp)
        if bb is None:
            bb = bbox_of(vp)
            cache[vp] = bb
        if bb is None:
            return None
        M = world.get(n["idx"], np.eye(4))
        corners = np.array([[x, y, z] for x in (bb[0][0], bb[1][0])
                            for y in (bb[0][1], bb[1][1])
                            for z in (bb[0][2], bb[1][2])])
        gl = corners @ M[:3, :3].T + M[:3, 3]
        lo = np.minimum(lo, gl.min(axis=0))
        hi = np.maximum(hi, gl.max(axis=0))
        used += 1
    if not used:
        return None
    return lo, hi


def main():
    want = [a for a in sys.argv[1:] if not a.startswith("--")]
    auto = int(sys.argv[sys.argv.index("--auto") + 1]) if "--auto" in sys.argv else 0
    sock, item_mesh, sid2name, desc, bounds = load_tables()
    print("sock=%d item_mesh=%d sid=%d desc=%d bounds=%d"
          % (len(sock), len(item_mesh), len(sid2name), len(desc), len(bounds)))

    if auto:
        want = []
        for des, nodes in desc.items():
            if str(des) in bounds and all(mesh_of(item_mesh, n["item"]) for n in nodes):
                want.append(str(des))
            if len(want) >= auto:
                break

    cache = {}
    ok = 0
    for des_s in want:
        des = int(des_s)
        nodes = desc.get(des) or []
        ob, eb = bounds.get(des_s, (None, None))
        if not nodes or ob is None:
            print("skip", des)
            continue
        uniq = {}
        for n in nodes:
            if n["idx"] is None:
                continue
            cur = uniq.get(n["idx"])
            if cur is None:
                uniq[n["idx"]] = dict(n)
            elif cur["pidx"] in (0, None) and n["pidx"] not in (0, None):
                uniq[n["idx"]] = dict(n)
        branches = {"all": list(uniq.values())}
        res = []
        for key, grp in branches.items():
            r = assemble_branch(grp, sock, item_mesh, sid2name, cache)
            if r:
                res.append(r)
        if not res:
            print("DES", des, "no complete branch (%d branch)" % len(branches))
            continue
        lo = np.min([r[0] for r in res], axis=0)
        hi = np.max([r[1] for r in res], axis=0)
        ue_lo = np.array([-hi[2], lo[0], lo[1]]) * 100
        ue_hi = np.array([-lo[2], hi[0], hi[1]]) * 100
        o_mid = (ue_lo + ue_hi) / 2
        e_half = (ue_hi - ue_lo) / 2
        d_o = float(np.abs(o_mid - ob).max())
        d_e = float(np.abs(e_half - eb).max())
        flag = "OK " if max(d_o, d_e) < 1.5 else "BAD"
        print("%s DES %-12s parts=%-2d br=%d mine o=%s e=%s | game o=%s e=%s | d=%.2f/%.2f"
              % (flag, des, len(uniq), len(branches), np.round(o_mid, 2), np.round(e_half, 2),
                 np.round(ob, 2), np.round(eb, 2), d_o, d_e))
        if flag == "OK ":
            ok += 1
    if want:
        print("\nMATCH %d / %d" % (ok, len(want)))


if __name__ == "__main__":
    main()
