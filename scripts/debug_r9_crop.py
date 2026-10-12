#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R9 误报定位：复刻 check_contrast 的裁剪与百分位逻辑，把中间量全部打印出来。

目标控件：浅色主题下被报"低对比"的 开始科学分析 (RAG)。
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("MIMW_SKIN", "metal")
os.environ["MIMW_THEME"] = "light"

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.core.qt_compat.QtCore import QPoint  # noqa: E402
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QPushButton, QScrollArea, QWidget,
)

app = QApplication.instance() or QApplication([])

from src.utils.skeuomorphic import apply_global  # noqa: E402
from src.utils.skeuo_style import install  # noqa: E402


def _wcag_lum(c) -> float:
    def f(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c.red()) + 0.7152 * f(c.green()) + 0.0722 * f(c.blue())

apply_global(app)
install(app)

from ui.widgets.main_window import MainWindow  # noqa: E402

win = MainWindow(remaining_seconds=0, license_exp_ts=0)
win.resize(1680, 1000)
win.show()


def pump(n=14):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.05)


pump(14)

stack = win.stacked_widget
TARGET = "开始科学分析"

for idx in range(stack.count()):
    stack.setCurrentIndex(idx)
    pump(8)
    holder = stack.widget(idx)
    page = holder.widget() if isinstance(holder, QScrollArea) else holder
    page_img = page.grab()
    dpr = float(page_img.devicePixelRatio() or 1.0)
    img = page_img.toImage()

    btn = None
    for b in page.findChildren(QPushButton):
        if TARGET in (b.text() or ""):
            btn = b
            break
    if btn is None:
        continue

    print(f"page[{idx}] {type(page).__name__}  抓图={img.width()}x{img.height()} DPR={dpr}")
    print(f"  按钮 geo={btn.width()}x{btn.height()} visible={btn.isVisible()} "
          f"enabled={btn.isEnabled()}")
    print(f"  按钮在父链中的 parent = {type(btn.parentWidget()).__name__}")
    par = btn.parentWidget()
    print(f"  parent geo={par.width()}x{par.height()}  btn.geometry()={btn.geometry()}")

    pos = btn.mapTo(page, QPoint(0, 0))
    x0, y0 = int(pos.x() * dpr), int(pos.y() * dpr)
    cw, ch = int(btn.width() * dpr), int(btn.height() * dpr)
    x1, y1 = min(img.width(), x0 + cw), min(img.height(), y0 + ch)
    print(f"  mapTo(page)=({pos.x()},{pos.y()})  crop=({x0},{y0})-({x1},{y1})")

    # 复刻 R9 的 inset + 采样
    inset = min(int(max(2, min(cw, ch) // 10)), 8)
    ix0, iy0, ix1, iy1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
    if ix1 - ix0 < 4 or iy1 - iy0 < 4:
        ix0, iy0, ix1, iy1 = x0, y0, x1, y1
    print(f"  inset={inset}  内部采样区=({ix0},{iy0})-({ix1},{iy1})")

    step = max(1, min(ix1 - ix0, iy1 - iy0) // 40)
    samples = []
    for y in range(iy0 + 1, iy1 - 1, step):
        for x in range(ix0 + 1, ix1 - 1, step):
            c = img.pixelColor(x, y)
            samples.append((_wcag_lum(c), c))
    n = len(samples)
    samples.sort(key=lambda t: t[0])
    print(f"  step={step} 样本数={n}")
    if n:
        for frac in (0.002, 0.02, 0.25, 0.5, 0.75, 0.98, 0.998):
            i = max(0, min(n - 1, int(n * frac)))
            c = samples[i][1]
            print(f"     p{frac*100:5.1f}%  lum={samples[i][0]:.4f}  "
                  f"#{c.red():02X}{c.green():02X}{c.blue():02X}")

    out = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots",
                       f"r9debug_p{idx}.png")
    img.copy(max(0, x0), max(0, y0), max(1, x1 - max(0, x0)),
             max(1, y1 - max(0, y0))).save(out)
    # 同时保存"内部采样区"
    out2 = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots",
                        f"r9debug_inner_p{idx}.png")
    img.copy(max(0, ix0), max(0, iy0), max(1, ix1 - max(0, ix0)),
             max(1, iy1 - max(0, iy0))).save(out2)
    print(f"  裁剪已存: {os.path.basename(out)} / {os.path.basename(out2)}")

win.close()
