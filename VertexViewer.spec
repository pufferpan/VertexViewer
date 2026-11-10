# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包脚本：VertexViewer（模型浏览器）。

用法： python -m PyInstaller --noconfirm VertexViewer.spec
产物： dist/VertexViewer/VertexViewer.exe（onedir，双击即用）
VERTEXVIEWER_ONEFILE=1 生成单文件；VERTEXVIEWER_ONEFILE=both 一次构建两种格式。
"""
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

# 文档工具的 native 目录不能参与应用 DLL 搜索。Poppler 的 ICU 带 _78
# 后缀，与 Qt 依赖的 Windows ICU ABI 不同；libheif 还包含旧的系统 API shim。
def _foreign_native_path(path):
    return "\\dependencies\\native" in str(path).replace("/", "\\").lower()

os.environ["PATH"] = os.pathsep.join(
    p for p in os.environ.get("PATH", "").split(os.pathsep)
    if not _foreign_native_path(p)
)

ROOT = os.path.dirname(os.path.abspath(SPECPATH if "SPECPATH" in globals() else os.getcwd()))
if not os.path.isdir(os.path.join(ROOT, "render")):
    ROOT = os.path.abspath(os.getcwd())

binaries = []
datas = []
hiddenimports = []
hiddenimports += collect_submodules("trimesh")
animation = os.path.join(ROOT, "assets", "animation")
if not os.path.isfile(os.path.join(animation, "VertexViewer.AnimationBridge.exe")):
    raise RuntimeError("请先构建 tools/animation_bridge 动画组件")
datas.append((animation, "assets/animation"))
STARTUP_AUDIO = os.path.join(ROOT, "assets", "audio", "OPEN_0.wav")
if not os.path.isfile(STARTUP_AUDIO):
    raise RuntimeError("缺少启动音乐 assets/audio/OPEN_0.wav")
datas.append((STARTUP_AUDIO, "assets/audio"))
hiddenimports.append("winsound")

# ---- 本体资源：着色器 + 索引/名字表 -----------------------------------------
shaders = os.path.join(ROOT, "render", "shaders")
if os.path.isdir(shaders):
    for name in os.listdir(shaders):
        datas.append((os.path.join(shaders, name), os.path.join("render", "shaders")))

work = os.path.join(ROOT, "work")
# index.tsv.gz 是流式索引（启动进度条走真进度），比 fileindex.json.gz 优先被读，
# 所以包里只带 TSV 这一份，省 8.6MB。

def _stamp() -> str:
    """从 core/version.py 读版本号（不存在就退回时间戳）。"""
    try:
        import re
        txt = open(os.path.join(ROOT, "core", "version.py"), encoding="utf-8").read()
        ver = re.search(r'VERSION\s*=\s*"([^"]+)"', txt)
        build = re.search(r'BUILD\s*=\s*"([^"]+)"', txt)
        return f"{ver.group(1) if ver else '1.0'}+{build.group(1) if build else 'dev'}"
    except Exception:
        return "1.0+dev"


# 索引不再随包（现在存成 %LOCALAPPDATA%\VertexViewer\index.db 一个 SQLite 文件，
# 第一次启动时从游戏 pak 现场建，之后永远复用它）。包里只带「静态查表数据」。
# 物品图标库（icons.db）与中文名表（names.json）属于游戏派生素材，不随包分发：
# 显示名由 core/humanize.py 从资产代号生成，图标用彩色占位块。
WORK_FILES = ("AESKey1.json", "mesh_catalog.json", "pakinfo.json")

# 界面里用到的图片（启动画面 logo 等）随包进 _internal/assets
LOGO = os.path.join(ROOT, "assets", "logo.png")
if os.path.exists(LOGO):
    datas.append((LOGO, "assets"))
# 启动画面用抠掉黑底的透明版（原图黑底画在蓝卡上是一块黑方块）
LOGO_NOBG = os.path.join(ROOT, "assets", "logo_nobg.png")
if os.path.exists(LOGO_NOBG):
    datas.append((LOGO_NOBG, "assets"))
# 标题用的粗体字（Noto Sans SC 子集，只留拉丁/数字/标点）
TITLE_FONT = os.path.join(ROOT, "assets", "fonts", "VertexViewer-Bold.ttf")
if os.path.exists(TITLE_FONT):
    datas.append((TITLE_FONT, "assets/fonts"))
# 用户指定的 MiSans 粗体子集（家族改名 VertexViewer MiSans，避免和系统 MiSans 撞名）
MISANS_FONT = os.path.join(ROOT, "assets", "fonts", "VertexViewer-MiSans-Bold.ttf")
if os.path.exists(MISANS_FONT):
    datas.append((MISANS_FONT, "assets/fonts"))
# 左上角横排 logo：原图（深色）+ 刷白版（画在蓝色卡片上用这份）
for _logo_name in ("logo_wordmark.png", "logo_wordmark_light.png"):
    _logo_path = os.path.join(ROOT, "assets", _logo_name)
    if os.path.exists(_logo_path):
        datas.append((_logo_path, "assets"))
# 首次启动向导的整屏背景（右半边 45° 三行截图，tools/make_wizard_bg.py 生成）
# wizard_bg.png 是合成好的整图（兜底/预览）；wizard_base.png + wizard_row*.png +
# wizard_rows.json 是分层素材，进场动画要靠它们让三行各自从屏幕外飞进来。
WIZARD_ASSETS = ["wizard_bg.png", "wizard_base.png", "wizard_row1.png",
                 "wizard_row2.png", "wizard_row3.png", "wizard_rows.json", "credits.json"]
for _wiz in WIZARD_ASSETS:
    _wiz_path = os.path.join(ROOT, "assets", _wiz)
    if os.path.exists(_wiz_path):
        datas.append((_wiz_path, "assets"))
    elif _wiz == "wizard_bg.png":
        print("[spec] 警告：assets/wizard_bg.png 不存在，首次向导会退回纯色背景")
    elif _wiz == "wizard_rows.json":
        print("[spec] 警告：assets/wizard_rows.json 不存在，进场动画会被跳过")
# 静态查表数据（名字表 / 类名表 / 密钥）改成**打进 _internal/dfdata**：
# 它们跟 exe 一起走，不会因为别人只拷了 exe、或者漏拷 data/ 就变成全英文名；
# data/ 里放同名文件仍然可以覆盖（给想自己改名字表的人留口子）。
for name in WORK_FILES:
    src = os.path.join(work, name)
    if os.path.exists(src):
        datas.append((src, "dfdata"))
# data/ 里只留给人看/改的东西（说明、版本），不再放必需数据

# 改枪挂点标定数据（伸缩托默认伸展量）：core/gunsmith.py 运行时要读，
# 冻进 _internal/core/ 才能和源码态的 core/part_offsets.json 对上。
_PART_OFFSETS = os.path.join(ROOT, "core", "part_offsets.json")
if os.path.exists(_PART_OFFSETS):
    datas.append((_PART_OFFSETS, os.path.join("core")))
else:
    print("[spec] 警告：core/part_offsets.json 不存在，伸缩托会退回不伸展")

# ---- 第三方包：FluentPy 控件/OpenGL/BC 解码器 --------------------------------
# fluentpy = XDDXMT 的 FluentPy，界面只剩这一套（qfluentwidgets 已整体删除）。
for pkg in ("fluentpy", "texture2ddecoder", "darkdetect"):
    try:
        b, d, h = collect_all(pkg)
        binaries += b
        datas += d
        hiddenimports += h
    except Exception as exc:                                    # noqa: BLE001
        print(f"[spec] collect_all({pkg}) skipped: {exc}")

hiddenimports += [
    "OpenGL",
    "OpenGL.GL",
    "Crypto",
    "Crypto.Cipher",
    "Crypto.Cipher.AES",
    "Crypto.Util.Padding",
    "tools",
    "tools.pakpick",
    "numpy",
    "PIL.Image",
    "darkdetect",
    "win32api",
    "win32con",
    "win32gui",
    "win32print",
]

# FluentPy 的分支模块（theme/widgets/icons 子包）是运行时按需 import 的，
# PyInstaller 静态分析抓不全 —— 直接整包收集。
for pkg in ("fluentpy",):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:                                        # noqa: BLE001
        pass

block_cipher = None

a = Analysis(
    [os.path.join(ROOT, "__main__.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest", "torch", "torchvision", "scipy",
              "onnxruntime", "sklearn", "pandas", "IPython", "sympy", "numba",
              "llvmlite", "cv2", "tqdm", "notebook", "jupyter", "setuptools",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
              "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DAnimation",
              "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DExtras",
              "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
              "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
              "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtBluetooth",
              "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtSerialPort",
              "PySide6.QtSensors", "PySide6.QtSpatialAudio", "PySide6.QtTest",
              "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools",
              "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine",
              "PySide6.QtTextToSpeech", "PySide6.QtPdf", "PySide6.QtPdfWidgets"],
    noarchive=False,
    cipher=block_cipher,
)
# 也过滤缓存 Analysis 里已经解析过的外部文档工具 DLL，确保增量打包安全。
foreign_dlls = [entry for entry in a.binaries if _foreign_native_path(entry[1])]
for entry in foreign_dlls:
    print("[spec] 排除外部工具 DLL:", entry[0], entry[1])
a.binaries = [entry for entry in a.binaries if not _foreign_native_path(entry[1])]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

build_mode = os.environ.get("VERTEXVIEWER_ONEFILE", "")
single_file = build_mode == "1"


def executable(single_file):
    return EXE(
        pyz,
        a.scripts,
        *([a.binaries, a.datas] if single_file else []),
        [],
        exclude_binaries=not single_file,
        name="VertexViewer",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,          # 无控制台窗口；出问题可用 VertexViewer-debug.exe
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )


exe = executable(single_file)

if not single_file:
    coll = COLLECT(
        exe, a.binaries, a.datas,
        strip=False, upx=False, upx_exclude=[], name="VertexViewer",
    )

# Both formats share one dependency analysis and the same frozen Python code.
if build_mode == "both":
    single_exe = executable(True)

# ---- 收尾：把索引/名字表放到 dist/VertexViewer/data/（可见、可替换）-------------
import shutil

DIST = os.path.join(globals().get("DISTPATH", os.path.join(ROOT, "dist")), "VertexViewer")
DATA = os.path.join(DIST, "data")
if os.path.isdir(DIST):
    os.makedirs(DATA, exist_ok=True)
    # 数据已经在 _internal/dfdata 里了（见上），data/ 只放「人能看/能改」的东西，
    # 免得再放一份让 zip 白白大一倍、也免得用户以为删掉 data/ 就丢了数据。
    manual = os.path.join(ROOT, "docs", "使用说明.txt")
    if os.path.exists(manual):
        shutil.copy2(manual, os.path.join(DATA, "使用说明.txt"))
    # 顺手把旧版本残留的索引文件清掉：以前 data/ 里放过 index.tsv.gz /
    # fileindex.json.gz，覆盖安装时会留下来，害得 WORK 指到奇怪的地方。
    for stale in ("index.tsv.gz", "fileindex.json.gz", "fileindex.json",
                  "index.db", "index.db-wal", "index.db-shm"):
        leftover = os.path.join(DATA, stale)
        if os.path.exists(leftover):
            os.remove(leftover)
            print("[spec] 清掉旧索引残留:", stale)
    hidden = os.path.join(DIST, "_internal", "dfdata")
    os.makedirs(hidden, exist_ok=True)
    print("[spec] dfdata/:", sorted(os.listdir(hidden)))
    import time as _time
    info = [
        "VertexViewer · 模型浏览器",
        "构建时间：" + _time.strftime("%Y-%m-%d %H:%M"),
        "版本：" + _stamp() + "（感谢名单 / OPEN_0 启动音乐 / 物品检视方向修复 / 第一人称与改枪检视 / GLB 动画导出）",
        "报问题时请把这一行版本号发过来，能立刻判断是不是新包。",
        "",
        "data/ 目录说明",
        "- （索引不在这里）  资产索引存在用户目录的 VertexViewer\\index.db（SQLite），",
        "- mesh_catalog.json  路径→类名，检视动画扫描用它",
        "- names.json         中文名表",
        "- AESKey1.json       pak 解包密钥",
        "- pakinfo.json       pak 元数据",
        "- icon_table.json    自定义图标表（换图标后自动生成，可复制给别人）",
        "- icons/             自定义图标图片",
        "",
        "这些文件都可以直接替换：换掉 names.json 就换名字，换掉 icon_table.json 就换图标。",
    ]
    with open(os.path.join(DATA, "版本信息.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(info) + "\n")
    print("[spec] data/ 已就绪:", sorted(os.listdir(DATA)))
