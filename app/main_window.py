"""Main window: nav shell, asset loading, cache lifecycle, OBJ export, capture."""
from __future__ import annotations

import os
import sys
import time
import traceback
from typing import Any, Dict, List, Optional

from app.browser import ModelBrowser
from app.fluent_api import (FluentWindow, InfoBar, InfoBarPosition, QApplication,
                            QColor, QFileDialog, QIcon, QKeySequence, QShortcut,
                            QThread, QTimer, Qt, Signal, Theme, icon,
                            isDarkTheme, setTheme)
from app.gunsmith_page import GunsmithPage
from app.inspection_page import InspectionPage
from app.pages import (CAPTURE_DIR, ExportPage, LibraryPage, MaterialsPage,
                       SettingsPage, TexturesPage, human_bytes)
from app.viewer import Viewport, create_viewport, describe_backend
from cache import get_cache
from exporters import export_obj, export_obj_lods, export_static_glb, skeleton_available

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 窗口外壳（标题栏 + 导航栏）要和内容区一个色，否则顶部会横一条异色带。
# 深色用 FluentPy 的 theme.tokens.background（#1f2633），浅色沿用系统浅灰。
TITLEBAR_LIGHT = "#f3f3f3"
TITLEBAR_DARK = "#1f2633"


def _dwm_set(hwnd: int, attribute: int, color: str) -> None:
    """给原生标题栏/边框染色（Win11 22000+ 才有；老系统静默失败）。"""
    try:
        import ctypes
        from ctypes import wintypes

        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        colorref = wintypes.DWORD(r | (g << 8) | (b << 16))
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute(
            wintypes.HWND(int(hwnd)),
            ctypes.c_int(attribute),
            ctypes.byref(colorref),
            ctypes.sizeof(colorref),
        )
    except Exception:                                       # noqa: BLE001
        pass


def blend_caption(hwnd: int, color: str) -> None:
    """标题栏、边框、文字一起调，让系统画的标题条和窗口主体连成一体。"""
    _dwm_set(hwnd, 35, color)          # DWMWA_CAPTION_COLOR
    _dwm_set(hwnd, 34, color)          # DWMWA_BORDER_COLOR
    _dwm_set(hwnd, 36, "#f5f7fb")      # DWMWA_TEXT_COLOR



def _export_root() -> str:
    """导出目录：打包版放 exe 旁边，源码版放项目里的 exports/。"""
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "exports")
    return os.path.join(ROOT, "exports")


DEFAULT_EXPORT_DIR = _export_root()

# 这些名字必须和 LightingState.merge() 认的一致（key_azimuth / fill_intensity …），
# 以前写的是 azimuth/fill 这种短名，结果全落进 merge 的 unknown 里 —— 滑杆怎么拉
# 渲染器都不动，就是「灯光调整失效」的根因。
DEFAULT_LIGHTING = {
    "key_azimuth": 42.0,
    "key_elevation": 38.0,
    "key_intensity": 1.35,
    "key_color": (1.0, 0.97, 0.92),
    "fill_intensity": 0.42,
    "rim_intensity": 0.55,
    "env_intensity": 0.18,
}


def _pak_dir() -> Optional[str]:
    try:
        from core.loader import PAK_DIR
        return PAK_DIR
    except Exception:                                       # noqa: BLE001
        return None


def _friendly_missing(exc: Exception) -> str:
    """把文件缺失翻译成「用户能照着做」的话，并带上版本与诊断信息。"""
    from core import loader as _ld
    from core.version import stamp
    if getattr(_ld, "INDEX_ERROR", ""):
        return _ld.INDEX_ERROR + f"\n\n版本：{stamp()}"
    name = os.path.basename(getattr(exc, "filename", "") or "")
    head = f"读不到 {name}。\n" if name else "读游戏文件时出错。\n"
    return (head + _ld.search_report() + "\n\n"
            f"版本：{stamp()}\n"
            "资产索引已经改成用户目录下的 VertexViewer/index.db（SQLite），"
            "正常不会缺文件：进「设置 → 数据维护」点「重建索引」即可。"
            "要换数据目录可以设环境变量 VERTEXVIEWER_WORK。")


class _LoadWorker(QThread):
    """Unpack -> cache -> parse, off the UI thread."""

    done = Signal(str, object, str)

    def __init__(self, cache, vpath: str, parent=None) -> None:
        super().__init__(parent)
        self.cache = cache
        self.vpath = vpath

    def run(self) -> None:                                  # noqa: D401
        try:
            self.cache.get(self.vpath)                      # warm cache + sidecars
        except KeyError:
            # 常见于「别人的游戏版本里这个资产已经改名/被移走」，或者索引是旧的。
            # 原来的样子是把 KeyError 的原文糊到状态栏上，看着像是我们把文件搞丢了。
            self.done.emit(self.vpath, None,
                           f"这个资产在当前游戏目录里读不到（{os.path.basename(self.vpath)}），"
                           "可能是游戏版本更新后改名/移除了，索引也需要重新生成。")
            return
        except FileNotFoundError as exc:
            self.done.emit(self.vpath, None, _friendly_missing(exc))
            return
        except Exception as exc:                            # noqa: BLE001
            self.done.emit(self.vpath, None,
                           f"cache: {type(exc).__name__}: {exc}")
            return
        try:
            from core.loader import load_model
            bundle = load_model(self.vpath, lod=0, want_textures=True, want_cn=True)
            self.done.emit(self.vpath, bundle, "")
        except Exception as exc:                            # noqa: BLE001
            self.done.emit(self.vpath, None,
                           f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")


class VertexViewerWindow(FluentWindow):
    bundleChanged = Signal(object)
    cacheChanged = Signal()

    def __init__(self, *, auto_build: bool = True, viewer: Optional[str] = None,
                 cache=None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("VertexViewerMainWindow")
        try:
            from core.version import stamp
            _ver = f"  ·  {stamp()}"
        except Exception:                                     # noqa: BLE001
            _ver = ""
        self.setWindowTitle("VertexViewer · 模型浏览器" + _ver)
        # 不同机器缩放差别很大（100% / 125% / 150%、4K）：一律收进屏幕可用区域
        from app import ui_scale as _ui
        _w, _h = _ui.fit(1500, 940)
        self.resize(_w, _h)
        self.setMinimumSize(*_ui.min_size(1080, 680))
        self.setAcceptDrops(True)

        self.cache = cache or get_cache()
        try:
            self.cache.cleanup_stale()
            self.cache.install_cleanup(QApplication.instance())
        except Exception:                                   # noqa: BLE001
            pass

        self.bundle = None
        self.current_vpath = ""
        self.last_export = None
        self.last_capture = ""
        self.game_dir = _pak_dir()
        self._metallic: Optional[float] = None
        self._roughness: Optional[float] = None
        self._exposure = 0.0
        self._lighting: Dict[str, Any] = dict(DEFAULT_LIGHTING)
        self._loader: Optional[_LoadWorker] = None
        self._requested_vpath = ""
        self._closing = False

        self.browser = ModelBrowser(self, auto_build=auto_build)
        self.viewport: Viewport = create_viewport(self, force=viewer)

        self.library_page = LibraryPage(self, self.viewport, self)
        self.library_page.status.set_cache(self._cache_size())
        self.textures_page = TexturesPage(self, self)
        self.materials_page = MaterialsPage(self, self)
        self.export_page = ExportPage(self, self)
        self.gunsmith_page = GunsmithPage(self, self)
        self.inspection_page = InspectionPage(self, self)
        self.settings_page = SettingsPage(self, self)
        from app.tutorial import TutorialPage
        self.tutorial_page = TutorialPage(self)
        self.inspector = self.library_page.inspector

        self.addSubInterface(self.library_page, icon("library"), "模型库")
        self.addSubInterface(self.textures_page, icon("photo"), "贴图")
        self.addSubInterface(self.materials_page, icon("brush"), "材质")
        self.addSubInterface(self.gunsmith_page, icon("play"), "改枪")
        self.addSubInterface(self.inspection_page, icon("play"), "检视动画")
        self.addSubInterface(self.export_page, icon("export"), "导出")
        self.addSubInterface(self.tutorial_page, icon("info"), "教程")
        self.addSubInterface(self.settings_page, icon("setting"), "设置")

        try:
            self.setMicaEffectEnabled(os.environ.get("VERTEXVIEWER_MICA", "") == "1")
        except Exception:                                   # noqa: BLE001
            pass

        # 标题栏/导航和内容区要用同一个底色，否则窗口顶部会有一条异色带
        try:
            self.set_background_colors(TITLEBAR_LIGHT, TITLEBAR_DARK)
        except Exception:                                   # noqa: BLE001
            pass
        # 用库自己的标题栏（和外壳同色），原生 caption 那条 DWM 上色在 Win11 26200 上盖不住
        try:
            self.set_title_bar_enabled(True)
        except Exception:                                   # noqa: BLE001
            pass
        self._tidy_title_bar()

        self.browser.modelActivated.connect(self.load_vpath)
        self.browser.statusMessage.connect(lambda text: self.status(text))
        self.bundleChanged.connect(
            lambda b: self.textures_page.set_bundle(b, self.current_vpath))
        self.bundleChanged.connect(self.materials_page.set_bundle)
        self.bundleChanged.connect(
            lambda b: self.export_page.set_bundle(b, self.current_vpath))
        self.bundleChanged.connect(self._on_bundle_changed)
        self.bundleChanged.connect(lambda b: self.inspection_page.set_bundle(b, self.current_vpath))
        self.inspection_page.availabilityChanged.connect(self._on_inspection_available)

        self._settings_refreshed = False
        self._cache_timer = QTimer(self)
        self._cache_timer.setInterval(2500)
        self._cache_timer.timeout.connect(self._tick_cache)
        self._cache_timer.start()

        self._install_shortcuts()
        self._setup_fluent_chrome()
        self.status(f"就绪 · 渲染器 {describe_backend(self.viewport)}")
        # 有加载界面时把「选游戏目录」推迟到窗口真正显示之后，
        # 否则对话框会盖在还没展开的小方框上。
        if not getattr(self, "_defer_game_dir", False):
            QTimer.singleShot(0, self.ensure_game_dir)

    # -- game folder ------------------------------------------------------- #
    def ensure_game_dir(self) -> None:
        """启动时检查游戏 Paks 目录；找不到就问一次并存到配置里。"""
        try:
            import core.loader as L
        except Exception:                                       # noqa: BLE001
            return
        if os.path.isdir(L.PAK_DIR):
            return
        start = L.find_game_root() or "C:\\"
        from PySide6.QtWidgets import QFileDialog
        chosen = QFileDialog.getExistingDirectory(
            self, "请选择游戏安装目录（含 Content\\Paks 的那一层）", start)
        if not chosen:
            self.status("没找到游戏目录：模型库会是空的，可以从菜单重新选")
            return
        paks = L.set_game_root(chosen)
        if os.path.isdir(paks):
            self.status(f"游戏目录已设置：{paks}")
            self.toast("游戏目录已保存", paks, ok=True)
        else:
            self.status(f"这个目录里没有 Content\\Paks：{chosen}")

    # -- chrome ------------------------------------------------------------ #
    def _setup_fluent_chrome(self) -> None:
        """Mica is a desktop composite: with it on, FluentWindow paints a fully
        transparent background. There is no backdrop offscreen (and none on
        Win10), which left dark-theme white text on a white window, so it is
        only enabled on a real Win11 desktop."""
        offscreen = os.environ.get("QT_QPA_PLATFORM", "").lower() in ("offscreen", "minimal")
        win11 = False
        if sys.platform == "win32":
            try:
                win11 = sys.getwindowsversion().build >= 22000
            except Exception:                               # noqa: BLE001
                win11 = False
        # Mica 默认关掉：它是 DWM 的桌面合成背板，鼠标一动就整块重新合成，
        # 全屏下看起来就是闪屏。想要透明磨砂效果可以设 VERTEXVIEWER_MICA=1。
        mica = bool(win11 and not offscreen
                    and os.environ.get("VERTEXVIEWER_MICA", "") == "1")
        self._mica_ok = mica                 # 全屏时要临时关掉，退出再按这个恢复
        try:
            self.setMicaEffectEnabled(mica)
        except Exception:                                   # noqa: BLE001
            pass
        if not mica:
            try:
                self.setBackgroundColor(QColor(32, 32, 32) if isDarkTheme()
                                        else QColor(243, 246, 250))
            except Exception:                               # noqa: BLE001
                pass
        try:
            panel = self.navigationInterface.panel
            panel.setExpandWidth(232)
            panel.expand(False)
            self.navigationInterface.setMinimumWidth(232)
        except Exception:                                   # noqa: BLE001
            pass

    # -- lifecycle --------------------------------------------------------- #
    def _install_shortcuts(self) -> None:
        bindings = (
            ("Ctrl+O", self.open_game_dir),
            ("Ctrl+E", self.export_current),
            ("F5", self.capture_view),
            ("F11", self.toggle_fullscreen),
            ("Ctrl+R", lambda: self.viewport.reset_camera()),
            ("Ctrl+F", lambda: self.browser.search.setFocus()),
        )
        self._shortcuts = []
        for keys, slot in bindings:
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(slot)
            self._shortcuts.append(shortcut)

    def showEvent(self, event) -> None:                     # noqa: N802
        super().showEvent(event)
        self._tidy_title_bar()
        # 原生标题栏是系统画在我们窗口上面的，Qt 样式表管不到它，
        # 只能等窗口真正有了 HWND 再用 DWM 上色，才能和主体同色。
        self._blend_window_chrome()

    def _tidy_title_bar(self) -> None:
        """标题栏只留标题和窗口按钮：前进/后退对本程序没意义。"""
        bar = getattr(self, "_title_bar", None)
        if bar is None:
            return
        for name in ("_back_button", "_forward_button", "back_button", "forward_button"):
            btn = getattr(bar, name, None)
            if btn is not None:
                try:
                    btn.setVisible(False)
                except Exception:                           # noqa: BLE001
                    pass
        # 标题文字放大一点（库默认用主题字号，标题在 1500 宽的窗口里显得很小）
        try:
            from PySide6.QtGui import QFont
            from fluentpy.widgets.title_bar import _WindowTitle
            label = bar.findChild(_WindowTitle)
            if label is not None:
                f = QFont(label.font())
                f.setPixelSize(max(14, int(f.pixelSize() * 1.32)) if f.pixelSize() > 0 else 14)
                f.setWeight(QFont.Weight.DemiBold)
                label.setFont(f)
        except Exception:                                   # noqa: BLE001
            pass

    def _blend_window_chrome(self) -> None:
        try:
            color = TITLEBAR_DARK if isDarkTheme() else TITLEBAR_LIGHT
        except Exception:                                   # noqa: BLE001
            color = TITLEBAR_DARK
        try:
            blend_caption(int(self.winId()), color)
        except Exception:                                   # noqa: BLE001
            pass

    def closeEvent(self, event) -> None:                    # noqa: N802
        self._closing = True
        self.browser.shutdown()
        self.inspection_page.shutdown()
        self.gunsmith_page.shutdown()
        if self._loader is not None:
            self._loader.wait()
        try:
            self.cache.purge()
        except Exception:                                   # noqa: BLE001
            pass
        super().closeEvent(event)

    # -- status / info ----------------------------------------------------- #
    def status(self, text: str, progress: Optional[float] = None) -> None:
        try:
            self.library_page.status.set_asset(text)
            self.library_page.status.set_progress(progress)
        except Exception:                                   # noqa: BLE001
            pass

    def toast(self, title: str, content: str = "", ok: bool = True) -> None:
        try:
            factory = InfoBar.success if ok else InfoBar.error
            factory(title=title, content=content, orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP_RIGHT, duration=3200, parent=self)
        except Exception:                                   # noqa: BLE001
            pass

    def _cache_size(self) -> int:
        try:
            return self.cache.size_bytes()
        except Exception:                                   # noqa: BLE001
            return 0

    def _tick_cache(self) -> None:
        self.library_page.status.set_cache(self._cache_size())
        # The settings card shows the asset count, so refresh it once the
        # background index thread has produced results.
        if self.browser.is_ready and not self._settings_refreshed:
            self._settings_refreshed = True
            self.settings_page.refresh()
            self.library_page.refresh_backend()
            # 索引好了就先打开第一个模型：不然启动后视口是一片空的灰，
            # 用户会以为软件没跑起来。
            if self.bundle is None:
                QTimer.singleShot(200, self.browser.select_first_model)
            # 索引没读出来（别人电脑最常见的坑）：给一个「立即重建」的入口
            QTimer.singleShot(500, self._maybe_offer_rebuild)
            # 首次启动：自动打开「教程」并放一遍进场动画，然后记下来
            QTimer.singleShot(260, self._maybe_first_run_tutorial)
            # 截图/演示用：VERTEXVIEWER_START_PAGE=tutorial|settings|gunsmith 启动直接停在那一页
            page = (os.environ.get("VERTEXVIEWER_START_PAGE") or "").strip().lower()
            if page:
                target = {"tutorial": getattr(self, "tutorial_page", None),
                          "settings": getattr(self, "settings_page", None),
                          "gunsmith": getattr(self, "gunsmith_page", None)}.get(page)
                if target is not None:
                    # 索引没读完之前切页面会被后续刷新顶回模型库，所以轮询到就绪再切
                    self._start_page = target
                    QTimer.singleShot(300, lambda: self.switchTo(target))
                    timer = QTimer(self)
                    timer.setInterval(600)
                    timer.timeout.connect(self._maybe_switch_start_page)
                    timer.start()
                    self._start_page_timer = timer

    def _maybe_switch_start_page(self) -> None:
        target = getattr(self, "_start_page", None)
        timer = getattr(self, "_start_page_timer", None)
        if target is None or timer is None:
            return
        if not getattr(self.browser, "is_ready", False):
            return
        timer.stop()
        try:
            self.switchTo(target)
        except Exception:                                   # noqa: BLE001
            pass

    def _maybe_first_run_tutorial(self) -> None:
        """第一次用这个软件：直接停在教程页并放动画；以后不再自动播。"""
        import core.loader as L
        force = os.environ.get("VERTEXVIEWER_FORCE_TUTORIAL") not in (None, "", "0")
        try:
            cfg = L._read_config()
        except Exception:                                   # noqa: BLE001
            cfg = {}
        if cfg.get("tutorial_seen") and not force:
            return
        page = getattr(self, "tutorial_page", None)
        if page is None:
            return
        try:
            self.switchTo(page)
            page.play_intro()
        except Exception:                                   # noqa: BLE001
            return
        try:
            cfg["tutorial_seen"] = True
            L._write_config(cfg)
        except Exception:                                   # noqa: BLE001
            pass

    def _maybe_offer_rebuild(self) -> None:
        if getattr(self, "_offered_rebuild", False):
            return
        self._offered_rebuild = True
        try:
            import core.loader as L
            error = getattr(L, "INDEX_ERROR", "") or ""
        except Exception:                                   # noqa: BLE001
            return
        if not error or getattr(self.browser, "count", 0):
            return
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(self)
        box.setWindowTitle("找不到资产索引")
        box.setIcon(QMessageBox.Warning)
        box.setText("软件没找到资产索引。")
        box.setInformativeText(
            (error.strip().splitlines()[0] if error.strip() else "") +
            "\n\n可以直接扫描游戏目录里的 pak 重建，大约 40 秒。")
        go = box.addButton("立即重建", QMessageBox.AcceptRole)
        box.addButton("稍后", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is go:
            try:
                self.switchTo(self.settings_page)
                self.settings_page._rebuild_index()
            except Exception as exc:                        # noqa: BLE001
                self.status(f"重建启动失败：{exc}")

    # -- asset loading ----------------------------------------------------- #
    def load_vpath(self, vpath: str) -> None:
        if not vpath or self._closing:
            return
        self._requested_vpath = vpath
        self.inspection_page.begin_selection(vpath)
        self.inspector.set_inspection_count(0, loading=True)
        self.status(f"解包 {os.path.basename(vpath)} …", progress=-1)
        if self._loader is None:
            self._start_model_load(vpath)

    def _start_model_load(self, vpath):
        worker = _LoadWorker(self.cache, vpath, self)
        self._loader = worker
        worker.done.connect(self._on_loaded)
        worker.finished.connect(lambda: self._model_load_finished(worker))
        worker.start()

    def _model_load_finished(self, worker):
        if self._loader is worker:
            self._loader = None
        worker.deleteLater()
        if not self._closing and self._requested_vpath and self._requested_vpath != worker.vpath:
            self._start_model_load(self._requested_vpath)

    def _on_loaded(self, vpath: str, bundle, error: str) -> None:
        if self._closing or (self._requested_vpath and vpath != self._requested_vpath):
            return
        self.library_page.status.set_progress(None)
        self._tick_cache()
        if error or bundle is None:
            self.inspection_page.selection_error(vpath, error or "未知错误")
            self.inspector.set_inspection_count(0)
            self.status(f"加载失败：{os.path.basename(vpath)}")
            self.toast("加载失败", error.splitlines()[0] if error else "未知错误", ok=False)
            print(f"[vertexviewer] load failed {vpath}: {error}", flush=True)
            return
        self.bundle = bundle
        self.current_vpath = vpath
        self._apply_material_slot_from_table(bundle, vpath)
        mesh = getattr(bundle, "mesh", None)
        if mesh is None or not getattr(mesh, "lods", None):
            self.inspection_page.selection_error(vpath, "该资产没有可用网格")
            self.inspector.set_inspection_count(0)
            self.status(f"该资产没有可用网格：{os.path.basename(vpath)}")
            self.toast("没有网格", "core.loader 没有解析出 LOD", ok=False)
            print(f"[vertexviewer] no mesh for {vpath}", flush=True)
            return
        triangles = mesh.lods[0].triangle_count if mesh.lods else 0
        try:
            self.viewport.set_mesh(mesh, bundle.materials, bundle.textures)
            self.viewport.frame_all()
        except Exception as exc:                            # noqa: BLE001
            self.toast("渲染器拒绝该网格", str(exc), ok=False)
        self.inspector.set_lod_list(len(mesh.lods))
        self.inspector.set_uv_list(mesh.lods[0].uv_channel_count)
        self.inspector.set_material_list([getattr(m, "name", "") or "材质"
                                          for m in (bundle.materials or [])],
                                         self._material_slot(bundle, vpath))
        # 3P 缺贴图时自动借了 UI/LAY 那套材质，状态栏说一声，免得以为是渲染坏了
        note = getattr(self.bundle, "material_note", "") if self.bundle else ""
        if note:
            self.status(note)
        self.bundleChanged.emit(bundle)
        self.inspector.set_inspection_count(len(self.inspection_page._rows))
        label = bundle.display_name_cn or bundle.display_name or os.path.basename(vpath)
        self.status(f"{label} · {vpath}")
        try:
            from core import icons as _icons

            self.library_page.status.set_icon(
                getattr(bundle, "icon_path", "") or _icons.icon_for(vpath))
        except Exception:                                   # noqa: BLE001
            pass
        self.library_page.status.set_triangles(triangles)

    def _on_inspection_available(self,vpath,count):
        if vpath==self.current_vpath: self.inspector.set_inspection_count(count)
        if count==0: self.browser.reject_inspection(vpath)

    def _on_bundle_changed(self, bundle) -> None:
        mesh = getattr(bundle, "mesh", None)
        triangles = mesh.lods[0].triangle_count if (mesh and mesh.lods) else 0
        self.library_page.status.set_triangles(triangles)

    # -- viewer control (called by the inspector) -------------------------- #
    def apply_material_override(self, metallic: Optional[float] = None,
                                roughness: Optional[float] = None) -> None:
        if metallic is not None:
            self._metallic = float(metallic)
        if roughness is not None:
            self._roughness = float(roughness)
        try:
            self.viewport.set_material_override(metallic=self._metallic,
                                                roughness=self._roughness)
        except Exception as exc:                            # noqa: BLE001
            self.status(f"材质覆盖失败：{exc}")
        self.status(f"metallic={self._metallic} roughness={self._roughness}")

    def apply_lighting(self, **params) -> None:
        self._lighting.update(params)
        try:
            self.viewport.set_lighting(**self._lighting)
        except Exception as exc:                            # noqa: BLE001
            self.status(f"灯光更新失败：{exc}")

    def toggle_inspect(self) -> None:
        """Open the real animation page already bound to this selected model."""
        if self.bundle is None or not self.inspection_page._rows:
            self.status("当前模型未找到对应的检视动画")
            return
        self.switchTo(self.inspection_page)

    def apply_material_index(self, index: int) -> None:
        """材质页：整个网格统一用第 index 个材质（1P 多材质的兜底手段）。"""
        try:
            self.viewport.set_single_material(int(index))
        except Exception as exc:                            # noqa: BLE001
            self.status(f"切换材质失败：{exc}")
            return
        self.status(f"整套网格改用材质 #{index}")

    def apply_style(self, name: str) -> None:
        try:
            self.viewport.set_style(name)
        except Exception as exc:                            # noqa: BLE001
            self.toast("风格不可用", str(exc), ok=False)
            return
        self.status(f"渲染风格：{name}")

    def apply_exposure(self, ev: float) -> None:
        self._exposure = float(ev)
        try:
            self.viewport.set_exposure(self._exposure)
        except Exception as exc:                            # noqa: BLE001
            self.status(f"曝光设置失败：{exc}")

    def apply_background(self, kind: str) -> None:
        try:
            self.viewport.set_background(kind)
        except Exception as exc:                            # noqa: BLE001
            self.toast("背景不可用", str(exc), ok=False)
            return
        self.status(f"背景：{kind}")

    def _apply_material_slot_from_table(self, bundle, vpath: str) -> None:
        """把用户存过的材质槽套到 bundle 上（选中那格转到第 0 位，渲染器只吃第 0 位）。"""
        self._materials_original = list(getattr(bundle, "materials", None) or [])
        self._rotate_materials(bundle, self._material_slot(bundle, vpath))

    def _material_slot(self, bundle, vpath: str) -> int:
        try:
            from core import usertable
            idx = usertable.slot_for(vpath)
        except Exception:                                    # noqa: BLE001
            idx = None
        mats = getattr(bundle, "materials", None) or []
        if idx is None or not 0 <= int(idx) < len(mats):
            return 0
        return int(idx)

    def _rotate_materials(self, bundle, index: int) -> None:
        mats = list(getattr(self, "_materials_original", None) or
                    getattr(bundle, "materials", None) or [])
        if not mats:
            return
        index = max(0, min(int(index), len(mats) - 1))
        bundle.materials = [mats[index]] + [m for i, m in enumerate(mats) if i != index]

    def apply_material_slot(self, index: int) -> None:
        """检查器里换材质槽：立即重渲染，并按资产记住选择。"""
        bundle = self.bundle
        vpath = self.current_vpath
        if bundle is None or not vpath:
            return
        self._rotate_materials(bundle, index)
        try:
            self.viewport.set_mesh(bundle.mesh, bundle.materials, bundle.textures)
        except Exception as exc:                             # noqa: BLE001
            self.toast("切换材质失败", str(exc), ok=False)
            return
        try:
            from core import usertable
            usertable.set_slot(vpath, int(index))
        except Exception:                                    # noqa: BLE001
            pass
        mat = (bundle.materials or [None])[0]
        name = getattr(mat, "name", "") if mat is not None else ""
        self.status(f"材质槽 {index + 1}/{len(self._materials_original or [])}：{name}（已记住）")

    def apply_lod(self, index: int) -> None:
        if not self.bundle:
            return
        try:
            self.viewport.set_lod(index)
        except Exception as exc:                            # noqa: BLE001
            self.status(f"LOD 切换失败：{exc}")
            return
        lods = self.bundle.mesh.lods
        if 0 <= index < len(lods):
            self.library_page.status.set_triangles(lods[index].triangle_count)
            self.status(f"LOD {index} · {lods[index].triangle_count:,} 三角形")

    def apply_uv_channel(self, index: int) -> None:
        """切换 UV 通道（同一套贴图用不同 UV 采样，位置会完全不一样）。"""
        try:
            self.viewport.set_uv_channel(int(index))
        except Exception as exc:                            # noqa: BLE001
            self.status(f"UV 通道切换失败：{exc}")
            return
        self.status(f"UV 通道：UV{int(index)}")

    def apply_show_untextured(self, on: bool) -> None:
        try:
            self.viewport.set_show_untextured(bool(on))
        except Exception as exc:                            # noqa: BLE001
            self.status(f"切换无贴图部件失败：{exc}")

    def apply_wireframe(self, on: bool) -> None:
        try:
            self.viewport.set_wireframe(bool(on))
        except Exception as exc:                            # noqa: BLE001
            self.status(f"线框切换失败：{exc}")

    # -- menu actions ------------------------------------------------------ #
    def open_game_dir(self) -> None:
        return _open_game_dir(self)

    def toggle_fullscreen(self) -> None:
        """全屏前后要摘掉 Mica。

        Mica 是 DWM 的桌面合成背板：全屏时窗口铺满整屏，鼠标移动引起的 hover
        重绘会让 DWM 重新合成一次，肉眼就是「闪」。改成全屏期间用纯色背景，
        退出全屏再按 `_mica_ok` 恢复。
        """
        try:
            if self.isFullScreen():
                self.showNormal()
                self._apply_mica(getattr(self, "_mica_ok", False))
            else:
                self._apply_mica(False)
                self.showFullScreen()
        except Exception as exc:                            # noqa: BLE001
            self.status(f"全屏失败：{exc}")

    def _apply_mica(self, on: bool) -> None:
        try:
            self.setMicaEffectEnabled(bool(on))
        except Exception:                                   # noqa: BLE001
            return
        if on:
            return
        # 关掉 Mica 之后背景会变全透明白，补一层实色底
        try:
            self.setBackgroundColor(QColor(32, 32, 32) if isDarkTheme()
                                    else QColor(243, 246, 250))
        except Exception:                                   # noqa: BLE001
            pass

    def capture_view(self) -> str:
        os.makedirs(CAPTURE_DIR, exist_ok=True)
        path = os.path.join(CAPTURE_DIR,
                            f"vertexviewer_{time.strftime('%Y%m%d_%H%M%S')}.png")
        ok = False
        try:
            ok = bool(self.viewport.capture(path))
        except Exception as exc:                            # noqa: BLE001
            self.toast("抓图失败", str(exc), ok=False)
        if ok:
            self.last_capture = path
            self.toast("已保存抓图", path)
            self.status(f"抓图：{path}")
        else:
            self.toast("抓图失败", "渲染器没有写出文件", ok=False)
        return path

    def export_obj(self, *, lod: Optional[int] = None,
                   directory: Optional[str] = None, scale: float = 1.0,
                   mtl: bool = True, axis: str = "gl",
                   merge_sections: bool = False, flip_uv: bool = True):
        bundle = self.bundle
        if bundle is None:
            raise RuntimeError("没有加载模型")
        target_dir = directory or DEFAULT_EXPORT_DIR
        os.makedirs(target_dir, exist_ok=True)
        stem = _asset_stem(bundle, self.current_vpath)
        base = os.path.join(target_dir, stem + ".obj")
        kwargs = dict(scale=scale, mtl=mtl, axis=axis,
                      merge_sections=merge_sections, flip_uv=flip_uv)
        if lod is None:
            result = export_obj_lods(bundle, base, **kwargs)
        else:
            result = export_obj(bundle, base, lod=lod, **kwargs)
        self.last_export = result
        return result

    def export_glb(self, *, directory: Optional[str] = None):
        """导出带骨骼的 GLB：几何、材质、蒙皮权重一起写进一个文件。"""
        bundle = self.bundle
        if bundle is None:
            self.toast("没有可导出的模型", "先在模型库里选一个资产", ok=False)
            return None
        if not skeleton_available(bundle.mesh):
            self.toast("这个模型没有骨骼", "纯静态网格请用「导出 OBJ」", ok=False)
            return None
        target_dir = directory or DEFAULT_EXPORT_DIR
        os.makedirs(target_dir, exist_ok=True)
        stem = _asset_stem(bundle, self.current_vpath)
        try:
            info = export_static_glb(bundle, os.path.join(target_dir, stem + ".glb"))
        except Exception as exc:                            # noqa: BLE001
            self.toast("导出失败", str(exc), ok=False)
            self.status(f"导出失败：{exc}")
            return None
        self.last_export = info
        self.toast(f"已导出 GLB（{info['bones']} 根骨骼）", os.path.dirname(info["path"]))
        return info

    def export_current(self) -> None:
        if self.bundle is None:
            self.toast("没有可导出的模型", "先在模型库里选一个资产", ok=False)
            return
        try:
            info = self.export_obj(lod=None)
        except Exception as exc:                            # noqa: BLE001
            self.toast("导出失败", str(exc), ok=False)
            self.status(f"导出失败：{exc}")
            return
        items = info if isinstance(info, list) else [info]
        path = os.path.dirname(items[0].get("obj", ""))
        self.toast(f"已导出 {len(items)} 个 OBJ", path)
        self.status(f"导出完成 → {path}")

    # -- drag & drop -------------------------------------------------------- #
    def dragEnterEvent(self, event) -> None:                 # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:                  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:                      # noqa: N802
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and path.lower().endswith(".uasset"):
                vpath = self.vpath_for_file(path)
                if vpath:
                    self.load_vpath(vpath)
                else:
                    self.toast("不在资产索引里", path, ok=False)
                event.acceptProposedAction()
                return

    def vpath_for_file(self, path: str) -> Optional[str]:
        normalized = path.replace("\\", "/")
        marker = "/models/"
        low = normalized.lower()
        if marker in low:
            rel = normalized[low.index(marker) + len(marker):]
            rel_dir = os.path.dirname(rel)
            name = os.path.basename(rel)
            for candidate, vpath in self.browser._rel_to_path.items():
                if os.path.basename(candidate) == name and \
                        os.path.dirname(candidate).endswith(rel_dir):
                    return vpath
            for candidate, vpath in self.browser._rel_to_path.items():
                if os.path.basename(candidate) == name:
                    return vpath
        return None


def _open_game_dir(window: "VertexViewerWindow") -> None:
    directory = window.game_dir or _pak_dir()
    try:
        if directory and os.path.isdir(directory):
            os.startfile(directory)                         # noqa: S606 (desktop app)
            window.status(f"已打开游戏目录：{directory}")
            return
    except Exception:                                       # noqa: BLE001
        pass
    chosen = QFileDialog.getExistingDirectory(window, "选择游戏目录", directory or "")
    if chosen:
        window.game_dir = chosen
        window.status(f"游戏目录：{chosen}")


def _asset_stem(bundle, vpath: str) -> str:
    name = getattr(bundle, "display_name", "") or ""
    if not name:
        mesh = getattr(bundle, "mesh", None)
        name = getattr(mesh, "name", "") if mesh else ""
    if not name:
        name = os.path.splitext(os.path.basename(vpath or "asset"))[0]
    safe = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in name)
    return safe or "asset"
