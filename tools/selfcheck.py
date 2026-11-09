"""VertexViewer 全链路自检：索引 -> 几何 -> 材质/贴图 -> 渲染 -> 三种导出 -> 缓存清理。

用法：
    python -m tools.selfcheck                # 全部检查
    python -m tools.selfcheck --no-window    # 跳过真实窗口（只用离屏 GL）

每条检查都记 PASS/FAIL，最后打印汇总；任何 FAIL 都会让进程返回码为 1。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np                                                  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str):
    def _wrap(fn):
        def _run(*a, **kw):
            t0 = time.time()
            try:
                detail = fn(*a, **kw) or ""
                RESULTS.append((name, True, f"{time.time() - t0:.1f}s {detail}"))
                print(f"  PASS {name}  ({time.time() - t0:.1f}s) {detail}", flush=True)
                return True
            except Exception as exc:                               # noqa: BLE001
                RESULTS.append((name, False, f"{type(exc).__name__}: {exc}"))
                print(f"  FAIL {name}  {type(exc).__name__}: {exc}", flush=True)
                traceback.print_exc()
                return False
        return _run
    return _wrap


def _pick(index_map, catalog, kinds, per_kind=1):
    """按 (目录关键词, 类名) 取样，尽量分散在不同类别。"""
    out = []
    for kw in kinds:
        n = 0
        for k, cls in catalog.items():
            if cls not in ("StaticMesh", "SkeletalMesh"):
                continue
            if kw not in k:
                continue
            out.append(k)
            n += 1
            if n >= per_kind:
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-window", action="store_true")
    args = ap.parse_args()

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from core import loader, icons, cnnames
    import render
    from exporters import obj as obj_exporter

    state = {}

    @check("1 索引已就绪")
    def _index():
        idx = loader.index()
        state["index"] = idx
        catalog = loader.catalog() or {}
        state["catalog"] = catalog
        meshes = sum(1 for c in catalog.values() if c in ("StaticMesh", "SkeletalMesh"))
        assert len(idx) > 500000, f"索引太小：{len(idx)}"
        assert meshes > 5000, f"可渲染网格太少：{meshes}"
        return f"索引 {len(idx)} 条 / 可渲染网格 {meshes}"

    @check("2 图标索引")
    def _icons():
        icons.load()
        st = icons.stats()
        assert st.get("assets", 0) > 500, st
        return f"资产名 {st.get('assets')} / ID {st.get('ids')}"

    @check("3 中文名库")
    def _names():
        cnnames.load()
        st = cnnames.stats()
        assert st.get("count", 0) > 1000, st
        return f"{st.get('count')} 条映射"

    _index()
    _icons()
    _names()

    kinds = ("Models/Weapons/Parts", "Models/Characters", "Models/Characters_HD",
             "Models/Vehicles", "Models/Props", "Models/Equipments_HD")
    samples = _pick(state.get("index", {}), state.get("catalog", {}), kinds, 1)
    state["samples"] = samples

    @check("4 几何 + 材质 + 贴图（各类别抽样）")
    def _load():
        assert samples, "没有取到样本"
        lines = []
        for v in samples:
            b = loader.load_model(v)
            assert b is not None and b.mesh and b.mesh.lods, f"{v} 没有几何"
            lod = b.mesh.lods[0]
            assert len(lod.indices) > 0 and len(lod.positions) > 0, f"{v} 空几何"
            assert lod.uvs is not None and len(lod.uvs) == len(lod.positions), f"{v} UV 缺失"
            assert np.isfinite(lod.positions).all(), f"{v} 顶点有 NaN"
            lines.append(f"{v.rsplit('/', 1)[-1][:26]}:{len(lod.indices)//3}t/{len(b.materials)}m/{len(b.textures)}t")
        return "; ".join(lines)

    _load()

    @check("5 真实 GL 渲染（非空帧）")
    def _render():
        v = samples[0]
        b = loader.load_model(v)
        w = render.MeshViewer()
        w.resize(520, 520)
        w.set_mesh(b.mesh, b.materials, b.textures)
        w.frame_all()
        p = os.path.join(ROOT, "work", "selfcheck_render.png")
        w.capture(p)
        assert os.path.getsize(p) > 20000, "渲染图太小"
        from PIL import Image as _PILImage
        img = np.asarray(_PILImage.open(p).convert("RGB"))
        assert img.std() > 6, f"画面几乎纯色 std={img.std():.2f}"
        return f"{os.path.basename(p)} std={img.std():.1f}"

    _render()

    @check("6 三种导出（OBJ / uemodel / FModel 目录）")
    def _export():
        from exporters import uemodel as ue_exporter
        from exporters import fmodel_layout
        v = samples[0]
        b = loader.load_model(v)
        exp = os.path.join(ROOT, "work", "selfcheck_export")
        os.makedirs(exp, exist_ok=True)
        p1 = os.path.join(exp, "model.obj")
        obj_exporter.export_obj(b, p1)
        p2 = os.path.join(exp, "model.uemodel")
        ue_exporter.export_uemodel(b, p2)
        p3 = os.path.join(exp, "tree")
        fmodel_layout.export_tree(b, p3, v)
        sizes = [os.path.getsize(x) for x in (p1, p2) if os.path.exists(x)]
        assert len(sizes) == 2 and min(sizes) > 1000, f"导出文件异常 {sizes}"
        n_tree = sum(len(f) for _, _, f in os.walk(p3))
        assert n_tree >= 3, f"FModel 目录文件太少 {n_tree}"
        return f"obj={sizes[0]}B uemodel={sizes[1]}B tree={n_tree}文件"

    _export()

    @check("7 缓存写入后能整体清除")
    def _cache():
        import cache as cache_mod
        c = cache_mod.get_cache()
        root = str(getattr(c, "root", ""))
        assert root, "缓存根目录为空"
        before = sum(len(f) for _, _, f in os.walk(root)) if os.path.isdir(root) else 0
        c.purge()
        after = sum(len(f) for _, _, f in os.walk(root)) if os.path.isdir(root) else 0
        assert after <= 1, f"清理后仍有 {after} 个文件"
        return f"root={root} 清理前{before}个文件"

    _cache()

    if not args.no_window:
        @check("8 真窗口加载 + 截图 + 关窗清缓存")
        def _window():
            from PySide6.QtCore import QTimer
            from app.main_window import VertexViewerWindow
            win = VertexViewerWindow()
            win.show()
            seen = {}

            def go():
                win.load_vpath(samples[0])
                QTimer.singleShot(9000, shot)

            def shot():
                seen["tri"] = getattr(win.viewport, "triangle_count", 0)
                p = os.path.join(ROOT, "work", "selfcheck_window.png")
                win.grab().save(p)
                win.close()
                QTimer.singleShot(1500, done)

            def done():
                app.quit()

            QTimer.singleShot(2000, go)
            app.exec()
            assert seen.get("tri", 0) > 0, f"视口三角形为 0（{seen}）"
            return f"三角形 {seen['tri']}，截图已存"

        _window()

    ok = sum(1 for _, p, _ in RESULTS if p)
    bad = [r for r in RESULTS if not r[1]]
    print("\n== 自检汇总 ==", flush=True)
    for name, passed, detail in RESULTS:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}  {detail}", flush=True)
    print(f"共 {len(RESULTS)} 项，通过 {ok}，失败 {len(bad)}", flush=True)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
