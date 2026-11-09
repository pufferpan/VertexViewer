"""看某一行 DataTable 到底为什么没配上名字：把行内所有字段摊开打印。

    python tools/probe_row.py 30mmCannon_1P [表名过滤]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WORK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work")
HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (WORK_DIR, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import json  # noqa: E402

import dtparse  # noqa: E402
import fetch  # noqa: E402
import mini_upk as mu  # noqa: E402
from core import loader  # noqa: E402
from ustbin import parse_ustbin  # noqa: E402


def main():
    needle = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    table_filter = (sys.argv[2] if len(sys.argv) > 2 else "").lower()
    locres = json.load(open(os.path.join(WORK_DIR, "locres_zh.json"), encoding="utf-8"))
    tables = [p for p in loader.index()
              if "/DataTables/" in p and p.endswith(".uasset") and table_filter in p.lower()]
    found = 0
    for path in tables:
        try:
            upk = mu.Upk(fetch.get(path), fetch.get(path[:-7] + ".uexp") or b"")
            if not upk.exports:
                continue
            data = upk.export_data(upk.exports[0])
            rows, _e, _n = dtparse.walk(data, upk.names)
        except Exception:                                     # noqa: BLE001
            continue
        for row_name, props in rows:
            hit = needle in row_name.lower()
            if not hit:
                for nm, typ, size, aidx, vs, vl in props:
                    if typ in ("StructProperty", "SoftObjectProperty", "ObjectProperty") and vl <= 16:
                        s = dtparse.softpath(data, vs, upk.names, vl)
                        if s and needle in s.lower():
                            hit = True
                            break
            if not hit:
                continue
            found += 1
            print(f"=== {path.rsplit('/', 1)[-1]}  行 {row_name}")
            for nm, typ, size, aidx, vs, vl in props:
                line = f"   {nm:28s} {typ:22s}"
                if typ == "TextProperty":
                    info = dtparse.text_info(data, vs, upk.names) or {}
                    ns = (info.get("table") or "").rsplit(".", 1)[-1]
                    key = info.get("key", "")
                    val = (locres.get(ns) or {}).get(key, "")
                    line += f" ns={ns} key={key} zh={val[:30]!r}"
                elif typ in ("StructProperty", "SoftObjectProperty", "ObjectProperty") and vl <= 16:
                    line += " " + str(dtparse.softpath(data, vs, upk.names, vl))[:90]
                else:
                    line += f" size={size}"
                print(line)
            if found >= 6:
                return
    print("命中", found)


if __name__ == "__main__":
    main()
