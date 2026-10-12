#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""低对比度判定机制诊断：对若干被标记的控件，打印其真实坐标/调色板/像素直方图。"""

import os
import re
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("MIMW_SKIN", "metal")

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.core.qt_compat.QtCore import QPoint  # noqa: E402
from src.core.qt_compat.QtGui import QPalette  # noqa: E402
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QLabel, QCheckBox, QAbstractButton, QScrollArea,
)

app = QApplication.instance() or QApplication([])
from src.utils.skeuomorphic import apply_global  # noqa: E402
apply_global(app)
try:
    from src.utils.skeuo_style import install as install_style
    install_style(app)
except Exception:
    pass
from ui.widgets.main_window import MainWindow  # noqa: E402

win = MainWindow(remaining_seconds=0, license_exp_ts=0)
win.resize(1680, 1000)
win.show()


def pump(n=14):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.05)


pump(12)

TARGET_PAGE = int(os.environ.get("PROBE_PAGE", "3"))   # 3 = OCRWidget
LIMIT = int(os.environ.get("PROBE_LIMIT", "6"))

stack = win.stacked_widget
stack.setCurrentIndex(TARGET_PAGE)
pump(10)
holder = stack.widget(TARGET_PAGE)
page = holder.widget() if isinstance(holder, QScrollArea) else holder

page_img = page.grab()
dpr = float(page_img.devicePixelRatio() or 1.0)
img = page_img.toImage()
print(f"页面={type(page).__name__}  抓图={img.width()}x{img.height()}  DPR={dpr}")

shown = 0
for w in [page] + list(page.findChildren(QWidget)):
    if shown >= LIMIT:
        break
    if not isinstance(w, (QLabel, QAbstractButton)):
        continue
    try:
        if not w.isVisible() or w.width() < 6 or w.height() < 6:
            continue
    except Exception:
        continue
    t = w.text() if hasattr(w, "text") else ""
    t = re.sub(r"<[^>]+>", "", str(t or "")).strip()
    if not t or len(t) < 2:
        continue

    pos = w.mapTo(page, QPoint(0, 0))
    x0, y0 = int(pos.x() * dpr), int(pos.y() * dpr)
    cw, ch = int(w.width() * dpr), int(w.height() * dpr)
    x1, y1 = min(img.width(), x0 + cw), min(img.height(), y0 + ch)
    inside = (0 <= x0 < img.width()) and (0 <= y0 < img.height())
    pal = w.palette().color(QPalette.WindowText)
    hist = {}
    for y in range(max(0, y0) + 1, max(0, y1) - 1):
        for x in range(max(0, x0) + 1, max(0, x1) - 1):
            c = img.pixelColor(x, y)
            k = (c.red() // 8, c.green() // 8, c.blue() // 8)
            hist[k] = hist.get(k, 0) + 1
    top = sorted(hist.items(), key=lambda kv: -kv[1])[:4]
    tops = " ".join(f"#{k[0]*8:02X}{k[1]*8:02X}{k[2]*8:02X}x{n}" for k, n in top)
    m = re.search(r"color\s*:\s*(#[0-9A-Fa-f]{6})", w.styleSheet() or "")
    print(f"  [{type(w).__name__:12}] {t[:20]!r}")
    print(f"        geo={w.width()}x{w.height()} mapTo=({pos.x()},{pos.y()}) "
          f"crop=({x0},{y0})-({x1},{y1}) inside={inside}")
    print(f"        paletteWindowText=#{pal.red():02X}{pal.green():02X}{pal.blue():02X} "
          f"enabled={w.isEnabled()} ss色={m.group(1) if m else '-'}")
    print(f"        top像素: {tops}")
    # 保存裁剪图，供人工核对"是否真的没有文字"
    try:
        crop = img.copy(max(0, x0), max(0, y0),
                        max(1, min(img.width(), x1) - max(0, x0)),
                        max(1, min(img.height(), y1) - max(0, y0)))
        safe = re.sub(r"[^0-9A-Za-z一-龥]+", "_", t)[:18] or f"w{shown}"
        out = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots",
                           f"crop_{TARGET_PAGE}_{shown}_{safe}.png")
        crop.save(out)
        print(f"        crop saved: {os.path.basename(out)}")
    except Exception as e:
        print("        crop save failed:", e)
    shown += 1

win.close()
