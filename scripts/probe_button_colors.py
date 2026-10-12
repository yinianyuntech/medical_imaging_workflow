#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采样按钮实际渲染色，验证语义色（成功绿/危险红/警告橙）是否被全局材质覆盖。"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("MIMW_SKIN", "metal")

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.core.qt_compat.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

app = QApplication.instance() or QApplication([])
from src.utils.skeuomorphic import apply_global, strip_conflicting_stylesheets  # noqa: E402
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

TARGETS = ["新建样本", "删除样本", "刷新", "新建项目", "删除勾选", "DICOM"]


def snapshot(tag):
    print(f"\n=== {tag} ===")
    for name in TARGETS:
        found = None
        for pg_idx in range(win.stacked_widget.count()):
            holder = win.stacked_widget.widget(pg_idx)
            page = holder.widget() if hasattr(holder, "widget") else holder
            if page is None:
                continue
            for b in page.findChildren(QPushButton):
                if b.text().strip() == name:
                    found = b
                    break
            if found:
                break
        if found is None:
            print(f"  {name:8} 未找到")
            continue
        ss = found.styleSheet() or ""
        pm = found.grab()
        img = pm.toImage()
        c = img.pixelColor(img.width() // 2, img.height() // 2)
        has_color = f"#{c.red():02X}{c.green():02X}{c.blue():02X}"
        print(f"  {name:8} 中心色={has_color}  ss长度={len(ss)}  "
              f"含#4CAF50={'#4CAF50' in ss} 含F44336={'#F44336' in ss} 含FF9800={'#FF9800' in ss} "
              f"含bg-image={'background-image' in ss}")


snapshot("strip 之前（MainWindow 已自动 strip）")

# 手动再跑一次 strip，看是否为"被清掉"或"被材质盖住"
rep = strip_conflicting_stylesheets(win)
print("\nstrip 报告:", rep)
pump(6)
snapshot("strip 之后")

win.close()
