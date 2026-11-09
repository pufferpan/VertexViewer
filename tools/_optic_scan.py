"""扫一批机匣，算「瞄具底面 − 机匣顶面」的偏差，找位置异常的枪。

正数 = 悬空（瞄具坐在导轨上方没贴合），负数 = 陷进导轨。
顺便把每把枪瞄具用的 socket 打出来，方便看是不是挂到了 Rea_point / Mou_point 这种基座。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    from core import gunsmith as gs, loader

    idx = loader.index()
    bases = [k for k in idx
             if "/Models/Weapons/Parts/Rec/" in k and k.lower().endswith("_3p.uasset")]
    rows = []
    for vp in sorted(bases)[:limit]:
        try:
            picks = gs.official_loadout(vp)
            bundle = loader.load_model(vp, want_textures=False)
            base_lod = gs._lod0(bundle) if bundle is not None else None
            if base_lod is None:
                continue
            pairs = []
            for sp in picks:
                b = loader.load_model(sp.vpath, want_textures=False)
                lod = gs._lod0(b) if b is not None else None
                if lod is not None:
                    pairs.append((sp, lod))
            world = gs.resolve_placements(vp, base_lod, pairs)
        except Exception as exc:                            # noqa: BLE001
            print("skip", os.path.basename(vp), exc)
            continue
        top = float(base_lod.positions[:, 1].max())
        for sp, lod in pairs:
            if sp.slot != "optic":
                continue
            mat = world.get(id(sp))
            if mat is None:
                continue
            p = lod.positions @ mat[:3, :3].T + mat[:3, 3]
            bottom = float(p[:, 1].min())
            rows.append((abs(bottom - top), os.path.basename(vp)[:-9], sp.socket,
                         round((bottom - top) * 100, 1)))

    rows.sort(reverse=True)
    print("瞄具相对机匣顶面的偏差（cm）：")
    for _d, gun, sock, cm in rows:
        print(f"  {cm:+7.1f}  {gun:30} socket={sock}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
