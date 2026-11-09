"""查清「哪些模型没有中文名」到底卡在哪一步。

三件事：
1. 把所有 DataTable 行里的 SoftObjectPath（不管这一行有没有名字文本）全收集起来，
   看缺名字的模型 stem 到底有没有被任何 DataTable 引用；
2. 把 StringTable（.ustbin）全解一遍，看 locres 里缺哪些 namespace/key；
3. 输出「被引用但没配上名字」的模型清单，便于下一步做 ID 关联。

    python tools/probe_cov.py [--dump]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import loader  # noqa: E402

WORK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work")
for _p in (WORK_DIR, os.path.dirname(os.path.abspath(__file__))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fetch                      # noqa: E402
import mini_upk as mu             # noqa: E402
import dtparse                    # noqa: E402
from ustbin import parse_ustbin   # noqa: E402

WORK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work")
CATALOG = r"G:\xmcl-fetch\work\mesh_catalog.json"
NAMES = os.path.join(WORK, "names.json")


def stem(p: str) -> str:
    return str(p).replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]


def main():
    catalog = json.load(open(CATALOG, encoding="utf-8"))
    models = {stem(k) for k, v in catalog.items() if v in ("StaticMesh", "SkeletalMesh")}
    named = set()
    if os.path.exists(NAMES):
        data = json.load(open(NAMES, encoding="utf-8"))
        named = {k for k, v in data.get("map", {}).items() if (v.get("cn") or "").strip()}
    missing = sorted(models - named)
    print(f"模型 {len(models)}，已有中文名 {len(named & models)}，缺 {len(missing)}")

    index = loader.index()
    tables = sorted(p for p in index if "/DataTables/" in p and p.endswith(".uasset"))
    print("DataTable", len(tables))

    # 1) 全量收集 soft path 里出现的模型 stem，以及它在哪些表
    refs = {}
    for i, path in enumerate(tables):
        try:
            uasset = fetch.get(path)
            try:
                uexp = fetch.get(path[:-7] + ".uexp")
            except Exception:                                 # noqa: BLE001
                uexp = b""
            upk = mu.Upk(uasset, uexp)
            if not upk.exports:
                continue
            d = upk.export_data(upk.exports[0])
            rows, _end, _n = dtparse.walk(d, upk.names)
        except Exception:                                     # noqa: BLE001
            continue
        for row_name, props in rows:
            for nm, typ, size, aidx, vs, vl in props:
                if typ not in ("StructProperty", "SoftObjectProperty", "ObjectProperty"):
                    continue
                if vl > 16:
                    continue
                s = dtparse.softpath(d, vs, upk.names, vl)
                if not s or "/Models/" not in s:
                    continue
                st = stem(s)
                if st:
                    refs.setdefault(st, set()).add(path.rsplit("/", 1)[-1])
        if (i + 1) % 400 == 0:
            print(f"  ..{i + 1} 表, 命中模型 {len(refs)}", flush=True)

    hit = [m for m in missing if m in refs]
    print(f"缺名字的模型里，被 DataTable 引用过的：{len(hit)} / {len(missing)}")
    for m in hit[:15]:
        print("   ", m, "->", sorted(refs[m])[:2])

    # 2) StringTable 全解
    ust = [p for p in index if p.endswith(".ustbin")]
    locres_path = os.path.join(WORK, "locres_zh.json")
    locres = json.load(open(locres_path, encoding="utf-8")) if os.path.exists(locres_path) else {}
    extra_ns = 0
    extra_keys = 0
    total_rows = 0
    dump = {}
    for p in ust:
        try:
            blob = loader.load_blobs(p).get("ustbin") or b""
            name, rows = parse_ustbin(blob)
        except Exception:                                     # noqa: BLE001
            continue
        if not name:
            name = os.path.basename(p).rsplit(".", 1)[0]
        if rows:
            dump[name] = dict(rows)
            total_rows += len(rows)
        have = locres.get(name) or {}
        if not have:
            extra_ns += 1
        extra_keys += sum(1 for k, _ in rows if k not in have)
    print(f"StringTable {len(ust)} 个，解出 {len(dump)} 表 / {total_rows} 行；"
          f"locres 里没有的 namespace {extra_ns} 个，多出的 key {extra_keys} 条")
    if "--dump" in sys.argv:
        out = os.path.join(WORK, "stringtables.json")
        json.dump(dump, open(out, "w", encoding="utf-8"), ensure_ascii=False)
        print("已写", out)


if __name__ == "__main__":
    main()
