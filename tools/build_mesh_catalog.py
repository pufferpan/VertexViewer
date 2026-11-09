"""扫描全部 Models/ 资产，记录每个包的「主导出类名」。

目的：让浏览器的模型库只显示真正可渲染的资产（StaticMesh / SkeletalMesh），
把 AnimSequence / PhysicsAsset / Skeleton / 蓝图之类从列表里剔掉。

用法：
    python tools/build_mesh_catalog.py            # 全量（多进程，约 8-15 分钟）
    python tools/build_mesh_catalog.py --limit 200

产出：
    G:/xmcl-fetch/work/mesh_catalog.json  = {"<vpath>": "<class>", ...}
    G:/xmcl-fetch/work/mesh_catalog_stats.json
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
WORK = r"G:\xmcl-fetch\work"
OUT = os.path.join(WORK, "mesh_catalog.json")

# 只关心这几类（其余记为类名原样，方便统计）
MESH_CLASSES = {"StaticMesh", "SkeletalMesh"}


def _classify_chunk(chunk):
    from core import loader
    from core.uasset import Package

    out = {}
    for vpath in chunk:
        try:
            blobs = loader.load_blobs(vpath)
            uasset = blobs.get("uasset") or b""
            if not uasset:
                out[vpath] = "<no-uasset>"
                continue
            pkg = Package(uasset, blobs.get("uexp"), blobs.get("ubulk"))
            cls = ""
            for exp in pkg.exports:
                try:
                    name = pkg.export_class(exp) or ""
                except Exception:                                  # noqa: BLE001
                    name = ""
                if name:
                    cls = name
                    if name in MESH_CLASSES:
                        break
            out[vpath] = cls or "?"
        except Exception as exc:                                    # noqa: BLE001
            out[vpath] = f"ERR:{type(exc).__name__}"
    return out


def main(argv):
    limit = None
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])

    from core import loader

    paths = sorted(p for p in loader.index() if "/Models/" in p and p.endswith(".uasset"))
    if limit:
        paths = paths[:limit]
    print(f"assets: {len(paths)}", flush=True)

    workers = max(2, min(12, (os.cpu_count() or 4) - 2))
    chunk = max(64, min(600, len(paths) // (workers * 6) or 64))
    chunks = [paths[i:i + chunk] for i in range(0, len(paths), chunk)]
    print(f"workers={workers} chunk={chunk} chunks={len(chunks)}", flush=True)

    result = {}
    t0 = time.time()
    done = 0
    ctx = mp.get_context("spawn")
    with ctx.Pool(workers) as pool:
        for part in pool.imap_unordered(_classify_chunk, chunks):
            result.update(part)
            done += len(part)
            if done % 2000 < chunk:
                rate = done / max(time.time() - t0, 1e-6)
                print(f"  {done}/{len(paths)}  {rate:.1f}/s  eta {(len(paths)-done)/max(rate,1e-6)/60:.1f} min",
                      flush=True)

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    stats = {}
    for v in result.values():
        stats[v] = stats.get(v, 0) + 1
    stats = dict(sorted(stats.items(), key=lambda kv: -kv[1]))
    with open(os.path.join(WORK, "mesh_catalog_stats.json"), "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2)
    total_mesh = sum(c for k, c in stats.items() if k in MESH_CLASSES)
    print(f"done {len(result)} assets in {(time.time()-t0)/60:.1f} min; "
          f"meshes={total_mesh}; top={list(stats.items())[:8]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
