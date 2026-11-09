"""检视动画资产（AnimSequence）的最小解析器。

该游戏的检视动画是 ACL 压缩过的（import 里带 `CommonAnimBoneCompressionSettingsACL`），
完整解出骨骼关键帧需要一个 ACL 解码器；这里只取能确定拿到的元信息：

* `SequenceLength`（秒）——检视动画时长
* `NumFrames` —— 原始帧数
* `TrackToSkeletonMapTable` —— 影响到的骨骼数（数组长度）

用途：界面里按真实时长播放「检视转台」动画，并在卡片/检查器上显示时长。

实现说明：UE 的属性块是连续的 FPropertyTag（FName name / FName type / i32 size /
i32 arrayIndex / value），但 export 数据前还有一段我们没完全对上的头部，
所以这里改成「按名字索引在 uexp 里定位、再读后面的值」这种稳的做法。
"""
from __future__ import annotations

import struct
from typing import List, Optional

_PROP_KEYS = {
    "SequenceLength": ("<f", 4, "FloatProperty"),
    "Duration": ("<f", 4, "FloatProperty"),
    "NumFrames": ("<i", 4, "IntProperty"),
    "TrackToSkeletonMapTable": ("<i", 4, "ArrayProperty"),
}


def _names(upk) -> List[str]:
    names = getattr(upk, "names", None) or []
    return [n if isinstance(n, str) else str(n) for n in names]


def _find_varint(uexp: bytes, name_idx: int) -> List[int]:
    pat = struct.pack("<i", name_idx)
    hits: List[int] = []
    pos = uexp.find(pat)
    while pos >= 0:
        hits.append(pos)
        pos = uexp.find(pat, pos + 1)
    return hits


def _read_props(uexp: bytes, names: List[str]) -> dict:
    """在 uexp 里按名字定位属性，返回 {名字: 值}。"""
    out = {}
    for key, (fmt, width, want_type) in _PROP_KEYS.items():
        if key not in names:
            continue
        idxs = [i for i, n in enumerate(names) if n == key]
        if not idxs:
            continue
        for at in _find_varint(uexp, idxs[0]):
            # 布局：name(8B) + type(8B) + size(4B) + arrayIndex(4B) + value(24B 处)
            if at + 24 + width > len(uexp):
                continue
            type_idx = struct.unpack_from("<i", uexp, at + 8)[0]
            if not (0 <= type_idx < len(names)) or names[type_idx] != want_type:
                continue
            psize = struct.unpack_from("<i", uexp, at + 16)[0]
            if psize != width:
                continue
            value = struct.unpack_from(fmt, uexp, at + 24)[0]
            if key in ("SequenceLength", "Duration") and not (0.05 <= value <= 120.0):
                continue
            if key == "NumFrames" and not (1 <= value <= 100000):
                continue
            out[key] = value
            break
    return out


def anim_info(upk, uexp: bytes) -> dict:
    """从 AnimSequence 包里取时长/帧数/骨骼数（拿不到的字段留 None）。"""
    names = _names(upk)
    props = _read_props(uexp, names)
    duration = props.get("SequenceLength") or props.get("Duration")
    frames = props.get("NumFrames")
    bones = props.get("TrackToSkeletonMapTable")
    return {
        "duration": float(duration) if duration else None,
        "frames": int(frames) if frames else None,
        "bones": int(bones) if bones else None,
    }


def cached_info(loader_mod, vpath: str) -> Optional[dict]:
    """按资产路径取动画信息（内部缓存，解析失败返回 None 字段）。"""
    key = vpath.rsplit("/", 1)[-1]
    cache = cached_info.__dict__.setdefault("_cache", {})
    if key in cache:
        return cache[key]
    info = {"duration": None, "frames": None, "bones": None}
    try:
        from mini_upk import Upk                       # 局部导入，避免循环依赖
        blobs = loader_mod.load_blobs(vpath)
        upk = Upk(blobs.get("uasset", b""), blobs.get("uexp", b""))
        info = anim_info(upk, blobs.get("uexp", b""))
    except Exception:                                   # noqa: BLE001
        pass
    cache[key] = info
    return info
