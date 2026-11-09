"""验证「合并变体时优先挑 UI 网格」是否生效。

按关键字过滤几组资产，打印每组最终挑中的是哪个变体。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.getcwd())

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.browser import ModelBrowser, _variant_of  # noqa: E402
from app.main_window import VertexViewerWindow  # noqa: E402


def main() -> None:
    app = QApplication(sys.argv)
    win = VertexViewerWindow()
    win.resize(1500, 940)
    win.show()

    def probe():
        page = win.findChildren(ModelBrowser)[0]
        for kw in ("头盔", "M4A1", "钥匙卡"):
            q = kw.lower()
            rels = [r for r in page._rels                   # noqa: SLF001
                    if q in ((page._meta.get(r) or {}).get("search") or "")]
            groups = page._group_rels(rels)             # noqa: SLF001
            print(f"\n=== {kw}: {len(rels)} 个资产 / {len(groups)} 张卡")
            shown = 0
            for rel, count in groups:
                if count < 2:
                    continue
                stem = (page._meta.get(rel) or {}).get("stem") or rel.rsplit("/", 1)[-1][:-7]
                print(f"  [{count} 变体] 选中 {_variant_of(stem) or '原版':<6} {stem}")
                shown += 1
                if shown >= 6:
                    break
        app.quit()

    QTimer.singleShot(12000, probe)
    app.exec()


if __name__ == "__main__":
    main()
