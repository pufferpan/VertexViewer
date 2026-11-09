"""全量体检：把所有网格按类别抽样跑一遍「解包 → 几何 → 材质 → 贴图」，
统计哪一类还有问题，并拼一张联络表（contact sheet）看截面。

    python -m tools.audit_all --sample 240 --render 36
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _categories(index_keys):
    buckets = defaultdict(list)
    for k in index_keys:
        if "/Models/" not in k or not k.endswith(".uasset"):
            continue
        rest = k.split("/Models/", 1)[1]
        top = rest.split("/", 1)[0]
        buckets[top].append(k)
    return buckets


def _pick(keys, n, per_cat):
    out = []
    for cat in sorted(keys):
        items = keys[cat]
        if not items:
            continue
        step = max(1, len(items) // max(1, per_cat))
        picked = items[::step][:per_cat]
        out.extend((cat, k) for k in picked)
        if len(out) >= n:
            break
    return out[:n]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=240)
    ap.add_argument("--per-cat", type=int, default=12)
    ap.add_argument("--render", type=int, default=36)
    ap.add_argument("--out", default="work/audit")
    args = ap.parse_args(argv)

    from core import loader

    t0 = time.time()
    index = loader.index()
    catalog = loader.catalog() or {}
    mesh_keys = [k for k in index
                 if catalog.get(k) in ("StaticMesh", "SkeletalMesh")]
    print(f"索引 {len(index)} 条，可渲染网格 {len(mesh_keys)} 个，"
          f"取样本 {min(args.sample, len(mesh_keys))}")

    cats = _categories(mesh_keys)
    picked = _pick(cats, args.sample, args.per_cat)
    print("抽样分布:", {c: sum(1 for cc, _ in picked if cc == c) for c in sorted(cats)})

    rows = []
    for i, (cat, vpath) in enumerate(picked):
        rec = {"cat": cat, "vpath": vpath, "ok": False}
        t = time.time()
        try:
            bundle = loader.load_model(vpath)
            mesh = bundle.mesh
            if mesh is None or not mesh.lods:
                rec["error"] = "no-mesh"
            else:
                lod = mesh.lods[0]
                mats = list(bundle.materials or [])
                texs = list(bundle.textures or [])
                base = [m for m in mats if getattr(m, "base_color_texture", "")]
                rec.update(
                    ok=True,
                    cls=catalog.get(vpath),
                    lods=len(mesh.lods),
                    tris=len(lod.indices) // 3,
                    verts=len(lod.positions),
                    sections=len(lod.sections),
                    mats=len(mats),
                    mats_with_base=len(base),
                    texs=len(texs),
                    cn=bool(bundle.display_name_cn),
                )
                if mats and not base:
                    rec["error"] = "no-base-texture"
                elif not mats:
                    rec["error"] = "no-material"
        except Exception as exc:                                # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {exc}"[:160]
        rec["ms"] = int((time.time() - t) * 1000)
        rows.append(rec)
        print(f"  [{i + 1}/{len(picked)}] {cat:14s} {rec['ms']:6d}ms "
              f"mats={rec.get('mats', '-')} texs={rec.get('texs', '-')} "
              f"{rec.get('error', 'ok')} · {rec['vpath'].rsplit('/', 1)[-1][:44]}",
              flush=True)

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "audit.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)

    ok = [r for r in rows if r.get("ok")]
    errs = Counter(r.get("error") for r in rows if r.get("error"))
    with_base = sum(1 for r in ok if r.get("mats_with_base"))
    print(f"\n样本 {len(rows)} · 可加载 {len(ok)} ({len(ok)/max(1,len(rows)):.0%}) · "
          f"有材质 {sum(1 for r in ok if r['mats'])} · 有固有色 {with_base} · "
          f"有中文名 {sum(1 for r in ok if r.get('cn'))}")
    print("失败原因:", dict(errs))
    per_cat = defaultdict(lambda: [0, 0])
    for r in ok:
        per_cat[r["cat"]][0] += 1
        if r.get("mats_with_base"):
            per_cat[r["cat"]][1] += 1
    print("各类别 有固有色/可加载:", {k: f"{v[1]}/{v[0]}" for k, v in sorted(per_cat.items())})

    # ---- 联络表 ----
    if args.render:
        try:
            from PySide6.QtWidgets import QApplication
            from PIL import Image, ImageDraw
            app = QApplication.instance() or QApplication([])
            import render

            good = [r for r in ok if r.get("mats_with_base")][: args.render]
            cell = 260
            cols = 6
            rows_n = (len(good) + cols - 1) // cols
            sheet = Image.new("RGB", (cols * cell, rows_n * cell), (18, 20, 24))
            draw = ImageDraw.Draw(sheet)
            tmp = os.path.join(args.out, "_cell.png")
            for i, r in enumerate(good):
                try:
                    bundle = loader.load_model(r["vpath"])
                    w = render.MeshViewer()
                    w.resize(cell, cell)
                    w.set_mesh(bundle.mesh, bundle.materials, bundle.textures)
                    w.frame_all()
                    w.capture(tmp)
                    im = Image.open(tmp).convert("RGB")
                    im.thumbnail((cell - 8, cell - 22))
                    x = (i % cols) * cell
                    y = (i // cols) * cell
                    sheet.paste(im, (x + 4, y + 18))
                    draw.text((x + 6, y + 4), f"{i}:{os.path.basename(r['vpath'])[:26]}",
                              fill=(210, 215, 220))
                except Exception as exc:                        # noqa: BLE001
                    print("  render fail", r["vpath"][-40:], exc)
            out_png = os.path.join(args.out, "sheet.png")
            sheet.save(out_png)
            print("联络表:", out_png, sheet.size)
        except Exception as exc:                                # noqa: BLE001
            print("联络表跳过:", exc)

    print(f"用时 {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
