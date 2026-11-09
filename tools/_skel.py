"""ReferenceSkeleton 解析 + 全局 rest 变换（针对该游戏 SkeletalMesh 包）。"""
import os
import struct
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
for _p in (os.path.join(BASE, "work"), os.path.join(BASE, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np                                    # noqa: E402

import mini_upk as mu                                 # noqa: E402
from core import loader                               # noqa: E402


def quat_mat(q):
    x, y, z, w = q
    n = (x * x + y * y + z * z + w * w) ** 0.5 or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], np.float64)


def xform(q, t, s=None):
    m = np.eye(4)
    m[:3, :3] = quat_mat(q)
    if s is not None:
        m[:3, :3] = m[:3, :3] @ np.diag(s)
    m[:3, 3] = t
    return m


def parse_skeleton(ue, names, verbose=False):
    """在 uexp 里找 FReferenceSkeleton：int32 N, N×(FName name + i32 parent), N×FTransform. """
    best = None
    for start in range(0, len(ue) - 8):
        n = struct.unpack_from("<i", ue, start)[0]
        if not (3 <= n <= 400):
            continue
        o = start + 4
        bones = []
        ok = True
        for _ in range(n):
            if o + 12 > len(ue):
                ok = False
                break
            idx, num = struct.unpack_from("<ii", ue, o)
            par = struct.unpack_from("<i", ue, o + 8)[0]
            if not (0 <= idx < len(names)) or num not in (0, 1) or not (-1 <= par < n):
                ok = False
                break
            bones.append((names[idx], par))
            o += 12
        if not ok or not bones:
            continue
        nameset = {b[0] for b in bones}
        if "Root" not in nameset and "S_root" not in nameset:
            continue
        # 紧跟 N 个 40 字节 FTransform（Quat16 + Vector12 + Vector12）
        pose_ok = 0
        o2 = o
        for _ in range(n):
            if o2 + 40 > len(ue):
                break
            q = np.array(struct.unpack_from("<4f", ue, o2), np.float64)
            ln = float(np.linalg.norm(q))
            if 0.9 < ln < 1.1:
                pose_ok += 1
            o2 += 40
        if pose_ok < max(1, n // 2):
            continue
        if best is None or n > len(best[0]):
            best = (bones, o)
    if not best:
        return None
    bones, pose_off = best
    n = len(bones)
    glob = []
    loc = []
    for i in range(n):
        o = pose_off + i * 40
        q = np.array(struct.unpack_from("<4f", ue, o), np.float64)
        t = np.array(struct.unpack_from("<3f", ue, o + 16), np.float64)
        s = np.array(struct.unpack_from("<3f", ue, o + 28), np.float64)
        loc.append(xform(q, t, s))
    for i, (nm, par) in enumerate(bones):
        glob.append(loc[i] if par < 0 else glob[par] @ loc[i])
    if verbose:
        print("bones at pose_off=%d n=%d" % (pose_off, n))
    return bones, glob


if __name__ == "__main__":
    for vp in sys.argv[1:]:
        ua = loader.read_entry(vp)
        ue = loader.read_entry(vp[:-7] + ".uexp")
        upk = mu.Upk(ua, ue)
        res = parse_skeleton(ue, upk.names)
        print("==", os.path.basename(vp))
        if not res:
            print("   no skeleton found")
            continue
        bones, glob = res
        for (nm, par), m in zip(bones, glob):
            t = m[:3, 3]
            print("   %-22s par=%-3d loc=(%8.3f %8.3f %8.3f)" % (nm, par, t[0], t[1], t[2]))
