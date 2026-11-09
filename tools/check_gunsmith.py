"""端到端校验：`gunsmith.official_loadout()` + `gunsmith.assemble()`
拼出来的包围盒，和游戏 `GunPresetBoundsTable` 里这把枪的官方预设比。

这是**改枪台真正走的路径**（UI 选完主件 → `_apply_official()` → `_rebuild()`），
所以它对了，界面上看到的位置就对了。

用法：
    python tools/check_gunsmith.py                       # 抽查一批常见枪
    python tools/check_gunsmith.py "Rec_AR_M4A1-Std_001" # 指定
    python tools/check_gunsmith.py --all 40              # 扫 40 把
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np                                     # noqa: E402

from core import gunsmith as gs                        # noqa: E402
from core import loader, presets as P, sockets as S    # noqa: E402


def gl_to_ue(box):
    """GL 米包围盒 → UE 厘米 (origin, extent)。"""
    lo, hi = box
    ue_lo = np.array([-hi[2], lo[0], lo[1]]) * 100.0
    ue_hi = np.array([-lo[2], hi[0], hi[1]]) * 100.0
    return (ue_lo + ue_hi) * 0.5, (ue_hi - ue_lo) * 0.5


def score(base_vpath: str, verbose: bool = False):
    try:
        bundle = loader.load_model(base_vpath, want_textures=False)
    except Exception as exc:                            # noqa: BLE001
        return None, "load fail %s" % exc
    if not (bundle and getattr(bundle, "mesh", None) and bundle.mesh.lods):
        return None, "no mesh"
    picks = gs.official_loadout(base_vpath)
    pairs = []
    for spec in picks:
        try:
            pb = loader.load_model(spec.vpath, want_textures=False)
        except Exception:                               # noqa: BLE001
            continue
        if pb and getattr(pb, "mesh", None) and pb.mesh.lods:
            pairs.append((spec, pb))
    if not pairs:
        return None, "no parts"
    combo = gs.assemble(bundle, pairs, base_vpath=base_vpath)
    lod = gs._lod0(combo)
    if lod is None:
        return None, "assemble fail"
    origin, extent = gl_to_ue(gs.bounds(lod))

    # 和这把枪所有官方预设比，取最接近的那个
    item = S.item_of_mesh(base_vpath)
    best = None
    for desid in P.presets_of_item(item):
        ob = P.bounds_of(desid)
        if ob is None:
            continue
        d = float(np.abs(np.concatenate([ob[0] - origin, ob[1] - extent])).max())
        if best is None or d < best[0]:
            best = (d, desid, ob)
    if verbose:
        print("  件数 %d (socket: %s)" % (len(pairs), ", ".join(
            "%s=%s" % (p.slot, p.socket or "-") for p in picks)))
        print("  mine o=%s e=%s" % (np.round(origin, 2), np.round(extent, 2)))
        if best:
            print("  game o=%s e=%s  (DesId %s)" % (
                np.round(best[2][0], 2), np.round(best[2][1], 2), best[1]))
    return (best[0] if best else None), ("n=%d" % len(pairs))


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    S.load()
    P.load()
    if args:
        targets = []
        for a in args:
            if a.endswith(".uasset"):
                targets.append(a)
                continue
            for vp in loader.index():
                if a.lower() in vp.lower() and vp.lower().endswith("_3p.uasset") \
                        and "/rec/" in vp.lower():
                    targets.append(vp)
                    break
    else:
        targets = []
        seen = set()
        for desid in P.all_desids():
            nodes = P.dedup(P.nodes_of(desid))
            if len(nodes) < 5:
                continue
            root = [n for n in nodes if n[1] in (0, None)]
            if not root:
                continue
            meshes = [m for m in S.item_meshes(root[0][2]) if m.endswith("_3p")]
            if not meshes:
                continue
            vp = P.vpath_of(meshes[0])
            if not vp or vp in seen:
                continue
            seen.add(vp)
            targets.append(vp)
            if len(targets) >= 24:
                break

    ok = bad = 0
    rows = []
    for vp in targets:
        d, note = score(vp, verbose=False)
        name = os.path.basename(vp)
        if d is None:
            print("  ??  %-46s %s" % (name, note))
            continue
        rows.append((d, name, note))
        if d < 1.5:
            ok += 1
        else:
            bad += 1
    rows.sort(reverse=True)
    for d, name, note in rows:
        print("  %s %6.2fcm  %-46s %s" % ("OK" if d < 1.5 else "BAD", d, name, note))
    print("\n%d ok / %d bad / %d total" % (ok, bad, len(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
