"""通用 DataTable 行转储：递归展开 Array/Struct/Map，尽量把数值解出来。"""
import os
import struct
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
for _p in (os.path.join(BASE, "work"), os.path.join(BASE, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import dtparse                                        # noqa: E402
import mini_upk as mu                                 # noqa: E402
from core import loader                               # noqa: E402

T = dtparse.Tags


def fnum(data, o, n=3):
    return tuple(round(v, 4) for v in struct.unpack_from("<%df" % n, data, o))


def dump_props(data, names, start, end, indent, depth=0):
    tags = T(names)
    r = dtparse.Rd(data, start)
    lines = []
    while r.o + 8 <= end:
        st = r.o
        nm = tags.nm(r)
        if nm == "None":
            lines.append(" " * indent + "None @%d" % st)
            break
        r.o = st
        try:
            name, typ, size, aidx, vstart, vlen = tags.tag(r)
        except Exception as exc:                      # noqa: BLE001
            lines.append(" " * indent + "!! tag fail @%d (%s)" % (st, exc))
            break
        lines.append(" " * indent + "%s : %s size=%d @%d" % (name, typ, vlen, vstart))
        lines.extend(describe(data, names, typ, vstart, vlen, indent + 4, depth + 1))
        if r.o > end:
            break
    return lines


def describe(data, names, typ, vstart, vlen, indent, depth):
    out = []
    raw = data[vstart:vstart + vlen]
    if typ in ("ByteProperty", "EnumProperty", "BoolProperty", "StrProperty",
               "NameProperty", "TextProperty", "UInt64Property", "UInt32Property",
               "FloatProperty", "IntProperty", "ObjectProperty"):
        if typ == "NameProperty" and vlen >= 8:
            i, num = struct.unpack_from("<ii", data, vstart)
            out.append(" " * indent + "= %s" % (names[i] if 0 <= i < len(names) else i))
        elif typ in ("UInt32Property", "IntProperty", "FloatProperty"):
            out.append(" " * indent + "= %r" % (struct.unpack_from("<I", data, vstart)[0],))
        elif typ == "UInt64Property":
            out.append(" " * indent + "= %d" % (struct.unpack_from("<Q", data, vstart)[0],))
        else:
            out.append(" " * indent + raw[:40].hex())
        return out
    if typ == "StructProperty":
        return out + dump_props(data, names, vstart, vstart + vlen, indent, depth)
    if typ == "ArrayProperty":
        cnt = struct.unpack_from("<i", data, vstart)[0]
        out.append(" " * indent + "count=%d" % cnt)
        if cnt < 0 or cnt > 10000:
            out.append(" " * indent + raw[:48].hex())
            return out
        # 元素是 FName？
        if vlen == 4 + 8 * cnt:
            for k in range(cnt):
                i, num = struct.unpack_from("<ii", data, vstart + 4 + 8 * k)
                out.append(" " * indent + "  [%d] %s" % (k, names[i] if 0 <= i < len(names) else i))
            return out
        if vlen == 4 + 12 * cnt:
            for k in range(cnt):
                out.append(" " * indent + "  [%d] %s" % (k, fnum(data, vstart + 4 + 12 * k)))
            return out
        # 否则按「带 tag 的元素」试
        o = vstart + 4
        tags = T(names)
        for k in range(cnt):
            if o + 8 > vstart + vlen:
                break
            r = dtparse.Rd(data, o)
            nm = tags.nm(r)
            if nm == "None":
                out.append(" " * indent + "  [%d] None @%d" % (k, o))
                o = r.o
                break
            r.o = o
            try:
                name, typ2, size2, aidx2, vs2, vl2 = tags.tag(r)
            except Exception:                          # noqa: BLE001
                break
            out.append(" " * indent + "  [%d] %s : %s size=%d" % (k, name, typ2, vl2))
            out.extend(describe(data, names, typ2, vs2, vl2, indent + 6, depth + 1))
            o = r.o
        if o < vstart + vlen:
            out.append(" " * indent + "  leftover %d B: %s" % (vstart + vlen - o,
                                                              data[o:vstart + vlen][:40].hex()))
        return out
    return out + [" " * indent + raw[:48].hex()]


if __name__ == "__main__":
    vp = sys.argv[1]
    want = sys.argv[2] if len(sys.argv) > 2 else ""
    ua = loader.read_entry(vp)
    ue = loader.read_entry(vp[:-7] + ".uexp")
    upk = mu.Upk(ua, ue)
    data = upk.export_data(upk.exports[0])
    rows, _e, n = dtparse.walk(data, upk.names)
    print("rows", len(rows))
    for rn, props in rows:
        if want and want.lower() not in rn.lower():
            continue
        print("ROW", rn)
        for name, typ, size, aidx, vstart, vlen in props:
            print("  %s : %s size=%d" % (name, typ, vlen))
            for line in describe(data, upk.names, typ, vstart, vlen, 6, 0):
                print(line)
        break
