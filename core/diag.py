"""诊断报告：把「别人电脑上出问题」需要的全部信息打成一页文本。

设计目标是**一眼能判**：
- 跑的是哪个版本、是不是打包版；
- 名字表/类名表/密钥/index.db 各自在哪、读没读到（找不到时把找过的路径都列出来）；
- 游戏 pak 目录能不能读、有多少个 pak、能不能重建索引；
- 数据规模对不对（索引条数、可渲染网格数、中文名条数、检视动画数）；
- 最近一次启动日志的结尾、配置内容、环境信息。

不采集任何游戏文件内容，也不联网；只写本地一个 txt。
"""
from __future__ import annotations

import os
import platform
import sys
import time
import traceback
from typing import List

FILES = ("names.json", "mesh_catalog.json", "AESKey1.json", "pakinfo.json")


def _fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}GB"


def _stat(path: str) -> str:
    if not path or not os.path.exists(path):
        return "缺失"
    try:
        st = os.stat(path)
        return f"{_fmt_size(st.st_size)} · {time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))}"
    except OSError as exc:
        return f"无法读取（{exc}）"


def _tail(path: str, lines: int = 24) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            data = fh.readlines()
        return [ln.rstrip("\n") for ln in data[-lines:]]
    except OSError:
        return []


def _gpu() -> str:
    """当前 OpenGL 渲染器名字（拿不到就写未知，不抛异常）。"""
    try:
        from PySide6.QtGui import QOffscreenSurface, QOpenGLContext
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is None:
            return "（启动早期生成，Qt 还没起来，未测）"
        surf = QOffscreenSurface()
        surf.create()
        ctx = QOpenGLContext()
        ctx.create()
        if not ctx.makeCurrent(surf):
            return "无法创建 OpenGL 上下文（可能是驱动太老 / 远程桌面）"
        fn = ctx.functions()
        name = fn.glGetString(0x1F01)          # GL_RENDERER
        ver = fn.glGetString(0x1F02)           # GL_VERSION
        out = f"{name} | {ver}"
        ctx.doneCurrent()
        return out
    except Exception as exc:                                     # noqa: BLE001
        return f"读取失败：{type(exc).__name__}: {exc}"


def collect() -> dict:
    """把报告需要的原始数据都收齐（界面和文本共用）。"""
    from core import loader as L
    from core import indexdb, version

    info = {
        "生成时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "版本": version.stamp(),
        "是否打包版": "是（PyInstaller）" if L._frozen() else "否（源码运行）",
        "exe / 入口": sys.executable if L._frozen() else os.path.abspath(sys.argv[0] or ""),
        "安装目录": (os.path.dirname(os.path.abspath(sys.executable))
                     if L._frozen() else L._bundle_dir()),
        "打包资源目录": L._bundle_dir(),
        "工作目录 WORK": L.WORK,
        "游戏 pak 目录": L.PAK_DIR or "（未找到，等用户指路）",
        "Python": platform.python_version(),
        "系统": platform.platform(),
        "CPU": platform.processor() or "未知",
    }
    try:
        from core.oodle import find_oodle_dll
        info["Oodle 解压库"] = find_oodle_dll() or "（没找到，压缩资产读不出来）"
    except Exception as exc:                                     # noqa: BLE001
        info["Oodle 解压库"] = f"（检测失败：{exc}）"
    try:
        from PySide6 import __version__ as qtv
        from PySide6.QtCore import qVersion
        info["Qt"] = f"PySide6 {qtv} / Qt {qVersion()}"
    except Exception:                                            # noqa: BLE001
        pass
    info["OpenGL"] = _gpu()

    # ---- 静态数据：谁提供的、在哪个路径 ----
    static = []
    for name in FILES:
        path = L.data_file(name)
        static.append((name, path or "（没有找到）", _stat(path)))
    info["静态数据"] = static

    # ---- 索引数据库：先确保建好再统计（启动早期生成报告时 DB 可能还没建）----
    try:
        L.index()                     # 没有就会现场扫 pak 建 + 写 index.db
    except Exception:                 # noqa: BLE001
        pass
    db = indexdb.db_path()
    info["索引数据库"] = db
    info["索引状态"] = f"{indexdb.count()} 条 · {_stat(db)}"
    info["索引错误"] = (getattr(L, "INDEX_ERROR", "") or "").strip() or "（无）"

    # ---- 规模 ----
    try:
        idx = L.index()
        info["索引条数"] = f"{len(idx)}"
        try:
            from core.loader import catalog as _cat
            cls = _cat()
            meshes = sum(1 for v in cls.values()
                         if v in ("StaticMesh", "SkeletalMesh"))
            info["可渲染网格"] = f"{meshes}（按 mesh_catalog 的类名统计）"
        except Exception:                                        # noqa: BLE001
            models = [k for k in idx if k.lower().endswith(".uasset")
                      and "/models/" in k.lower()]
            info["可渲染网格"] = f"{len(models)}（粗略：带 /models/ 的 uasset）"
    except Exception as exc:                                     # noqa: BLE001
        info["索引条数"] = f"读取失败：{type(exc).__name__}: {exc}"
    try:
        from core import cnnames
        st = cnnames.stats() or {}
        info["中文名条数"] = f"{st.get('count', '?')}（生成于 {st.get('generated', '?')}）"
    except Exception as exc:                                     # noqa: BLE001
        info["中文名条数"] = f"读取失败：{type(exc).__name__}: {exc}"
    try:
        info["检视动画物品数"] = f"{len(L.inspect_animations())}"
    except Exception as exc:                                     # noqa: BLE001
        info["检视动画物品数"] = f"读取失败：{type(exc).__name__}: {exc}"
    try:
        from core import icons as _ic, iconpack
        info["游戏图标目录数"] = f"{(_ic.stats() or {}).get('assets', 0)} 个名字 / "                                 f"{(_ic.stats() or {}).get('ids', 0)} 个 ID"
        info["随包图标库"] = f"{iconpack.count()} 张（{iconpack.pack_path() or '未找到'}）"
    except Exception as exc:                                     # noqa: BLE001
        info["随包图标库"] = f"读取失败：{type(exc).__name__}: {exc}"

    # ---- 目录里到底有什么 ----
    listing = []
    bundle = L._bundle_dir()
    exe_dir = (os.path.dirname(os.path.abspath(sys.executable))
               if L._frozen() else bundle)
    for d in (os.path.join(exe_dir, "data"),
              os.path.join(bundle, "dfdata"),
              os.path.join(exe_dir, "_internal", "dfdata")):
        if os.path.isdir(d):
            try:
                items = sorted(os.listdir(d))[:20]
                listing.append((d, f"{len(os.listdir(d))} 项：{', '.join(items)}"))
            except OSError as exc:
                listing.append((d, f"列不出来：{exc}"))
        else:
            listing.append((d, "目录不存在"))
    info["目录清单"] = listing

    # ---- 日志与配置 ----
    localapp = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    logdir = os.path.join(localapp, "VertexViewer", "logs")
    info["日志目录"] = logdir
    cfg = os.path.join(localapp, "VertexViewer", "config.json")
    try:
        with open(cfg, "r", encoding="utf-8") as fh:
            info["配置"] = fh.read().strip()
    except OSError:
        info["配置"] = "（没有 config.json）"

    lines = []
    for name in sorted(os.listdir(logdir)) if os.path.isdir(logdir) else []:
        if name.lower().endswith(".log"):
            path = os.path.join(logdir, name)
            lines.append(f"--- {name} 末尾 ---")
            lines.extend(_tail(path))
    info["日志尾巴"] = lines
    return info


def render(info: dict) -> str:
    """把 collect() 的结果排成给人看的文本。"""
    out = []
    out.append("=" * 68)
    out.append("VertexViewer 诊断报告")
    out.append("=" * 68)
    out.append("一定一定把这个文件发送给开发者：3281644795（不然我只能帮你算一卦）")
    out.append("")
    for key in ("生成时间", "版本", "是否打包版", "exe / 入口", "安装目录",
                "打包资源目录", "工作目录 WORK", "游戏 pak 目录", "Oodle 解压库",
                "Python", "系统", "CPU", "Qt", "OpenGL"):
        if key in info:
            out.append(f"{key:<12}{info[key]}")
    out.append("")
    out.append("--- 静态数据（名字表/类名表/密钥）---")
    out.append("名字                实际使用的路径")
    for name, path, stat in info.get("静态数据", []):
        out.append(f"{name:<18} {path}")
        out.append(f"{'':<18} {stat}")
    out.append("")
    out.append("--- 资产索引（SQLite）---")
    out.append(f"数据库        {info.get('索引数据库')}")
    out.append(f"状态          {info.get('索引状态')}")
    out.append(f"索引条数      {info.get('索引条数')}")
    out.append(f"可渲染网格    {info.get('可渲染网格')}")
    out.append(f"中文名        {info.get('中文名条数')}")
    out.append(f"检视动画      {info.get('检视动画物品数')}")
    out.append(f"游戏图标      {info.get('游戏图标目录数')}")
    out.append(f"随包图标库    {info.get('随包图标库')}")
    if info.get("索引错误") and info["索引错误"] != "（无）":
        out.append("")
        out.append("--- 索引错误 ---")
        out.append(info["索引错误"])
    out.append("")
    out.append("--- 目录清单 ---")
    for path, desc in info.get("目录清单", []):
        out.append(f"{path}")
        out.append(f"    {desc}")
    out.append("")
    out.append("--- 配置 ---")
    out.append(str(info.get("配置")))
    out.append("")
    out.append("--- 日志 ---")
    out.extend(info.get("日志尾巴") or ["（没有日志）"])
    out.append("")
    out.append("=" * 68)
    out.append("把这一整段发回去即可定位问题。报告里没有游戏文件内容。")
    return "\n".join(out)


def write_report(path: str = "") -> str:
    """生成并写盘，返回文件路径。"""
    localapp = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    if not path:
        logdir = os.path.join(localapp, "VertexViewer", "logs")
        os.makedirs(logdir, exist_ok=True)
        path = os.path.join(logdir, "诊断报告-" + time.strftime("%Y%m%d-%H%M%S") + ".txt")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    text = render(collect())
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    return path


def install_excepthook() -> None:
    """未捕获异常时自动落一份报告，别人只要把文件发回来就行。"""
    def _hook(exc_type, exc, tb):
        try:
            localapp = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
            logdir = os.path.join(localapp, "VertexViewer", "logs")
            os.makedirs(logdir, exist_ok=True)
            path = os.path.join(logdir, "崩溃-" + time.strftime("%Y%m%d-%H%M%S") + ".txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("".join(traceback.format_exception(exc_type, exc, tb)))
                fh.write("\n\n")
                try:
                    fh.write(render(collect()))
                except Exception:                                # noqa: BLE001
                    fh.write("（诊断信息收集失败）\n")
                fh.write("\n")
            print(f"[diag] 崩溃报告 -> {path}", file=sys.stderr)
        except Exception:                                        # noqa: BLE001
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook
