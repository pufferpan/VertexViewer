"""干员模型/皮肤诊断：把本体和一两个皮肤加载出来，打印网格与材质解析情况。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3

from core import loader

DB = os.path.expandvars(r"%LOCALAPPDATA%\VertexViewer\index.db")


def find(pattern: str, limit: int = 12):
    con = sqlite3.connect(DB)
    rows = [v for (v,) in con.execute(
        "select vpath from assets where vpath like '%.uasset' and lower(vpath) like ?", (pattern,))]
    con.close()
    return rows[:limit]


def report(vpath: str) -> None:
    print("=" * 100)
    print(vpath.split("Content/")[-1])
    t0 = time.time()
    try:
        bundle = loader.load_model(vpath, lod=0, want_textures=True)
    except Exception as exc:                                     # noqa: BLE001
        print("  ! 加载异常:", type(exc).__name__, exc)
        return
    mesh = getattr(bundle, "mesh", None)
    if not mesh:
        print("  ! 没有网格")
        return
    lod = mesh.lods[0]
    print(f"  用时 {time.time() - t0:.1f}s  顶点 {len(lod.positions)}  三角 {len(lod.indices) // 3}  "
          f"段 {len(lod.sections)}  材质 {len(bundle.materials or [])}  贴图 {len(bundle.textures or [])}")
    print("  格式:", mesh.source_format)
    for i, m in enumerate((bundle.materials or [])[:8]):
        print(f"    [{i}] {type(m).__name__} {str(getattr(m, 'name', m))[:60]}")
    if bundle.textures:
        for tex in list(bundle.textures)[:6]:
            k = getattr(tex, 'name', '?')
            print(f"    贴图 {str(k)[:44]} {getattr(tex, 'width', '?')}x{getattr(tex, 'height', '?')}")


for args in sys.argv[1:]:
    if args.startswith("%"):
        for v in find(args):
            report(v)
    else:
        report(args)

if not sys.argv[1:]:
    print("用法: python tools/_op_diag.py \"%body_3p_hd%\" \"%CharAppear%Kai%Body%\"")
