"""在真实窗口里跟踪滚轮事件：谁收到了、有没有被接受。

跑起来后把鼠标放在卡片上滚一下，终端会打印事件链路。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.getcwd())

from PySide6.QtCore import QEvent, QObject, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.main_window import VertexViewerWindow  # noqa: E402


class Spy(QObject):
    def eventFilter(self, obj, event):                       # noqa: N802
        if event.type() == QEvent.Wheel:
            name = obj.__class__.__name__
            extra = ""
            if hasattr(obj, "objectName"):
                extra = obj.objectName()
            print(f"[wheel] -> {name} {extra}", flush=True)
        return False


def main() -> None:
    app = QApplication(sys.argv)
    win = VertexViewerWindow()
    win.resize(1500, 940)
    win.show()
    spy = Spy()
    app.installEventFilter(spy)
    QTimer.singleShot(60000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
