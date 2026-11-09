"""Rewrite the five page screenshots with a settled navigation animation."""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.fluent_api import QApplication, apply_dark_palette, apply_fluent_theme  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv[:1])
apply_fluent_theme(True)
apply_dark_palette(app, True)

from app.main_window import VertexViewerWindow  # noqa: E402

w = VertexViewerWindow()
w.resize(1500, 940)
w.show()

vp = "../../../DeltaForce/Content/Models/Weapons/Parts/Bullet/Bullets_12Gauge_828/Bullets_12Gauge_828_3P.uasset"
deadline = time.time() + 90
while time.time() < deadline and not w.browser.is_ready:
    app.processEvents()
w.load_vpath(vp)
deadline = time.time() + 150
while time.time() < deadline and w.bundle is None:
    app.processEvents()
print("loaded", w.bundle.display_name if w.bundle else None, flush=True)

PAGES = [
    ("library", "lib"),
    ("textures", "tex"),
    ("materials", "mat"),
    ("export", "exp"),
    ("settings", "set"),
]
for index, (attr, tag) in enumerate(PAGES, 1):
    page = getattr(w, f"{attr}_page")
    w.switchTo(page)
    for _ in range(30):
        app.processEvents()
        time.sleep(0.02)
    path = f"app/shot_page_{index}_{attr}.png"
    ok = w.grab().save(path)
    print("page", index, attr, ok, path, flush=True)
print("done")
