#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按文本定位控件并导出裁剪图，用于人工核对对比度判定的真伪。"""

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
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QLabel, QAbstractButton, QScrollArea,
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

WIN = MainWindow(remaining_seconds=0, license_exp_ts=0)
WIN.resize(1680, 1000)
WIN.show()


def pump(n=14):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.05)


pump(12)

WANT = ["项目列表", "总计", "未选择图片", "Left Click"]

OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots")
stack = WIN.stacked_widget
for idx in range(stack.count()):
    stack.setCurrentIndex(idx)
    pump(8)
    holder = stack.widget(idx)
    page = holder.widget() if isinstance(holder, QScrollArea) else holder
    pimg = page.grab()
    dpr = float(pimg.devicePixelRatio() or 1.0)
    img = pimg.toImage()

    for w in [page] + list(page.findChildren(QWidget)):
        if not isinstance(w, (QLabel, QAbstractButton)):
            continue
        try:
            if not w.isVisible() or w.width() < 6 or w.height() < 6:
                continue
        except Exception:
            continue
        t = w.text() if hasattr(w, "text") else ""
        t = re.sub(r"<[^>]+>", "", str(t or "")).strip()
        if not any(k in t for k in WANT):
            continue
        pos = w.mapTo(page, QPoint(0, 0))
        x0, y0 = int(pos.x() * dpr), int(pos.y() * dpr)
        x1 = min(img.width(), x0 + int(w.width() * dpr))
        y1 = min(img.height(), y0 + int(w.height() * dpr))
        safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]+", "_", t)[:16] or "w"
        out = os.path.join(OUT, f"flag_p{idx}_{safe}.png")
        try:
            img.copy(max(0, x0), max(0, y0),
                     max(1, x1 - max(0, x0)), max(1, y1 - max(0, y0))).save(out)
            print(f"[p{idx}] {t[:26]!r:30} geo={w.width()}x{w.height()} "
                  f"mapTo=({pos.x()},{pos.y()}) -> {os.path.basename(out)}")
        except Exception as e:
            print(f"[p{idx}] {t[:26]!r} crop失败: {e}")

WIN.close()
