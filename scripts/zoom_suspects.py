#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把可疑控件裁出来放大，供人工目视判定（重影 / 溢出）。

对 R12 的每一条命中，光看指标无法区分"真错位重绘"与"重复字形天然相似"
（`TXT` 的两个 T、汉字致密笔画都会让孪生率虚高）。
所以这里输出 3 倍放大的裁剪图，由眼睛做最终裁决。
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("MIMW_SKIN", "metal")
os.environ.setdefault("MIMW_THEME", "light")

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.core.qt_compat.QtCore import Qt, QPoint, QRect  # noqa: E402
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QScrollArea, QPushButton, QLabel, QComboBox, QFrame,
)

app = QApplication.instance() or QApplication([])

from src.utils import skeuomorphic as sk  # noqa: E402
from src.utils import skeuo_style as st  # noqa: E402

sk.apply_global(app)
st.install(app)

from ui.widgets.main_window import MainWindow  # noqa: E402

win = MainWindow(remaining_seconds=0, license_exp_ts=0)
win.resize(1680, 1000)
win.show()


def pump(n=16):
    import time
    for _ in range(n):
        app.processEvents()
        time.sleep(0.05)


pump(20)

OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots")
os.makedirs(OUT, exist_ok=True)


def zoom_crop(page, w, name, scale=3, pad=6):
    pos = w.mapTo(page, QPoint(0, 0))
    dpr = float(page.grab().devicePixelRatio() or 1.0)
    img = page.grab().toImage()
    x = int(pos.x() * dpr) - pad
    y = int(pos.y() * dpr) - pad
    cw = int(w.width() * dpr) + pad * 2
    ch = int(w.height() * dpr) + pad * 2
    x = max(0, x)
    y = max(0, y)
    cw = min(cw, img.width() - x)
    ch = min(ch, img.height() - y)
    if cw < 4 or ch < 4:
        print("   跳过（尺寸过小）:", name)
        return None
    crop = img.copy(x, y, cw, ch)
    big = crop.scaled(crop.width() * scale, crop.height() * scale,
                      Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.FastTransformation)
    p = os.path.join(OUT, f"zoom_{name}.png")
    big.save(p)
    print(f"   {name}: 裁剪({cw}x{ch}) → 放大 x{scale} → {os.path.basename(p)}")
    return p


stack = win.stacked_widget

# ---- 1) 函数按钮里的 QLabel 溢出 ----
stack.setCurrentIndex(0)
pump(10)
holder = stack.widget(0)
page = holder.widget() if isinstance(holder, QScrollArea) else holder
print("== 页0 ProjectManagementWidget ==")
for b in page.findChildren(QPushButton):
    kids = b.findChildren(QLabel, options=Qt.FindChildOption.FindDirectChildrenOnly)
    if not kids:
        continue
    print(f"   按钮 {b.text()[:16]!r} 尺寸={b.width()}x{b.height()} "
          f"子标签={[(k.geometry().x(), k.geometry().y(), k.width(), k.height()) for k in kids]}")
    zoom_crop(page, b, f"fnbtn_{abs(hash(b.text())) % 1000}")
    break

# ---- 2) AI 概要页的下拉框溢出 ----
for i in range(stack.count()):
    if type(stack.widget(i).widget() if isinstance(stack.widget(i), QScrollArea)
            else stack.widget(i)).__name__ != "AISummaryWidget":
        continue
    stack.setCurrentIndex(i)
    pump(10)
    holder = stack.widget(i)
    page = holder.widget() if isinstance(holder, QScrollArea) else holder
    print(f"== 页{i} AISummaryWidget ==")
    for cb in page.findChildren(QComboBox):
        fr = cb.parentWidget()
        print(f"   下拉框 尺寸={cb.width()}x{cb.height()} geo={cb.geometry()}   "
              f"父={type(fr).__name__} 父尺寸={fr.width()}x{fr.height()}")
        zoom_crop(page, fr, "aisummary_row")
        break
    break

# ---- 3) R12 命中的几个代表 ----
print("== R12 目视样本 ==")
targets = [("刷新列表", 2), ("TXT", 2), ("开始文本处理", 3), ("选择单个文件", 1)]
for txt, idx in targets:
    if idx >= stack.count():
        continue
    stack.setCurrentIndex(idx)
    pump(8)
    holder = stack.widget(idx)
    page = holder.widget() if isinstance(holder, QScrollArea) else holder
    for w in page.findChildren(QWidget):
        try:
            t = w.text() if hasattr(w, "text") else (
                w.currentText() if isinstance(w, QComboBox) else "")
        except Exception:
            continue
        if t and t.strip() == txt and w.isVisible() and w.width() > 20:
            zoom_crop(page, w, f"ghost_{idx}_{txt}", scale=4)
            break

win.close()
print("完成")
