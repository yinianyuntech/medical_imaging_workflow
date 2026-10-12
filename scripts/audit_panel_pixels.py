#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对面板区域做像素审计：确认材质颗粒是**纯冷蓝**，不存在杂色条纹/伪彩。"""

import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("MIMW_SKIN", "metal")

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.core.qt_compat.QtWidgets import QApplication, QWidget, QGroupBox  # noqa: E402

app = QApplication.instance() or QApplication([])
from src.utils.skeuomorphic import apply_global  # noqa: E402
apply_global(app)
from ui.widgets.main_window import MainWindow  # noqa: E402

win = MainWindow(remaining_seconds=0, license_exp_ts=0)
win.resize(1680, 1000)
win.show()


def pump(n=12):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.04)


pump(10)

box = None
for gb in win.project_management_widget.findChildren(QGroupBox):
    if gb.title() == "项目管理":
        box = gb
        break
if box is None:
    print("未找到面板")
    sys.exit(1)

pm = box.grab()          # 直接抓面板自身，避免 DPR / 坐标映射误差
img = pm.toImage()
W, H = img.width(), img.height()
print(f"面板抓图 {W}x{H} (DPR={pm.devicePixelRatio()})")

# 采样内部空白区：避开顶部标牌标题(约 40px)、左右边、底部
x0, x1 = int(W * 0.35), int(W * 0.95)
y0, y1 = 100, max(120, H - 80)
print(f"取样区域 x[{x0},{x1}] y[{y0},{y1}]")

counts = Counter()
nonblue = []
step = 3
for y in range(y0, y1, step):
    for x in range(x0, x1, step):
        if x >= img.width() or y >= img.height():
            continue
        c = img.pixelColor(x, y)
        r, g, b = c.red(), c.green(), c.blue()
        counts[(r // 16, g // 16, b // 16)] += 1
        # 冷蓝材质应满足 b >= r 且 b >= g；否则记为杂色
        if b < r or b < g:
            nonblue.append((x, y, f"#{r:02X}{g:02X}{b:02X}"))

total = sum(counts.values())
print(f"采样点 {total}，非冷蓝像素 {len(nonblue)}  ({100.0 * len(nonblue) / max(1, total):.2f}%)")
for item in nonblue[:10]:
    print("   杂色:", item)

print("\n最常见的 8 种色（量化到 16 级）:")
for k, v in counts.most_common(8):
    r, g, b = [c * 16 for c in k]
    print(f"   #{r:02X}{g:02X}{b:02X}  x{v}")
win.close()
