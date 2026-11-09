"""Find the real name table: try candidate offsets, validate all N entries parse."""
import struct

F = r"G:\xmcl-fetch\work\samples\T_VMGen_BaseColorMap_993eca56b1014c50d99948ab48a30e9a.uasset"
b = open(F, "rb").read()
NC, NO = 28, 201


def parse_names(buf, off, count, incl_null=True):
    out = []
    o = off
    for _ in range(count):
        if o + 4 > len(buf):
            return out, o, "eof-len"
        n = struct.unpack_from("<i", buf, o)[0]
        o += 4
        if n == 0:
            out.append("")
            continue
        if n < 0:
            ln = -n
            raw = buf[o:o + ln * 2]
            if len(raw) < ln * 2:
                return out, o, "eof-str"
            s = raw.decode("utf-16-le", "replace")
            o += ln * 2
        else:
            if not incl_null:
                n += 1
            raw = buf[o:o + n]
            if len(raw) < n:
                return out, o, "eof-str"
            s = raw.decode("utf-8", "replace")
            o += n
        s = s.rstrip("\0")
        out.append(s)
        o += 2
        o += 2
    return out, o, "ok"


for cand in (0xC9, 0xC8, 0xCB, 0xCC, 0xCD, 0x1C):
    for incl in (True, False):
        names, end, st = parse_names(b, cand, NC, incl)
        good = st == "ok" and all(31 < ord(c[0]) < 127 for c in names if c)
        print(f"off=0x{cand:x} incl_null={incl} -> {st} end=0x{end:x} "
              f"{'OK' if good else 'bad'} first3={names[:3]} last={names[-1:] if names else None}")
        if good:
            print("   names:", names)
            break
