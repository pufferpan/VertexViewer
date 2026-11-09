"""把「预设里引用了、但挂点表里没有网格」的件（虚空道具）按官方包围盒反推。

思路：`GunDescTable` 里的预设节点给的是道具 ID，其中一部分（默认枪托、
默认握把之类）在 `WeaponPartsMeshSocketNameInfo` 里没有对应网格。可是游戏
**自己的**包围盒表 `GunPresetBoundsTable` 是有的，于是：

    需要的枪尾位置 = 官方包围盒的 UE y 最小值
    某件枪托挂上去后的枪尾 = 挂点位置 + 该枪托网格自身的最小 GL x
    → 在所有候选枪托里挑一个最吻合的

这样选出来的件是**游戏数据算出来的**，不是按名字瞎猜。结果写到
`core/void_parts.json`，由 `core/gunsmith.guess_part_vpath()` 优先使用。

用法：
    python tools/fit_void_parts.py            # 跑全量并写文件
    python tools/fit_void_parts.py --dry 200  # 只跑前 200 个预设看效果
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np                                     # noqa: E402

from core import gunsmith as gs                        # noqa: E402
from core import loader, presets as P, sockets as S    # noqa: E402

OUT = os.path.join(BASE, "core", "void_parts.json")
FAMILIES = {
    "stock": ("Sto_point", "Sto2_point", "StoKit_point", "StockC_point",
              "StockP_point", "StoCase_point", "M16Sto_point"),
}


class Boxes:
    """网格 LOD0 包围盒缓存（GL 米）。"""

    def __init__(self) -> None:
        self.path = os.path.join(os.environ["LOCALAPPDATA"], "VertexViewer", "bbox_cache.json")
        try:
            with open(self.path, encoding="utf-8") as fh:
                self.data = json.load(fh)
        except (OSError, ValueError):
            self.data = {}
        self.dirty = False

    def get(self, vpath: str):
        key = S.asset_key(vpath)
        got = self.data.get(key)
        if got is not None:
            return None if got == [] else np.asarray(got, np.float32).reshape(2, 3)
        try:
            mesh = loader.load_mesh(vpath, lod=0)
        except Exception:                              # noqa: BLE001
            mesh = None
        lods = getattr(mesh, "lods", None)
        if not lods or getattr(lods[0], "positions", None) is None or not len(lods[0].positions):
            self.data[key] = []
            self.dirty = True
            return None
        pos = lodid = None
        pos = np.asarray(lods[0].positions, np.float32)
        box = [pos.min(axis=0).tolist(), pos.max(axis=0).tolist()]
        self.data[key] = box
        self.dirty = True
        return np.asarray(box, np.float32).reshape(2, 3)

    def save(self) -> None:
        if not self.dirty:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh)
        self.dirty = False


BOXES = Boxes()


def stock_candidates():
    """所有可能当枪托的网格（GL 米包围盒已缓存）。"""
    out = []
    for vpath, cn, _slot, gun, _kind in gs.catalog():
        low = vpath.lower()
        if "/sto/" not in low or not low.endswith("_3p.uasset"):
            continue
        box = BOXES.get(vpath)
        if box is None:
            continue
        out.append((vpath, box))
    return out


CANDIDATES = []


def pick_stock(base_vpath: str, needed_gl_x: float, socket_names) -> "tuple[str, float] | None":
    """在所有枪托里挑一个「挂到 socket 上以后枪尾正好落在 needed_gl_x」的。"""
    best = None
    for name in socket_names:
        try:
            mat = S.socket_matrix(base_vpath, name)
        except Exception:                              # noqa: BLE001
            mat = None
        if mat is None:
            continue
        sx = float(mat[0, 3])
        for vpath, box in CANDIDATES:
            rear = sx + float(box[0][0])
            d = abs(rear - needed_gl_x)
            if best is None or d < best[1]:
                best = (vpath, d, name)
        if best and best[1] < 0.02:                    # 2cm 内就别再看别的挂点了
            break
    if best is None or best[1] > 0.03:
        return None
    return best[0], best[1]


def main() -> int:
    dry = 0
    if "--dry" in sys.argv:
        dry = int(sys.argv[sys.argv.index("--dry") + 1])
    S.load()
    P.load()
    CANDIDATES.extend(stock_candidates())
    print("候选枪托 %d 个" % len(CANDIDATES))

    result = {}
    used = 0
    hits = 0
    for desid in P.all_desids():
        if dry and used >= dry:
            break
        ob = P.bounds_of(desid)
        if ob is None:
            continue
        nodes = P.dedup(P.nodes_of(desid))
        root = [n for n in nodes if n[1] in (0, None)]
        if not root or len(nodes) < 3:
            continue
        root_meshes = [m for m in S.item_meshes(root[0][2]) if "_ui" not in m]
        root_meshes.sort(key=lambda m: (not m.endswith("_3p"), len(m)))
        if not root_meshes:
            continue
        base_vpath = P.vpath_of(root_meshes[0])
        if not base_vpath:
            continue
        used += 1
        origin, extent = ob
        needed = float(origin[1] - extent[1]) / 100.0   # UE y min (cm) → GL x (m)
        for idx, pidx, item, psock in nodes:
            if pidx in (0, None):
                continue
            sock = S.socket_id_name(psock) or ""
            if not sock.lower().startswith(("sto", "stock")):
                continue
            if S.item_meshes(item):
                continue                               # 有网格的不用猜
            got = pick_stock(base_vpath, needed, [sock] + [
                n for n in FAMILIES["stock"] if n != sock])
            if got is None:
                continue
            vpath, d = got
            key = "%s|stock" % base_vpath
            prev = result.get(key)
            if prev is None or d < prev[1]:
                result[key] = [vpath, round(d * 100.0, 2)]
                hits += 1
        if used % 100 == 0:
            BOXES.save()
            print("  %d presets, %d keys" % (used, len(result)), flush=True)
    BOXES.save()

    offsets = {k: v[0] for k, v in result.items()}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({
            "format": "base_vpath|family -> mesh vpath；由 tools/fit_void_parts.py 按官方包围盒反推",
            "presets": used,
            "parts": offsets,
        }, fh, indent=1)
    print("%d 个虚空件反推成功（%d 预设），写入 %s" % (len(offsets), used, OUT))
    for k, (vp, d) in sorted(result.items(), key=lambda kv: -kv[1][1])[:12]:
        print("  %5.2fcm  %-40s %s" % (d, k.split("/")[-1], vp.split("/")[-1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
