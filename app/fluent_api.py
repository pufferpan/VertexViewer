"""FluentPy (XDDXMT) 组件层 —— 全项目只从这里取控件。

`app/*.py` 里所有控件都从这个模块导入，这样窗口代码不用直接依赖第三方库的
具体名字。这个模块现在只有两条路：

level 1  XDDXMT 的 FluentPy（PyPI 包名 `fluentpy-qt`，import 名 `fluentpy`）
         真正在用的就是它；`app/fluentpy_adapter.py` 负责把它的 API 抹平成
         项目想要的 `PushButton` / `CardWidget` / `InfoBar.success` 之类。
level 3  本文件底部手绘的 Fluent 仿制品。**只在**显式
         `VERTEXVIEWER_FLUENTPY=0` 且没装 fluentpy 时才会用到，正常运行永远不会走。

qfluentwidgets（`PySide6-Fluent-Widgets` / `QFluentWidgets`）已经整套删除，
不再有任何 import、回退或打包项。

`LEVEL`、`SOURCE`、`LEVEL_NAME` 会让界面与诊断报告显示当前用的是哪一条路。
"""
from __future__ import annotations

import os
import sys
import zipfile

# --------------------------------------------------------------------------- #
# Qt basics -- re-exported so `app/*.py` never imports PySide6 directly
# --------------------------------------------------------------------------- #
from PySide6.QtCore import (QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt,
                            QThread, QTimer, Signal)
from PySide6.QtGui import (QAction, QBrush, QColor, QFont, QFontDatabase, QIcon,
                           QImage, QKeySequence, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygon, QPolygonF,
                           QRadialGradient, QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox,
                               QColorDialog, QComboBox, QDialog,
                               QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QScrollArea,
                               QSizePolicy, QSlider, QSpinBox, QSplitter,
                               QStackedWidget, QStyle, QTableWidget,
                               QTableWidgetItem, QTextEdit, QToolButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

__all__ = []  # filled at the end


# --------------------------------------------------------------------------- #
# 组件来源：只认 XDDXMT 的 FluentPy
# --------------------------------------------------------------------------- #
_SRC, LEVEL, SOURCE = None, 3, "builtin-fallback"
_ADAPTER = None
_FP_ERROR = None

# 默认就要求 FluentPy；装不上直接报错，绝不悄悄换成别的控件库。
# `VERTEXVIEWER_FLUENTPY=0` 才允许用文件底部自绘的仿制品（离线救急用）。
_FORCE_FLUENTPY = (os.environ.get("VERTEXVIEWER_FLUENTPY", "1").strip().lower()
                   not in ("0", "false", "no", "off"))

try:
    from app import fluentpy_adapter as _ADAPTER          # noqa: E402
except Exception as _exc:                                 # noqa: BLE001
    _ADAPTER = None
    _FP_ERROR = _exc
else:
    _SRC, LEVEL = _ADAPTER, 1
    SOURCE = _ADAPTER.SOURCE

if _ADAPTER is None and _FORCE_FLUENTPY:
    raise RuntimeError(
        "界面必须使用 FluentPy（XDDXMT），但没装上 fluentpy。"
        " 安装：pip install -i https://pypi.org/simple fluentpy-qt 。"
        " 离线想用自绘界面：设置环境变量 VERTEXVIEWER_FLUENTPY=0 。"
        f" 原始错误：{_FP_ERROR!r}")

LEVEL_NAME = {1: "FluentPy (XDDXMT)", 3: "built-in fallback (self drawn)"}[LEVEL]


if _ADAPTER is not None:
    # ---- level 1: XDDXMT FluentPy via app/fluentpy_adapter.py ------------- #
    from app.fluentpy_adapter import (BodyLabel, CaptionLabel,  # noqa: F401
                                      CardWidget, ComboBox, FluentIcon,
                                      FluentWindow, FluentWidget,
                                      HeaderCardWidget, HorizontalSeparator,
                                      IconWidget, InfoBar, InfoBarPosition,
                                      LineEdit, PrimaryPushButton, ProgressBar,
                                      PushButton, ScrollArea, SearchLineEdit,
                                      SimpleCardWidget, Slider, SmoothScrollArea,
                                      StrongBodyLabel, SubtitleLabel,
                                      SwitchButton, Theme, TitleLabel,
                                      ToggleButton, ToolButton,
                                      isDarkTheme, setTheme, setThemeColor)
    NavigationInterface = NavigationPushButton = None      # FluentPy 没有这两个
    SpinBox = _ADAPTER.SpinBox
    DoubleSpinBox = _ADAPTER.DoubleSpinBox
    FlowLayout = None
    SegmentedWidget = None
    TABLE_WIDGET = QTableWidget
    LIST_WIDGET = QListWidget
    TREE_WIDGET = QTreeWidget

else:  # pragma: no cover - 只有 VERTEXVIEWER_FLUENTPY=0 且没装 fluentpy 才走到这里
    # ------------------------------------------------------------------ #
    # level 3: self drawn fallback                                        #
    # ------------------------------------------------------------------ #
    import enum

    ACCENT = "#0067C0"
    _DARK = {"bg": "#202020", "card": "#2b2b2b", "text": "#f0f0f0", "sub": "#c8c8c8",
             "sidebar": "rgba(38,38,38,0.86)", "border": "#3d3d3d", "hover": "#333333"}
    _LIGHT = {"bg": "#f5f5f5", "card": "#ffffff", "text": "#1b1b1b", "sub": "#5a5a5a",
              "sidebar": "rgba(244,244,244,0.86)", "border": "#e2e2e2", "hover": "#eaeaea"}
    _state = {"dark": True, "accent": ACCENT}

    class Theme(enum.Enum):
        LIGHT = "light"
        DARK = "dark"

    def isDarkTheme() -> bool:
        return _state["dark"]

    def _palette() -> dict:
        return _DARK if _state["dark"] else _LIGHT

    def _app() -> QApplication | None:
        return QApplication.instance()

    def setTheme(theme) -> None:                             # noqa: N802
        _state["dark"] = (theme == Theme.DARK if not isinstance(theme, str)
                          else str(theme).lower().endswith("dark"))
        app = _app()
        if app is not None:
            app.setStyleSheet(app.styleSheet())

    def setThemeColor(color: str, *args, **kwargs) -> None:    # noqa: N802
        _state["accent"] = color if isinstance(color, str) else ACCENT

    class InfoBarPosition(enum.Enum):
        TOP_LEFT = 0; TOP_RIGHT = 1; BOTTOM_LEFT = 2; BOTTOM_RIGHT = 3; TOP = 4

    class FluentIcon:
        """Level-3 icons: painted glyphs, same attribute names as the real enum."""
        _glyphs = {
            "LIBRARY": "▤", "PHOTO": "◪", "BRUSH": "✎", "SAVE": "⇩",
            "SETTING": "⚙", "FOLDER": "▣", "CAMERA": "◉", "FULL_SCREEN": "⛶",
            "SEARCH": "⌕", "DELETE": "✕", "SYNC": "↻", "INFO": "i",
            "PALETTE": "◐", "VIEW": "☰", "DOWNLOAD": "⇩", "APPLICATION": "◆",
            "IMAGE_EXPORT": "⇧", "ERASE_TOOL": "⌫", "TILES": "▦",
            "BOOK_SHELF": "▤", "PLAY": "▶", "DOCUMENT": "▤", "ZOOM": "⌕",
        }

    def _paint_icon(glyph: str, color: str = "#e8e8e8", size: int = 32) -> QIcon:
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        font = QFont("Segoe UI Symbol")
        font.setPixelSize(int(size * 0.78))
        p.setFont(font)
        p.setPen(QPen(QColor(color)))
        p.drawText(pm.rect(), Qt.AlignCenter, glyph)
        p.end()
        return QIcon(pm)

    for _name, _glyph in list(FluentIcon._glyphs.items()):
        setattr(FluentIcon, _name, _paint_icon(_glyph))

    class _Base:
        pass

    class FluentWidget(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setAttribute(Qt.WA_StyledBackground, True)

    class _Label(QLabel):
        size = 14
        weight = QFont.Normal

        def __init__(self, text: str = "", parent=None):
            super().__init__(text, parent)
            font = self.font()
            font.setPixelSize(self.size)
            font.setWeight(self.weight)
            font.setFamily("Segoe UI")
            self.setFont(font)

    class TitleLabel(_Label):
        size = 30
        weight = QFont.DemiBold

    class SubtitleLabel(_Label):
        size = 22
        weight = QFont.DemiBold

    class StrongBodyLabel(_Label):
        size = 15
        weight = QFont.DemiBold

    class BodyLabel(_Label):
        size = 14

    class CaptionLabel(_Label):
        size = 12

    _BTN_QSS = """
    QPushButton { border: 1px solid %(border)s; border-radius: 8px; padding: 6px 14px;
                  background: %(card)s; color: %(text)s; font-family: 'Segoe UI'; font-size: 14px; }
    QPushButton:hover { background: %(hover)s; }
    QPushButton:pressed { background: %(border)s; }
    QPushButton:disabled { color: %(sub)s; }
    """

    class PushButton(QPushButton):
        def __init__(self, text: str = "", parent=None):
            super().__init__(text, parent)
            self.setStyleSheet(_BTN_QSS % _palette())
            self.setCursor(Qt.PointingHandCursor)

    class PrimaryPushButton(PushButton):
        def __init__(self, text: str = "", parent=None):
            super().__init__(text, parent)
            self.setStyleSheet(
                "QPushButton { border: none; border-radius: 8px; padding: 7px 16px;"
                " background: %s; color: white; font-family: 'Segoe UI'; font-size: 14px;"
                " font-weight: 600; } QPushButton:hover { background: #1a78d4; }"
                % _state["accent"])

    class ToolButton(PushButton):
        def __init__(self, text: str = "", parent=None):
            super().__init__(text, parent)
            self.setFixedHeight(30)

    class ToggleButton(PushButton):
        def __init__(self, text: str = "", parent=None):
            super().__init__(text, parent)
            self.setCheckable(True)

    class Slider(QSlider):
        def __init__(self, orientation=Qt.Horizontal, parent=None):
            super().__init__(orientation, parent)
            self.setStyleSheet(
                "QSlider::groove:horizontal { height: 4px; border-radius: 2px; background: %(border)s; }"
                "QSlider::sub-page:horizontal { background: %(accent)s; border-radius: 2px; }"
                "QSlider::handle:horizontal { width: 14px; height: 14px; margin: -6px 0;"
                " border-radius: 7px; background: %(accent)s; }" % {
                    "border": _palette()["border"], "accent": _state["accent"]})

    class ComboBox(QComboBox):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setStyleSheet(
                "QComboBox { border: 1px solid %(border)s; border-radius: 8px; padding: 4px 10px;"
                " background: %(card)s; color: %(text)s; font-family: 'Segoe UI'; }"
                "QComboBox QAbstractItemView { background: %(card)s; color: %(text)s;"
                " selection-background-color: %(accent)s; }" % {
                    "border": _palette()["border"], "card": _palette()["card"],
                    "text": _palette()["text"], "accent": _state["accent"]})

    class SwitchButton(QCheckBox):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setStyleSheet("QCheckBox { color: %s; }" % _palette()["text"])

    class LineEdit(QLineEdit):
        def __init__(self, text: str = "", parent=None):
            super().__init__(text, parent)
            self.setStyleSheet(
                "QLineEdit { border: 1px solid %(border)s; border-radius: 8px; padding: 5px 10px;"
                " background: %(card)s; color: %(text)s; }" % _palette())

    class SearchLineEdit(LineEdit):
        pass

    class ScrollArea(QScrollArea):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWidgetResizable(True)
            self.setFrameShape(QFrame.NoFrame)

    class SmoothScrollArea(ScrollArea):
        pass

    class ProgressBar(QProgressBar):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setTextVisible(False)
            self.setFixedHeight(4)
            self.setStyleSheet(
                "QProgressBar { border: none; background: %s; border-radius: 2px; }"
                "QProgressBar::chunk { background: %s; border-radius: 2px; }"
                % (_palette()["border"], _state["accent"]))

    class CardWidget(QFrame):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setStyleSheet(
                "QFrame { background: %s; border: 1px solid %s; border-radius: 8px; }"
                % (_palette()["card"], _palette()["border"]))

    class SimpleCardWidget(CardWidget):
        pass

    class HeaderCardWidget(CardWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.vBoxLayout = QVBoxLayout(self)
            self.headerLabel = StrongBodyLabel("")
            self.vBoxLayout.addWidget(self.headerLabel)
            self.viewLayout = QVBoxLayout()
            self.vBoxLayout.addLayout(self.viewLayout)

        def setTitle(self, text: str) -> None:              # noqa: N802
            self.headerLabel.setText(text)

    class HorizontalSeparator(QFrame):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setFixedHeight(1)
            self.setStyleSheet("background: %s;" % _palette()["border"])

    class IconWidget(QWidget):
        def __init__(self, icon=None, parent=None, size: int = 18):
            super().__init__(parent)
            self._icon = icon
            self._size = size
            self.setFixedSize(size, size)

        def setIcon(self, icon) -> None:                    # noqa: N802
            self._icon = icon
            self.update()

        def paintEvent(self, event) -> None:                # noqa: N802
            p = QPainter(self)
            if isinstance(self._icon, QIcon):
                self._icon.paint(p, self.rect())
            p.end()

    class NavigationPushButton(QPushButton):
        def __init__(self, icon, text: str = "", parent=None):
            super().__init__(text, parent)
            self.setCheckable(True)
            if isinstance(icon, QIcon):
                self.setIcon(icon)
            self.setStyleSheet(
                "QPushButton { border: none; border-radius: 8px; text-align: left; padding: 8px 12px;"
                " color: %(text)s; background: transparent; font-family: 'Segoe UI'; font-size: 14px; }"
                "QPushButton:hover { background: %(hover)s; }"
                "QPushButton:checked { background: rgba(0,103,192,0.22); color: %(text)s;"
                " border-left: 3px solid %(accent)s; }" % {
                    "text": _palette()["text"], "hover": _palette()["hover"],
                    "accent": _state["accent"]})

    class NavigationInterface(QFrame):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setFixedWidth(200)
            self.setStyleSheet(
                "NavigationInterface { background: %s; border-right: 1px solid %s; }"
                % (_palette()["sidebar"], _palette()["border"]))
            self.vBoxLayout = QVBoxLayout(self)
            self.vBoxLayout.setContentsMargins(8, 12, 8, 12)
            self.vBoxLayout.setSpacing(4)
            self.vBoxLayout.addStretch(1)
            self._items: list[NavigationPushButton] = []

        def addItem(self, routeKey, icon, text, onClick=None, **kwargs):  # noqa: N802
            btn = NavigationPushButton(icon, text, self)
            btn.clicked.connect(lambda: (self._select(btn), onClick and onClick()))
            self.vBoxLayout.insertWidget(self.vBoxLayout.count() - 1, btn)
            self._items.append(btn)
            setattr(self, f"_route_{routeKey}", btn)
            return btn

        def _select(self, btn: NavigationPushButton) -> None:
            for item in self._items:
                item.setChecked(item is btn)

        def setCurrentItem(self, routeKey) -> None:          # noqa: N802
            btn = getattr(self, f"_route_{routeKey}", None)
            if btn is not None:
                btn.setChecked(True)

    class FluentWindow(QWidget):
        """Level-3 stand-in that mirrors the real `FluentWindow` surface."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("VertexViewer")
            self.setStyleSheet("FluentWindow { background: %s; }" % _palette()["bg"])
            self._root = QHBoxLayout(self)
            self._root.setContentsMargins(0, 0, 0, 0)
            self._root.setSpacing(0)
            self.navigationInterface = NavigationInterface(self)
            self.stackedWidget = QStackedWidget(self)
            self._root.addWidget(self.navigationInterface)
            self._root.addWidget(self.stackedWidget, 1)

        def addSubInterface(self, interface, icon, text,  # noqa: N802
                            position=None, parent=None, isTransparent: bool = False):
            self.stackedWidget.addWidget(interface)
            key = interface.objectName() or f"page{self.stackedWidget.count()}"
            self.navigationInterface.addItem(
                key, icon, text, lambda: self.switchTo(interface))
            if self.stackedWidget.count() == 1:
                self.switchTo(interface)
            return interface

        def switchTo(self, interface, **kwargs) -> None:      # noqa: N802
            self.stackedWidget.setCurrentWidget(interface)

        def setMicaEffectEnabled(self, enabled: bool) -> None:  # noqa: N802
            pass

        def setWindowIcon(self, icon) -> None:                 # noqa: N802
            super().setWindowIcon(icon)

    class FluentWidget(QWidget):                                # noqa: F811
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setStyleSheet("background: %s;" % _palette()["bg"])

    class InfoBar(QFrame):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setVisible(False)

        @staticmethod
        def _show(title: str, content: str, duration: int = 3000) -> None:
            win = QApplication.activeWindow()
            if win is not None:
                box = QMessageBox(QMessageBox.Information, title or "VertexViewer", content, parent=win)
                QTimer.singleShot(max(800, int(duration)), box.accept)
                box.show()

        @staticmethod
        def success(title, content, parent=None, duration=3000, **kw):
            InfoBar._show(title, content, duration)

        @staticmethod
        def error(title, content, parent=None, duration=3000, **kw):
            InfoBar._show(title, content, duration)

        @staticmethod
        def warning(title, content, parent=None, duration=3000, **kw):
            InfoBar._show(title, content, duration)

        @staticmethod
        def information(title, content, parent=None, duration=3000, **kw):
            InfoBar._show(title, content, duration)

    NavigationInterface = NavigationInterface                           # noqa: F811
    TABLE_WIDGET = QTableWidget
    LIST_WIDGET = QListWidget
    TREE_WIDGET = QTreeWidget
    SpinBox = None
    DoubleSpinBox = None
    FlowLayout = None
    SegmentedWidget = None


# --------------------------------------------------------------------------- #
# icon + theme helpers shared by both code paths
# --------------------------------------------------------------------------- #
_ALIASES = {
    "library": ("LIBRARY", "BOOK_SHELF", "DOCUMENT", "FOLDER"),
    "photo": ("PHOTO", "TILES", "VIEW", "PALETTE"),
    "brush": ("BRUSH", "PALETTE", "EDIT"),
    "save": ("SAVE", "DOWNLOAD", "IMAGE_EXPORT"),
    "setting": ("SETTING", "DEVELOPER_TOOLS", "IOT"),
    "folder": ("FOLDER", "LIBRARY", "ZIP_FOLDER"),
    "camera": ("CAMERA", "PHOTO"),
    "fullscreen": ("FULL_SCREEN", "VIEW"),
    "search": ("SEARCH", "ZOOM"),
    "delete": ("DELETE", "ERASE_TOOL"),
    "sync": ("SYNC", "UPDATE", "HISTORY"),
    "info": ("INFO", "HELP"),
    "palette": ("PALETTE", "BRUSH"),
    "view": ("VIEW", "TILES"),
    "export": ("IMAGE_EXPORT", "SAVE", "DOWNLOAD"),
    "open": ("FOLDER", "DOCUMENT"),
    "app": ("APPLICATION", "HOME"),
}


def icon(name: str):
    """A `FluentIcon` member (levels 1/2) or a `QIcon` (level 3)."""
    if _ADAPTER is not None:
        return _ADAPTER.icon(name)
    key = (name or "").strip().lower()
    for cand in _ALIASES.get(key, (key.upper(),)):
        try:
            return getattr(FluentIcon, cand)
        except Exception:                                   # noqa: BLE001
            continue
    try:
        return getattr(FluentIcon, "APPLICATION")
    except Exception:                                       # noqa: BLE001
        return QIcon()


def qicon(name: str) -> QIcon:
    """A plain `QIcon` for tree/list rows (FluentIconBase -> QIcon)."""
    if _ADAPTER is not None:
        return _ADAPTER.qicon(name)
    obj = icon(name)
    if isinstance(obj, QIcon):
        return obj
    try:
        return obj.icon()
    except Exception:                                       # noqa: BLE001
        return QIcon()


def apply_fluent_theme(dark: bool = True, color: str = "#0067C0") -> None:
    """Theme + accent colour, wrapped so every level accepts it."""
    try:
        setTheme(Theme.DARK if dark else Theme.LIGHT)
    except Exception:                                       # noqa: BLE001
        pass
    try:
        setThemeColor(color)
    except Exception:                                       # noqa: BLE001
        pass
    if LEVEL == 3:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(app.styleSheet())


def apply_dark_palette(app=None, dark: bool = True) -> None:
    """Dark QPalette for the stock Qt widgets that FluentPy does not restyle
    (QTreeWidget / QListWidget / QTableWidget / QScrollArea / plain QWidget)."""
    app = app or QApplication.instance()
    if app is None:
        return
    try:
        app.setStyle("Fusion")
    except Exception:                                       # noqa: BLE001
        pass
    from PySide6.QtGui import QColor as _QColor, QPalette as _QPalette

    if dark:
        window = _QColor(32, 32, 32)
        base = _QColor(38, 38, 38)
        text = _QColor(236, 236, 236)
        button = _QColor(45, 45, 45)
        disabled = _QColor(120, 120, 120)
    else:
        window = _QColor(243, 246, 250)
        base = _QColor(255, 255, 255)
        text = _QColor(26, 26, 26)
        button = _QColor(250, 250, 250)
        disabled = _QColor(150, 150, 150)

    palette = _QPalette()
    palette.setColor(_QPalette.Window, window)
    palette.setColor(_QPalette.WindowText, text)
    palette.setColor(_QPalette.Base, base)
    palette.setColor(_QPalette.AlternateBase, _QColor(45, 45, 45) if dark else _QColor(245, 247, 250))
    palette.setColor(_QPalette.ToolTipBase, base)
    palette.setColor(_QPalette.ToolTipText, text)
    palette.setColor(_QPalette.Text, text)
    palette.setColor(_QPalette.Button, button)
    palette.setColor(_QPalette.ButtonText, text)
    palette.setColor(_QPalette.BrightText, _QColor(255, 90, 90))
    palette.setColor(_QPalette.Link, _QColor(0, 103, 192))
    palette.setColor(_QPalette.Highlight, _QColor(0, 103, 192))
    palette.setColor(_QPalette.HighlightedText, _QColor(255, 255, 255))
    palette.setColor(_QPalette.Disabled, _QPalette.Text, disabled)
    palette.setColor(_QPalette.Disabled, _QPalette.ButtonText, disabled)
    palette.setColor(_QPalette.Disabled, _QPalette.WindowText, disabled)
    palette.setColor(_QPalette.PlaceholderText, _QColor(150, 150, 150))
    app.setPalette(palette)


def describe() -> dict:
    return {
        "level": LEVEL,
        "level_name": LEVEL_NAME,
        "source": SOURCE,
        "window_class": getattr(FluentWindow, "__name__", "FluentWindow"),
    }


__all__ = [
    # Qt re-exports
    "Qt", "Signal", "QTimer", "QSize", "QRect", "QRectF", "QPoint", "QPointF", "QEvent",
    "QThread",
    "QColor", "QFont", "QFontDatabase", "QIcon", "QImage", "QPixmap", "QPainter",
    "QKeySequence", "QShortcut",
    "QPainterPath", "QPen", "QBrush", "QLinearGradient", "QRadialGradient", "QAction",
    "QPolygon", "QPolygonF",
    "QWidget", "QApplication", "QMainWindow", "QFrame", "QLabel", "QPushButton",
    "QToolButton", "QCheckBox", "QComboBox", "QLineEdit", "QSlider", "QProgressBar",
    "QScrollArea", "QSplitter", "QStackedWidget", "QStyle", "QSizePolicy",
    "QAbstractItemView", "QDialog", "QFileDialog", "QMessageBox", "QListWidget",
    "QListWidgetItem", "QTreeWidget", "QTreeWidgetItem", "QTableWidget",
    "QTableWidgetItem", "QHeaderView", "QVBoxLayout", "QHBoxLayout", "QGridLayout",
    "QSpinBox", "QDoubleSpinBox", "QColorDialog", "QPlainTextEdit", "QTextEdit",
    "QGroupBox",
    # fluent components
    "FluentWindow", "FluentWidget", "SubtitleLabel", "TitleLabel", "StrongBodyLabel",
    "BodyLabel", "CaptionLabel", "PushButton", "PrimaryPushButton", "ToolButton",
    "ToggleButton", "Slider", "ComboBox", "SwitchButton", "LineEdit", "SearchLineEdit",
    "ScrollArea", "SmoothScrollArea", "ProgressBar", "InfoBar", "InfoBarPosition",
    "FluentIcon", "IconWidget", "CardWidget", "SimpleCardWidget", "HeaderCardWidget",
    "HorizontalSeparator", "NavigationInterface", "NavigationPushButton",
    "Theme", "setTheme", "setThemeColor", "isDarkTheme", "apply_dark_palette",
    "SpinBox", "DoubleSpinBox", "FlowLayout", "SegmentedWidget",
    "TABLE_WIDGET", "LIST_WIDGET", "TREE_WIDGET",
    # shim metadata + helpers
    "LEVEL", "LEVEL_NAME", "SOURCE", "icon", "qicon", "apply_fluent_theme", "describe",
]
