"""FluentPy (fluentpy-qt, XDDXMT) compat layer.

The window code in `app/` was written against a Fluent-style widget set / FluentPy
API family, but FluentPy 0.7.x renamed and trimmed a lot of it (no
`PushButton`, no `BodyLabel`, no `TitleLabel`, a much smaller `FluentIcon`
enum, `InfoBar(title, detail, tone=...)` instead of `.success(...)`).

This module adapts FluentPy *up* to the names the rest of `app/` expects, so
the whole UI really runs on XDDXMT's FluentPy instead of the old wheel
wheel:

* labels      -> QLabel with the same font sizes the old widgets used
* buttons     -> FluentPy FilledButton / AccentButton (+ `setIcon`, the shim
                 passes a QIcon as the first argument)
* SwitchButton-> FluentPy ToggleSwitch (adds `checkedChanged` alias)
* InfoBar     -> thin wrapper that turns `.success(...)`-style calls into
                 FluentPy's constructor
* ScrollArea / HorizontalSeparator / IconWidget -> small Qt classes, FluentPy
                 does not ship them
* FluentIcon  -> proxies FluentPy members, `.icon()` yields a QIcon
"""
from __future__ import annotations

import enum

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QScrollArea,
                               QSizePolicy, QWidget)

import fluentpy as _fp
from fluentpy import FluentIcon as _FluentIconEnum
from fluentpy import ThemeMode as _ThemeMode
from fluentpy import theme as _theme
from fluentpy import widgets as _w
from fluentpy.icons import fluent_icon as _fluent_icon

__all__ = [
    "LEVEL", "SOURCE", "LEVEL_NAME", "describe", "icon", "qicon",
    "Theme", "setTheme", "setThemeColor", "isDarkTheme",
    "FluentIcon", "FluentWindow", "FluentWidget",
    "BodyLabel", "CaptionLabel", "TitleLabel", "SubtitleLabel", "StrongBodyLabel",
    "PushButton", "PrimaryPushButton", "ToolButton", "TransparentToolButton",
    "SwitchButton", "ToggleButton", "Slider", "ComboBox", "LineEdit",
    "SearchLineEdit", "ProgressBar", "SpinBox", "DoubleSpinBox",
    "CardWidget", "SimpleCardWidget", "HeaderCardWidget",
    "ScrollArea", "SmoothScrollArea", "HorizontalSeparator", "IconWidget",
    "InfoBar", "InfoBarPosition", "apply_fluent_theme",
]

VERSION = getattr(_fp, "__version__", "?")
LEVEL = 1
SOURCE = f"fluentpy-qt {VERSION} (XDDXMT FluentPy)"
LEVEL_NAME = "FluentPy (XDDXMT)"


def describe() -> dict:
    return {"level": LEVEL, "level_name": LEVEL_NAME, "source": SOURCE,
            "window_class": "FluentWindow"}


# --------------------------------------------------------------------------- #
# theme
# --------------------------------------------------------------------------- #
class Theme:
    DARK = _ThemeMode.DARK
    LIGHT = _ThemeMode.LIGHT


def setTheme(theme) -> None:                                 # noqa: N802
    try:
        _theme.set_mode(theme)
    except Exception:                                        # noqa: BLE001
        pass


def setThemeColor(color: str, *args, **kwargs) -> None:      # noqa: N802
    try:
        _theme.set_accent(color)
    except Exception:                                        # noqa: BLE001
        pass


def isDarkTheme() -> bool:                                   # noqa: N802
    try:
        return _theme.mode == _ThemeMode.DARK
    except Exception:                                        # noqa: BLE001
        return True


def apply_fluent_theme(dark: bool = True, color: str = "#0067C0") -> None:
    setTheme(_ThemeMode.DARK if dark else _ThemeMode.LIGHT)
    setThemeColor(color)


# --------------------------------------------------------------------------- #
# icons
# --------------------------------------------------------------------------- #
class _IconMeta(type):
    """`FluentIcon.SYNC` -> proxy whose `.icon()` builds the QIcon."""

    def __getattr__(cls, name: str):
        member = _FluentIconEnum.__members__.get(str(name).upper())
        if member is None:
            raise AttributeError(name)
        return _IconProxy(member)


class FluentIcon(metaclass=_IconMeta):
    pass


class _IconProxy:
    def __init__(self, member) -> None:
        self._member = member

    def icon(self) -> QIcon:
        try:
            return _fluent_icon(self._member)
        except Exception:                                    # noqa: BLE001
            return QIcon()

    def qicon(self) -> QIcon:
        return self.icon()


# Our code asks for semantic names ("library", "save", "fullscreen"); FluentPy
# only ships 107 glyphs, so each name lists the closest candidates in order.
ICON_ALIASES = {
    "library": ("DOCUMENT", "BOOK", "ARCHIVE", "FOLDER"),
    "photo": ("IMAGE", "EYE", "PHOTO", "VIEW"),
    "brush": ("EYEDROPPER", "COLOR", "EDIT", "TOOLBOX"),
    "save": ("DOCUMENT_SAVE", "ARROW_DOWNLOAD", "DOCUMENT"),
    "setting": ("SETTINGS", "TOOLBOX"),
    "folder": ("FOLDER", "FOLDER_OPEN"),
    "camera": ("CAMERA", "IMAGE"),
    "fullscreen": ("ARROW_MAXIMIZE", "GRID"),
    "search": ("DOCUMENT_SEARCH", "FILTER"),
    "delete": ("DELETE", "DISMISS"),
    "sync": ("ARROW_SYNC", "ARROW_CLOCKWISE", "ARROW_RESET"),
    "info": ("INFO", "ALERT"),
    "palette": ("COLOR", "EYEDROPPER"),
    "view": ("EYE", "GRID"),
    "export": ("ARROW_EXPORT", "ARROW_UPLOAD"),
    "open": ("FOLDER_OPEN", "DOCUMENT"),
    "app": ("APPS", "HOME"),
    "download": ("ARROW_DOWNLOAD", "ARROW_DOWN"),
    "copy": ("COPY", "DOCUMENT_COPY"),
    "play": ("GAMES", "NAVIGATION"),
    "document": ("DOCUMENT", "DOCUMENT_TEXT"),
    "help": ("INFO", "ALERT"),
    "history": ("HISTORY", "CLOCK"),
}


def icon(name: str) -> QIcon:
    """FluentPy's FluentWindow / setIcon 只要 QIcon，所以这里直接给 QIcon。"""
    key = (name or "").strip().lower()
    for cand in ICON_ALIASES.get(key, ()) + (key.upper(),):
        member = _FluentIconEnum.__members__.get(str(cand).upper())
        if member is not None:
            try:
                return _fluent_icon(member)
            except Exception:                                # noqa: BLE001
                continue
    member = _FluentIconEnum.__members__.get("INFO")
    try:
        return _fluent_icon(member) if member is not None else QIcon()
    except Exception:                                        # noqa: BLE001
        return QIcon()


def qicon(name: str) -> QIcon:
    return icon(name)


# --------------------------------------------------------------------------- #
# labels
# --------------------------------------------------------------------------- #
class _BaseLabel(QLabel):
    SIZE = 14
    WEIGHT = 400
    COLOR = None

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        font = self.font()
        font.setPixelSize(self.SIZE)
        font.setWeight(QFont.Weight(self.WEIGHT))
        self.setFont(font)
        if self.COLOR:
            self.setStyleSheet(f"color:{self.COLOR};")
        self.setWordWrap(False)


class BodyLabel(_BaseLabel):
    SIZE, WEIGHT = 14, 400


class CaptionLabel(_BaseLabel):
    SIZE, WEIGHT = 12, 400
    COLOR = "rgba(255,255,255,0.62)"


class StrongBodyLabel(_BaseLabel):
    SIZE, WEIGHT = 14, 600


class SubtitleLabel(_BaseLabel):
    SIZE, WEIGHT = 20, 600


class TitleLabel(_BaseLabel):
    SIZE, WEIGHT = 26, 600


# --------------------------------------------------------------------------- #
# buttons
# --------------------------------------------------------------------------- #
class _Tolerant:
    """FluentPy 少了一些旧控件库的 setter（setOnText/setBorderRadius…）。
    这些调用基本只影响观感，缺了就当成空操作，别让界面直接崩。"""

    _warned: set = set()

    def __getattr__(self, name: str):
        if name.startswith("set") and len(name) > 3:
            if name not in _Tolerant._warned:
                _Tolerant._warned.add(name)
                print(f"[fluentpy] 忽略缺失的 setter: {type(self).__name__}.{name}")
            return lambda *a, **k: None
        raise AttributeError(name)


class _FluentButtonMixin(_Tolerant):
    """the old widgets allowed `PushButton(icon, text, parent)`; FluentPy wants
    `FilledButton(text, parent)` and a separate `setIcon`."""

    def __init__(self, *args, parent: QWidget | None = None) -> None:
        text, ico = "", None
        for arg in args:
            if isinstance(arg, QIcon):
                ico = arg
            elif isinstance(arg, QWidget):
                parent = arg
            elif isinstance(arg, str):
                text = arg
        super().__init__(text, parent)          # type: ignore[misc]
        if ico is not None:
            try:
                self.setIcon(ico)
            except Exception:                    # noqa: BLE001
                pass


class PushButton(_FluentButtonMixin, _w.FilledButton):
    pass


class PrimaryPushButton(_FluentButtonMixin, _w.AccentButton):
    pass


class ToolButton(_FluentButtonMixin, _w.Button):
    pass


class TransparentToolButton(_FluentButtonMixin, _w.TextButton):
    pass


class ToggleButton(_FluentButtonMixin, _w.FilledButton):
    def __init__(self, *args, parent: QWidget | None = None) -> None:
        super().__init__(*args, parent=parent)
        self.setCheckable(True)


class SwitchButton(_Tolerant, _w.ToggleSwitch):
    """the old widgets spelled the signal `checkedChanged`; FluentPy has `toggled`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.checkedChanged = self.toggled        # type: ignore[attr-defined]

    def setText(self, text: str) -> None:          # noqa: N802
        pass

    def text(self) -> str:
        return ""


class Slider(_Tolerant, _w.Slider):
    def __init__(self, orientation=Qt.Horizontal, parent: QWidget | None = None) -> None:
        super().__init__(orientation, parent)


def _split_args(args):
    """旧控件库允许把 parent 当第一个参数，FluentPy 往往不是。"""
    parent, rest = None, []
    for arg in args:
        if isinstance(arg, QWidget) and parent is None:
            parent = arg
        else:
            rest.append(arg)
    return rest, parent


class ComboBox(_Tolerant, _w.ComboBox):
    def __init__(self, *args, **kwargs):
        rest, parent = _split_args(args)
        super().__init__(parent or kwargs.pop("parent", None), *rest, **kwargs)


class LineEdit(_Tolerant, _w.LineEdit):
    def __init__(self, *args, **kwargs):
        rest, parent = _split_args(args)
        try:
            super().__init__(*rest, parent=parent or kwargs.pop("parent", None), **kwargs)
        except TypeError:
            super().__init__(rest[0] if rest else "", parent or kwargs.pop("parent", None))


class SearchLineEdit(_Tolerant, _w.SearchLineEdit):
    def __init__(self, *args, **kwargs):
        rest, parent = _split_args(args)
        placeholder = rest[0] if rest and isinstance(rest[0], str) else ""
        super().__init__(placeholder, parent or kwargs.pop("parent", None))


class ProgressBar(_Tolerant, _w.ProgressBar):
    def __init__(self, *args, **kwargs):
        rest, parent = _split_args(args)
        super().__init__(parent or kwargs.pop("parent", None))
        if rest and isinstance(rest[0], str):
            # 旧控件库: ProgressBar(parent) / Qt: ProgressBar(orientation, parent)
            pass


class SpinBox(_w.SpinBox):
    pass


class DoubleSpinBox(_w.DoubleSpinBox):
    pass


# --------------------------------------------------------------------------- #
# cards / containers FluentPy lacks
# --------------------------------------------------------------------------- #
class CardWidget(_Tolerant, _w.CardWidget):
    pass


class SimpleCardWidget(_w.CardWidget):
    pass


class HeaderCardWidget(_w.CardWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.headerLayout = QHBoxLayout(self)
        self.titleLabel = QLabel("", self)
        font = self.titleLabel.font()
        font.setPixelSize(16)
        font.setWeight(QFont.Weight.DemiBold)
        self.titleLabel.setFont(font)
        self.headerLayout.addWidget(self.titleLabel)
        self.headerLayout.addStretch(1)
        self.viewLayout = None

    def setTitle(self, text: str) -> None:          # noqa: N802
        self.titleLabel.setText(text)


class ScrollArea(QScrollArea):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)
        self.setStyleSheet("QScrollArea{background:transparent;border:none;}")


class SmoothScrollArea(ScrollArea):
    pass


class HorizontalSeparator(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet("background:rgba(255,255,255,0.12);border:none;")


class IconWidget(QLabel):
    def __init__(self, icon_obj=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon = QIcon()
        self.setFixedSize(QSize(16, 16))
        if icon_obj is not None:
            self.setIcon(icon_obj)

    def setIcon(self, icon_obj) -> None:            # noqa: N802
        try:
            if hasattr(icon_obj, "icon"):
                icon_obj = icon_obj.icon()
            self._icon = icon_obj or QIcon()
            self.setPixmap(self._icon.pixmap(QSize(16, 16)))
        except Exception:                            # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# InfoBar
# --------------------------------------------------------------------------- #
class InfoBarPosition(enum.Enum):
    TOP_LEFT = 0
    TOP_RIGHT = 1
    BOTTOM_LEFT = 2
    BOTTOM_RIGHT = 3
    TOP = 4


_TONE = {"success": "success", "warning": "warning", "error": "danger",
         "information": "info"}


class InfoBar:
    """Adapter for `InfoBar.success(title=..., content=...)` style calls."""

    def __init__(self, parent: QWidget | None = None, **kwargs) -> None:
        self._bar = None
        self._parent = parent
        self._kwargs = kwargs

    @classmethod
    def _make(cls, tone: str, **kwargs):
        parent = kwargs.get("parent")
        title = kwargs.get("title") or kwargs.get("content") or ""
        content = kwargs.get("content") or ""
        if title == content:
            content = ""
        try:
            bar = _w.InfoBar(title, content, parent, tone=_TONE.get(tone, "info"),
                             closable=bool(kwargs.get("isClosable", True)))
            show = getattr(bar, "show", None)
            if callable(show):
                show()
            return bar
        except Exception:                            # noqa: BLE001
            return None

    @classmethod
    def success(cls, **kwargs):                      # noqa: D401
        return cls._make("success", **kwargs)

    @classmethod
    def warning(cls, **kwargs):
        return cls._make("warning", **kwargs)

    @classmethod
    def error(cls, **kwargs):
        return cls._make("error", **kwargs)

    @classmethod
    def information(cls, **kwargs):
        return cls._make("information", **kwargs)


# --------------------------------------------------------------------------- #
# window
# --------------------------------------------------------------------------- #
class FluentWidget(QWidget):
    pass


class FluentWindow(_fp.FluentWindow):
    """FluentPy's window plus the two legacy calls our code still makes."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._mica = False

    # 旧控件库的 API 保留成空实现：窗口边框由 FluentPy 自己处理
    def setMicaEffectEnabled(self, on: bool = True) -> None:   # noqa: N802
        self._mica = bool(on)
        try:
            from fluentpy.window_effects import apply_system_backdrop
            apply_system_backdrop(self, dark=isDarkTheme(), enabled=bool(on))
        except Exception:                                      # noqa: BLE001
            pass

    def setBackgroundColor(self, color: QColor) -> None:       # noqa: N802
        try:
            self.setStyleSheet(f"FluentWindow{{background:{color.name()};}}")
        except Exception:                                      # noqa: BLE001
            pass

    def stackedWidget(self):                                   # noqa: N802
        """旧控件库暴露 `.stackedWidget`；这里用当前页 emulate 一下。"""
        window = self
        page = getattr(window, "current_page", None)

        class _Stack:
            def currentWidget(self_inner):                     # noqa: N802
                if callable(page):
                    try:
                        return page()
                    except Exception:                          # noqa: BLE001
                        return None
                return page

        return _Stack()

    # FluentPy signature is addSubInterface(widget, icon, text, routeKey=None)
    def addSubInterface(self, widget, icon_obj, text, *args, **kwargs):  # noqa: N802
        qico = icon_obj.icon() if hasattr(icon_obj, "icon") else icon_obj
        try:
            return super().addSubInterface(widget, qico, text, *args, **kwargs)
        except TypeError:
            return self.add_page(widget, text, qico)
