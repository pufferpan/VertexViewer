"""Oodle 解压（UE pak 里压缩块用的那个）。

DL 名字各家版本不一样（oo2core_6/7/8/9_win64.dll），查找顺序：

1. 环境变量 ``VERTEXVIEWER_OODLE`` 指向的 dll（想让用户自己放，就放这儿）
2. 程序目录旁边的 ``oodle/`` 或 ``_internal/oodle/``（打包时可选带上）
3. 游戏自己的 ``Binaries/Win64/oo2core_*_win64.dll``

以前的实现放在 ``tools/pakpick.py`` 里，而 pakpick 又写死了开发机路径，
``cache.py`` 失败回退到它 → 别人机器上报「读不到 fileindex.json」。
现在解压这块归 core，pakpick 只做兼容别名。
"""
from __future__ import annotations

import ctypes
import glob
import os
import sys

_ARGS = [ctypes.c_void_p, ctypes.c_longlong, ctypes.c_void_p, ctypes.c_longlong,
         ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
         ctypes.c_longlong, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
         ctypes.c_longlong, ctypes.c_int]


class Oodle:
    """薄封装：``decompress(压缩字节, 原始大小) -> bytes | None``。"""

    def __init__(self, dll: str | None = None) -> None:
        path = dll or find_oodle_dll()
        if not path:
            raise FileNotFoundError(
                "找不到 Oodle 解压库（oo2core_*_win64.dll）。"
                "它跟着游戏一起装，通常在游戏目录的 Binaries\\Win64 里；"
                "也可以把 dll 放到程序目录的 oodle\\ 下，"
                "或者用环境变量 VERTEXVIEWER_OODLE 指定路径。")
        self.path = path
        self.lib = ctypes.CDLL(path)
        fn = self.lib.OodleLZ_Decompress
        fn.restype = ctypes.c_longlong
        fn.argtypes = _ARGS
        self._fn = fn

    def decompress(self, comp: bytes, raw_size: int):
        if not comp or raw_size <= 0:
            return None
        out = ctypes.create_string_buffer(raw_size)
        n = self._fn(comp, len(comp), out, raw_size, 1, 0, 0,
                     None, 0, None, None, None, 0, 3)
        if n <= 0:
            return None
        return out.raw[:n]

    def __repr__(self) -> str:                                   # pragma: no cover
        return f"<Oodle {os.path.basename(self.path)}>"


# --------------------------------------------------------------------------- #
# dll 查找
# --------------------------------------------------------------------------- #
def _app_dirs() -> list:
    dirs = []
    env = os.environ.get("VERTEXVIEWER_OODLE")
    if env and os.path.isfile(env):
        dirs.append(os.path.dirname(env))
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    exe_dir = os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else __file__))
    bundle = getattr(sys, "_MEIPASS", exe_dir)
    for base in (exe_dir, bundle, root):
        for sub in ("oodle", os.path.join("_internal", "oodle"), ""):
            dirs.append(os.path.join(base, sub) if sub else base)
    out = []
    for d in dirs:
        if d not in out:
            out.append(d)
    return out


def find_oodle_dll() -> str | None:
    env = os.environ.get("VERTEXVIEWER_OODLE")
    if env and os.path.isfile(env):
        return env
    pats = ("oo2core*win64.dll", "oo2core*.dll", "oodle*.dll")
    for d in _app_dirs():
        for pat in pats:
            hits = sorted(glob.glob(os.path.join(d, pat)))
            if hits:
                return hits[-1]
    # 游戏自带的那份（跟 pak 目录同级的 Binaries/Win64）
    try:
        from . import loader  # 延迟导入，避免循环
        game = getattr(loader, "_GAME_ROOT", "") or ""
    except Exception:                                            # noqa: BLE001
        game = ""
    if game:
        for pat in pats:
            hits = sorted(glob.glob(os.path.join(
                game, "**", "Binaries", "Win64", pat), recursive=True))
            if hits:
                return hits[-1]
    return None


_OO: Oodle | None = None


def get_oodle() -> Oodle:
    global _OO
    if _OO is None:
        _OO = Oodle()
    return _OO


def oodle():
    """兼容旧调用：返回 Oodle 实例。"""
    return get_oodle()
