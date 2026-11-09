"""Texture2D decode acceptance probe for Game paks.

Run:  python tools/probe_tex.py [count]

Picks textures under GenTexDirHD, decodes them, prints pixel format / dims /
mip count / bulk usage / decoded statistics and writes a few PNGs to
``G:\\xmcl-fetch\\work\\tex_*.png`` which are then re-opened through Pillow to
prove they are not blank.

Nothing here is imported by the app: it is a throwaway harness.
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from tools.pakpick import extract  # noqa: E402
from core.texture import (inspect_texture, load_texture, mip_size,  # noqa: E402
                          mip_chain, save_png)

OUT = r"G:\xmcl-fetch\work"
PATHS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tex_paths.json")


def pick(count: int = 10):
    """Pick a spread of GenTexDirHD textures (BaseColor / MRA / Mask / Normal / UI)."""
    paths = [p for p in json.load(open(PATHS)) if "GenTexDirHD" in p and p.endswith(".uasset")]
    buckets = {"BaseColor": [], "MRA": [], "Mask": [], "UI": [], "Normal": [], "other": []}
    for p in paths:
        low = p.lower()
        key = "other"
        for needle, bucket in (("basecolor", "BaseColor"), ("mra", "MRA"),
                               ("mask", "Mask"), ("normal", "Normal"), ("nm", "Normal"),
                               ("ui", "UI")):
            if needle in low:
                key = bucket
                break
        buckets[key].append(p)
    out, per = [], max(1, count // len(buckets))
    for name, items in buckets.items():
        if not items:
            continue
        step = max(1, len(items) // per)
        out.extend(items[::step][:per])
    if len(out) < count:
        step = max(1, len(paths) // count)
        out.extend(paths[::step][:count - len(out)])
    return out[:count]


def _get(vpath: str):
    """extract() but a missing sibling is just ``None``."""
    try:
        return extract(vpath)
    except KeyError:
        return None
    except Exception as exc:
        print(f"   (read error on {os.path.basename(vpath)}: {type(exc).__name__})")
        return None


def blobs(vpath: str):
    stem = vpath.rsplit(".", 1)[0]
    return (stem + ".uasset", _get(stem + ".uasset") or b"", _get(stem + ".uexp"),
            _get(stem + ".ubulk"), _get(stem + ".uptnl"))


def main(argv):
    count = int(argv[1]) if len(argv) > 1 else 10
    picked = pick(count)
    print(f"probing {len(picked)} textures under GenTexDirHD\n")
    rows, ok, fail, pngs = [], 0, 0, []
    t0 = time.time()
    for vpath in picked:
        name = os.path.basename(vpath)
        try:
            pak_path, ua, ue, ub, up = blobs(vpath)
        except Exception as exc:
            print(f"[FAIL] {name}: read {type(exc).__name__}: {exc}")
            fail += 1
            continue
        info = inspect_texture(ua, ue, ub, up)
        tex = load_texture(ua, ue, ub, pak_path, uptnl=up)
        good = tex.rgba is not None and tex.width > 0
        mean = float(tex.rgba[:, :, :3].mean()) / 255.0 if good else 0.0
        std = float(tex.rgba[:, :, :3].std()) if good else 0.0
        print(f"{name[:64]}")
        print(f"   pf={info['pixel_format'] or '-':<14} fmt={info['format']:<6} "
              f"nominal={info['sx']}x{info['sy']}  mips={info['mip_count']}  "
              f"src={info['source'] or '-':<6} decoded={tex.width}x{tex.height}")
        print(f"   uexp={len(ue or b'')} ubulk={len(ub or b'')} uptnl={len(up or b'')} "
              f"compression={info['compression'] or '-'} lod={info['lod_group'] or '-'}"
              f"{'  stream=' + info['stream_compression'] if info.get('stream_compression') else ''}")
        if good:
            print(f"   rgba={tex.rgba.shape} {tex.rgba.dtype} mean={mean:.3f} std={std:.1f} "
                  f"srgb={tex.srgb} alpha_min={int(tex.rgba[:, :, 3].min())}")
            ok += 1
        else:
            print(f"   decode FAILED: {info['error'] or 'no pixels'}")
            fail += 1
        rows.append((name, info, tex, good, mean))

    # ---- PNG round trip ------------------------------------------------
    print()
    ranked = [r for r in rows if r[3]]
    ranked.sort(key=lambda r: -r[2].width * r[2].height)
    for i, (name, info, tex, good, mean) in enumerate(ranked[:4]):
        path = os.path.join(OUT, f"tex_{i}_{tex.source_format.lower()}_{tex.width}.png")
        save_png(tex, path)
        with Image.open(path) as im:
            arr = np.asarray(im.convert("RGBA"), dtype=np.uint8)
        m = float(arr[:, :, :3].mean()) / 255.0
        s = float(arr[:, :, :3].std())
        verdict = "OK" if 0.02 < m < 0.98 else "SUSPECT (blank?)"
        print(f"PNG {path}  {im.size} mean={m:.3f} std={s:.1f} -> {verdict}")
        pngs.append((path, m, s, verdict, im.size))

    # ---- pixel format census over the whole sample ---------------------
    fmts = {}
    srcs = {}
    for name, info, tex, good, mean in rows:
        fmts[info["format"] or "?"] = fmts.get(info["format"] or "?", 0) + 1
        srcs[info["source"] or "?"] = srcs.get(info["source"] or "?", 0) + 1
    print(f"\n{'-'*70}\nok={ok} fail={fail}  ({time.time()-t0:.1f}s)")
    print("pixel format census:", fmts)
    print("mip source census:  ", srcs)
    bad_png = [p for p in pngs if p[3] != "OK"]
    print("pngs:", len(pngs), "suspect:", len(bad_png))
    return 0 if ok and not bad_png else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
