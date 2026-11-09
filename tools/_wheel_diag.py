"""查首页卡片列表的滚轮为什么不动。

打印 QScrollArea 的可滚动范围、卡片网格的尺寸，并真的往 viewport 里塞一个
QWheelEvent 看 scrollbar 会不会变。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.getcwd())

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import (QApplication, QScrollArea,  # noqa: E402
                               QScrollBar)

from app.browser import ModelBrowser  # noqa: E402
from app.main_window import VertexViewerWindow  # noqa: E402


def main() -> None:
    app = QApplication(sys.argv)
    win = VertexViewerWindow()
    win.resize(1500, 940)
    win.show()

    def probe():
        pages = win.findChildren(ModelBrowser)
        if not pages:
            print("no ModelBrowser")
            app.quit()
            return
        page = pages[0]
        area = page.card_scroll
        bar = area.verticalScrollBar()
        grid = page.grid
        print("scrollarea:", area.size(), "viewport:", area.viewport().size())
        print("grid size:", grid.size(), "sizeHint:", grid.sizeHint(),
              "minHint:", grid.minimumSizeHint())
        print("bar range:", bar.minimum(), bar.maximum(), "page step:", bar.pageStep(),
              "value:", bar.value())
        print("grid children:", len(grid.findChildren(object)))
        print("policies:", area.verticalScrollBarPolicy(),
              area.horizontalScrollBarPolicy())
        # 直接往视口塞滚轮事件
        before = bar.value()
        vp = area.viewport()
        pos = QPointF(vp.width() / 2, vp.height() / 2)
        ev = QWheelEvent(pos, vp.mapToGlobal(pos), QPoint(0, 0), QPoint(0, -120),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(vp, ev)
        app.processEvents()
        print("wheel on viewport:", before, "->", bar.value())
        # 再试卡片本身
        cards = [c for c in grid.children() if c.__class__.__name__ == "_ModelCard"]
        if cards:
            card = cards[0]
            before = bar.value()
            gp = QPointF(card.width() / 2, card.height() / 2)
            ev2 = QWheelEvent(gp, card.mapToGlobal(gp), QPoint(0, 0),
                              QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                              Qt.NoScrollPhase, False)
            QApplication.sendEvent(card, ev2)
            app.processEvents()
            print("wheel on card:", before, "->", bar.value(),
                  "card size:", card.size())
        app.quit()

    QTimer.singleShot(11000, probe)
    app.exec()


if __name__ == "__main__":
    main()
