"""把 DataTable 摊开打印，侧重数值（用于挂点/变换表）。

    python tools/dump_dt.py SocketTransform            # vpath 子串过滤
    python tools/dump_dt.py PartSockets --row 1001     # 再看行名过滤
    python tools/dump_dt.py SocketTransform --a 1p     # 只看 1p 表

数值按大小猜：
    12 字节 -> 3 个 float（FVector / FRotator）
    16 字节 -> 4 个 float（FQuat）
     8 字节 -> int32 对 / 2 个 float
"""
from __future__ import annotations

import json
import os
import struct
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                      # noqa: BLE001
    pass
for _p in (os.path.join(BASE, "work"), os.path.join(BASE, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import dtparse                                        # noqa: E402
import mini_upk as mu                                 # noqa: E402
from core import loader                               # noqa: E402

INDEX: dict | None = None


class _Fetch:
    """docstring 里说的 fetch 兼容层：直接走 core.loader。"""

    @staticmethod
    def index():
        global INDEX
        if INDEX is None:
            INDEX = loader.index()
        return INDEX

    @staticmethod
    def get(vpath):
        try:
            return loader.read_entry(vpath)
        except Exception:                              # noqa: BLE001
            return None

    @staticmethod
    def close():
        pass


fetch = _Fetch()


def f32s(b):
    n = len(b) // 4
    return [round(struct.unpack_from("<f", b, 4 * i)[0], 4) for i in range(n)]


def show_val(typ, vs, vl, data, names):
    raw = data[vs:vs + vl]
    if typ == "BoolProperty":
        return ""
    if typ in ("FloatProperty",) and vl == 4:
        return f"{struct.unpack('<f', raw)[0]:+.4f}"
    if typ in ("IntProperty",) and vl == 4:
        return f"{struct.unpack('<i', raw)[0]}"
    if typ in ("NameProperty", "EnumProperty", "ByteProperty") and vl >= 8:
        return str(dtparse.fname_val(data, vs, names))
    if typ in ("StrProperty", "TextProperty") and vl <= 8 * 64:
        try:
            r = dtparse.Rd(data, vs)
            return repr(r.fstr())
        except Exception:                             # noqa: BLE001
            return ""
    if typ in ("StructProperty", "ObjectProperty", "SoftObjectProperty"):
        p = dtparse.softpath(data, vs, names, vl)
        if p:
            return p
    if vl in (12, 16):
        return str(f32s(raw))
    if vl == 8:
        return f"i={struct.unpack('<ii', raw)} f={f32s(raw)}"
    if 0 < vl <= 64:
        return raw.hex()
    return f"<{vl}B>"


def main(argv):
    needle = (argv[1] if len(argv) > 1 else "").lower()
    row_filter = ""
    only_a = ""
    if "--row" in argv:
        row_filter = argv[argv.index("--row") + 1].lower()
    if "--a" in argv:
        only_a = argv[argv.index("--a") + 1].lower()

    idx = fetch.index()
    hits = [p for p in idx if needle in p.lower() and p.endswith(".uasset")]
    print(f"# {len(hits)} 张表匹配 {needle!r}")
    for path in sorted(hits):
        if only_a and only_a not in path.lower():
            continue
        ua = fetch.get(path)
        ue = fetch.get(path[:-7] + ".uexp") or b""
        if not ua:
            print(f"!! 取不到 {path}")
            continue
        try:
            upk = mu.Upk(ua, ue)
            if not upk.exports:
                print(f"!! 无 export {path}")
                continue
            data = upk.export_data(upk.exports[0])
            rows, _e, n = dtparse.walk(data, upk.names)
        except Exception as exc:                       # noqa: BLE001
            print(f"!! 解析失败 {path}: {exc}")
            continue
        print(f"\n=== {path.rsplit('/', 1)[-1]}  ({len(data)}B, rows={len(rows)}/{n})")
        for rn, props in rows:
            if row_filter and row_filter not in rn.lower():
                continue
            print(f"  • {rn}")
            for nm, typ, size, aidx, vs, vl in props:
                v = show_val(typ, vs, vl, data, upk.names)
                print(f"      {nm:<26} {typ:<20} {v}")
    fetch.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
