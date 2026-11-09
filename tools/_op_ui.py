"""看模型库里「角色」分类和干员模型的实际显示效果。

用法： python tools/_op_ui.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.getcwd())

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.browser import ModelBrowser  # noqa: E402
from app.main_window import VertexViewerWindow as MainWindow  # noqa: E402
from core import loader  # noqa: E402

OUT = os.path.join(os.getcwd(), "work")


def main() -> None:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1500, 940)
    win.show()

    steps = []

    def add(fn, delay):
        steps.append((fn, delay))

    def grab(name):
        def _do():
            path = os.path.join(OUT, name)
            win.grab().save(path)
            print("[shot]", path)
        return _do

    def category(name):
        def _do():
            browsers = win.findChildren(ModelBrowser)
            if browsers:
                browsers[0]._set_category(name)
                print("[ui] category ->", name)
        return _do

    def load(vpath):
        def _do():
            print("[ui] load", vpath.rsplit("/", 1)[-1])
            win.load_vpath(vpath)
        return _do

    ops = [v for v in loader.index()
           if v.lower().endswith(".uasset")
           and "hero_hd" in v.lower() and v.lower().endswith("_body_3p_hd.uasset")
           and "physics" not in v.lower()]
    ops.sort()
    skin = [v for v in loader.index()
            if v.lower().endswith(".uasset") and "charappear" in v.lower()
            and v.lower().endswith("_body_3p_hd.uasset")]

    add(category("角色"), 2500)
    add(grab("op_ui_role.png"), 2500)
    if ops:
        add(load(ops[0]), 200)
        add(grab("op_ui_model.png"), 26000)
    if skin:
        add(load(skin[0]), 200)
        add(grab("op_ui_skin.png"), 26000)
    add(lambda: app.quit(), 600)

    delay = 9000                      # 等启动时的「恢复上次模型」
    for fn, wait in steps:
        QTimer.singleShot(delay, fn)
        delay += wait
    app.exec()


if __name__ == "__main__":
    main()
