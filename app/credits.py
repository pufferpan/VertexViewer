"""Wizard-style credits, ordered by English names or Chinese pinyin."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, Qt, Signal
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsOpacityEffect, QLabel,
                               QScrollArea, QVBoxLayout, QWidget)
from fluentpy import widgets as W

from app.transitions import SurfaceWindow
from app.wizard import BG, _Backdrop, _asset


def credit_entries():
    try:
        rows = json.loads(Path(_asset("credits.json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(rows,list):return []
    valid=[row for row in rows if isinstance(row,dict) and str(row.get('name','')).strip()]
    return sorted(valid,key=lambda row:str(row.get('sort_key') or row['name']).casefold())


class CreditsWindow(SurfaceWindow):
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("VertexViewer · 感谢名单")
        self._closing = False
        self._opened = False
        self.bg = _Backdrop(BG, self)
        self.bg.reset_rows()
        self.panel = W.SimpleCardWidget(self)
        self.panel.setBorderRadius(22)
        self.panel.setObjectName("creditsPanel")
        self.panel.setStyleSheet(
            "QLabel { color: #EAF4FF; background: transparent; border: 0; }")
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(42, 36, 42, 30)
        layout.setSpacing(18)
        brand = QLabel("VertexViewer", self.panel)
        brand.setStyleSheet("font-size: 24px; font-weight: 700;")
        layout.addWidget(brand)
        self.heading = QLabel("感谢名单", self.panel)
        self.heading.setStyleSheet("font-size: 34px; font-weight: 700;")
        layout.addWidget(self.heading)
        scroll = self.scroll = QScrollArea(self.panel)
        scroll.setVerticalScrollBar(W.FluentScrollBar(Qt.Vertical,scroll))
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea, QWidget#creditsList { background: transparent; border: 0; }")
        self.list_body = QWidget()
        self.list_body.setObjectName("creditsList")
        self.list_layout = QVBoxLayout(self.list_body)
        self.list_layout.setContentsMargins(0, 10, 0, 10)
        self.list_layout.setSpacing(18)
        self.entries = credit_entries()
        for row in self.entries:
            name = QLabel(str(row["name"]), self.list_body)
            name.setTextFormat(Qt.PlainText)
            name.setTextInteractionFlags(Qt.TextSelectableByMouse)
            name.setStyleSheet("font-size: 20px; font-weight: 600;")
            name.setWordWrap(True)
            self.list_layout.addWidget(name)
            if str(row.get("description", "")).strip():
                description=str(row['description'])
                if description.startswith(('https://','http://')):
                    detail=W.HyperlinkButton(description,self.list_body,url=description)
                    detail.setToolTip(description)
                else:
                    detail=QLabel(description,self.list_body)
                    detail.setTextFormat(Qt.PlainText)
                    detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
                    detail.setStyleSheet("font-size: 14px; color: #A9C4DE;")
                    detail.setWordWrap(True)
                self.list_layout.addWidget(detail)
        self.list_layout.addStretch(1)
        scroll.setWidget(self.list_body)
        layout.addWidget(scroll, 1)
        self.back_button = W.AccentButton("返回", self.panel)
        self.back_button.setMinimumHeight(42)
        self.back_button.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.back_button, 0, Qt.AlignLeft)
        self.back_button.clicked.connect(self.close)
        self._effect = QGraphicsOpacityEffect(self.panel)
        self._effect.setOpacity(0.0)
        self.panel.setGraphicsEffect(self._effect)

    def _layout_surface(self):
        if not hasattr(self, "bg"):
            return
        rect = self.surfaceRect
        self.bg.setGeometry(rect)
        width = min(620, max(320, int(rect.width() * .43)), max(1, rect.width() - 40))
        height = min(660, max(440, int(rect.height() * .72)), max(1, rect.height() - 40))
        self.panel.setGeometry(rect.x() + max(20, int(rect.width() * .05)),
                               rect.y() + (rect.height() - height) // 2, width, height)
        self.bg.lower()
        self.panel.raise_()

    def start(self):
        screen = QApplication.primaryScreen()
        area = screen.availableGeometry() if screen else QRect(0, 0, 1500, 940)
        self.setGeometry(area)
        width, height = min(760, area.width()), min(470, area.height())
        self.surfaceRect = QRect((area.width() - width) // 2, (area.height() - height) // 2,
                                 width, height)
        self.bg.set_growing(True)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self.animate_surface(self.rect(), 740, self._finish_open)
        fade = QPropertyAnimation(self._effect, b"opacity", self)
        fade.setDuration(640)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade = fade
        fade.start()

    def _finish_open(self):
        self._opened = True
        self.bg.set_growing(False)
        self.bg.reset_rows()

    def closeEvent(self, event):
        if self._closing:
            event.accept()
            return
        event.ignore()
        self._closing = True
        self.bg.set_growing(True)
        self._fade.stop()
        fade = QPropertyAnimation(self._effect, b"opacity", self)
        fade.setDuration(280)
        fade.setStartValue(self._effect.opacity())
        fade.setEndValue(0.0)
        self._fade = fade
        fade.start()
        width, height = min(560, self.width()), min(346, self.height())
        target = QRect((self.width() - width) // 2, (self.height() - height) // 2, width, height)
        self.animate_surface(target, 340, self._done)

    def _done(self):
        self.hide()
        self.close()
        self.finished.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_Enter, Qt.Key_Return):
            self.close()
        else:
            super().keyPressEvent(event)
