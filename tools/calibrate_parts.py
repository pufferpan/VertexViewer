"""标定「配件的默认额外位移」——用官方包围盒当标准答案。

## 为什么需要

挂点（`WeaponPartsMeshSocketNameInfo`）能解释 40 个官方预设里 26 个的包围盒
（误差 < 1cm），但**伸缩托**这类件在游戏里默认是「拉出一段」的，那段距离不在
挂点表里。实测：`sto_t_hk437_136` 恒差 -9.18cm、`sto_t_am17_141` 恒差 -5.08cm，
标准差 0.00~0.01，说明是每件固定的伸展量。

## 做法

对每个官方预设：
1. 用 `gunsmith.resolve_placements`（socket 链）算出每件的世界矩阵；
2. 把每个件的包围盒变换后求并，得到「我的包围盒」；
3. 和 `GunPresetBoundsTable` 的官方包围盒比，取前/后端残差；
4. 残差归给「真正顶到那一端的那件」（通常是枪托 / 枪管 / 枪口）；
5. 同一件跨多个预设取中位数，写进 `core/part_offsets.json`。

用法：
    python tools/calibrate_parts.py            # 全量标定（含 bbox 缓存，首次约 10 分钟）
    python tools/calibrate_parts.py --limit 400
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
from core.types import MeshLOD                         # noqa: E402

_CORNERS = np.array([[x, y, z]
                     for x in (0.0, 1.0) for y in (0.0, 1.0) for z in (0.0, 1.0)],
                    np.float32)


def bbox_cache_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "VertexViewer", "bbox_cache.json")


class Boxes:
    """网格包围盒缓存（GL 米）。只算 min/max，不碰材质和贴图。"""

    def __init__(self):
        self.path = bbox_cache_path()
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
            self.data[key] = []                        # [] 表示「解析失败」，别再试
            self.dirty = True
            return None
        pos = np.asarray(lods[0].positions, np.float64)
        out = np.stack([pos.min(axis=0), pos.max(axis=0)]).astype(np.float32)
        self.data[key] = out.tolist()
        self.dirty = True
        return out

    def save(self):
        if not self.dirty:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh)
        except OSError:
            pass


def fake_lod(box) -> MeshLOD:
    """把包围盒包成一个只有 8 个角点的 MeshLOD（给 resolve_placements 用）。"""
    lo, hi = box
    span = (hi - lo)[None, :]
    return MeshLOD(positions=(lo[None, :] + _CORNERS * span).astype(np.float32))


def assemble_box(base_vpath: str, nodes) -> "tuple[np.ndarray, np.ndarray, str, str, bool] | None":
    """用挂点链拼出一个预设的包围盒。

    返回 (lo, hi, 前端件键, 后端件键, 是否全部解析成功)。
    """
    root = [n for n in nodes if n[1] in (0, None)]
    if not root:
        return None
    root_meshes = [m for m in S.item_meshes(root[0][2]) if "_ui" not in m]
    root_meshes.sort(key=lambda m: (not m.endswith("_3p"), len(m)))
    if not root_meshes:
        return None
    base_vp = P.vpath_of(root_meshes[0]) or base_vpath

    parts = []
    complete = True
    for idx, pidx, item, psock in nodes:
        if pidx in (0, None):
            continue
        sock = S.socket_id_name(psock)
        meshes = [m for m in S.item_meshes(item) if "_ui" not in m]
        meshes.sort(key=lambda m: (not m.endswith("_3p"), len(m)))
        vpath = P.vpath_of(meshes[0]) if meshes else ""
        if not vpath:                          # 虚空道具：跟 gunsmith 一样按名字兜底
            complete = False
            vpath = gs.guess_part_vpath(base_vp, gs.SOCKET_FAMILY.get(sock.lower(), ""))
        if not vpath:
            continue
        spec = gs.PartSpec(vpath=vpath, slot="other", socket=sock)
        parts.append((spec, vpath))

    bboxes = {}
    kept = []
    for spec, vp in parts:
        box = BOXES.get(vp)
        if box is None:                        # 这件网格解不出来 → 跳过（别整把枪作废）
            complete = False
            continue
        bboxes[id(spec)] = box
        kept.append((spec, vp))
    parts = kept
    if len(parts) < 2:
        return None
    bb = BOXES.get(base_vp)
    if bb is None:
        return None
    lod_base = fake_lod(bb)

    plan = gs.resolve_placements(base_vp, lod_base,
                                 [(s, fake_lod(bboxes[id(s)])) for s, _vp in parts])
    lo = np.array([1e9, 1e9, 1e9], np.float64)
    hi = -lo.copy()
    front_family = rear_family = ""
    front_x = 1e9
    rear_x = -1e9
    for spec, vp in parts:
        world = plan.get(id(spec))
        if world is None:
            continue
        box = bboxes[id(spec)]
        corners = (box[0][None, :] + _CORNERS * (box[1] - box[0])[None, :])
        gl = corners @ world[:3, :3].T + world[:3, 3]
        lo = np.minimum(lo, gl.min(axis=0))
        hi = np.maximum(hi, gl.max(axis=0))
        if float(gl[:, 0].min()) < front_x:
            front_x = float(gl[:, 0].min())
            front_family = S.asset_key(vp)
        if float(gl[:, 0].max()) > rear_x:
            rear_x = float(gl[:, 0].max())
            rear_family = S.asset_key(vp)
    corners = (bb[0][None, :] + _CORNERS * (bb[1] - bb[0])[None, :])
    lo = np.minimum(lo, corners.min(axis=0))
    hi = np.maximum(hi, corners.max(axis=0))
    return lo, hi, front_family, rear_family, complete


BOXES = Boxes()


def main() -> int:
    limit = 0
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    S.load()
    P.load()
    print("sockets=%s presets=%s" % (S.table_size(), P.size()))

    samples: dict[str, list] = {}
    used = 0
    for desid in P.all_desids():
        if limit and used >= limit:
            break
        ob = P.bounds_of(desid)
        if ob is None:
            continue
        nodes = P.dedup(P.nodes_of(desid))
        if len(nodes) < 3:
            continue
        got = assemble_box("", nodes)
        if got is None:
            continue
        lo, hi, front_key, rear_key, _complete = got
        used += 1
        origin, extent = ob
        # GL x = UE y（前后）；官方包围盒中心 ± 半长
        game_front = float(origin[1] - extent[1])        # UE 最小 y = 最后端
        game_rear = float(origin[1] + extent[1])         # UE 最大 y = 最前端
        mine_front = float(lo[0]) * 100.0                # GL x 最小 = 最后端
        mine_rear = float(hi[0]) * 100.0
        d_front = game_front - mine_front                # 后端残差
        d_rear = game_rear - mine_rear                   # 前端残差
        # 只有「一端完全吻合、另一端差得多」才算某件缺了一段；
        # 两端都差 = 整把枪比例/解析有问题，丢掉。
        # 注意：GL x 最小 = 枪尾（枪托那一侧），最大 = 枪口那一侧。
        if abs(d_rear) < 0.6 and abs(d_front) > 0.5 and front_key and "/sto/" in front_key:
            samples.setdefault(front_key, []).append(d_front)
        if used % 25 == 0:
            BOXES.save()
            print("  %d presets, %d keys" % (used, len(samples)), flush=True)
    BOXES.save()

    offsets = {}
    report = []
    for key, vals in samples.items():
        if len(vals) < 2:                                # 样本太少不标定
            continue
        arr = np.asarray(vals, np.float64)
        med = float(np.median(arr))
        std = float(arr.std())
        if abs(med) < 0.2:
            continue
        if std > (0.3 if len(vals) < 3 else 1.5):        # 不稳定就当 0
            continue
        # 只标定「枪托」：其他族（枪管/枪口/瞄具）socket 摆法已验证精确，
        # 出现残差一定是预设里缺件，硬标定反而会把正确的位置拽歪。
        if "/sto/" not in key:
            continue
        # GL 的 +x 是枪口方向，残差为正表示游戏里这件的枪尾更靠后
        offsets[key] = [round(med / 100.0, 5), 0.0, 0.0]
        report.append((abs(med), len(arr), med, std, key))
    report.sort(reverse=True)
    for _a, n, med, std, key in report[:40]:
        print("  n=%-3d med=%+7.2f std=%5.2f  %s" % (n, med, std, key.split("/")[-1]))
    print("\n%d keys with |offset| >= 0.2cm (%d presets)" % (len(offsets), used))

    out = os.path.join(BASE, "core", "part_offsets.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({
            "format": "GL metres; 由 tools/calibrate_parts.py 用 GunPresetBoundsTable 标定",
            "presets": used,
            "offsets": offsets,
        }, fh, indent=1, sort_keys=True)
    print("写入", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
