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

VP = "../../../DeltaForce/Content/DataTables/WeaponAppearance/WeaponSocketTransformTable.uasset"
ua = loader.read_entry(VP)
ue = loader.read_entry(VP[:-7] + ".uexp")
upk = mu.Upk(ua, ue)
names = upk.names
data = upk.export_data(upk.exports[0])
rows, _e, n = dtparse.walk(data, names)

print("names[0..12]", names[0:12])
print("names[350..374]", names[350:374])

want = (sys.argv[1] if len(sys.argv) > 1 else "M4A1").lower()
for rn, props in rows:
    if want in rn.lower() and "COD" not in rn:
        rn0, props0 = rn, props
        break
m = [p for p in props0 if p[0] == "TransformMap"][0]
blob = data[m[4]:m[4] + m[5]]


class R:
    def __init__(self, b, o):
        self.b = b
        self.o = o

    def i32(self):
        v = struct.unpack_from("<i", self.b, self.o)[0]
        self.o += 4
        return v

    def u8(self):
        v = self.b[self.o]
        self.o += 1
        return v

    def name(self):
        i, num = struct.unpack_from("<ii", self.b, self.o)
        self.o += 8
        return (names[i] if 0 <= i < len(names) else f"<{i}>") + (f"_{num-1}" if num else "")

    def skip(self, k):
        self.o += k


def tag(r, struct_extra=True, guid_byte=True, depth=0):
    nm = r.name()
    if nm == "None":
        return (("None",), None)
    ty = r.name()
    size = r.i32()
    aidx = r.i32()
    if guid_byte:
        g = r.u8()
        if g:
            r.skip(16)
    extra = None
    if ty == "BoolProperty":
        extra = r.u8()
    elif ty == "StructProperty" and struct_extra:
        sname = r.name()
        r.skip(16)
        extra = sname
    p = r.o
    r.skip(size)
    return (nm, ty, size, aidx, extra, p), ty


def map_parse(r, struct_extra=True, guid_byte=True):
    nk = r.i32()
    num = r.i32()
    out = []
    for _ in range(num):
        key = r.name()
        props = []
        while True:
            t = tag(r, struct_extra, guid_byte)
            if t[0] == ("None",):
                break
            props.append(t[0])
        out.append((key, props))
    return nk, num, out


for start in range(66, 100):
    r = R(blob, start)
    try:
        nk, num, out = map_parse(r)
        ok = "OK" if r.o <= start + 420 else "??"
        if num in (1, 2, 3, 4) and out:
            print(f"start={start} nkeys_remove={nk} num={num} end={r.o} {ok}")
            for key, props in out:
                for p in props:
                    print("    ", key, p)
    except Exception as e:
        pass
