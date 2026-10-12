#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性几何探针：主窗口各页面区块的实际尺寸与父子关系。"""

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

from src.core.qt_compat.QtWidgets import QApplication, QWidget, QGroupBox, QPushButton  # noqa: E402

app = QApplication.instance() or QApplication([])
from src.utils.skeuomorphic import apply_global  # noqa: E402
apply_global(app)
from ui.widgets.main_window import MainWindow  # noqa: E402

win = MainWindow(remaining_seconds=0, license_exp_ts=0)
win.resize(1680, 1000)
win.show()


def pump(n=10):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.04)


pump(10)

pm = win.project_management_widget
print("== ProjectManagementWidget ==")
print(f"   self          geo={pm.width()}x{pm.height()}")

for child in pm.findChildren(QGroupBox):
    g = child.geometry()
    print(f"   GroupBox  {child.title()!r:22} geo={g.x()},{g.y()} {g.width()}x{g.height()}")
    for sub in child.findChildren(QWidget, options=child.findChildren(QWidget) and 0 or 0) if False else []:
        pass

print("\n== function_buttons（样本管理功能按钮） ==")
for i, b in enumerate(getattr(pm, "function_buttons", []) or []):
    g = b.geometry()
    print(f"   [{i}] {type(b).__name__} geo={g.x()},{g.y()} {g.width()}x{g.height()} "
          f"min={b.minimumWidth()}x{b.minimumHeight()} max={b.maximumWidth()}x{b.maximumHeight()} "
          f"vis={b.isVisible()} enabled={b.isEnabled()}")
    par = b.parentWidget()
    if par is not None:
        pr = par.rect()
        print(f"        parent={type(par).__name__} rect={pr.width()}x{pr.height()} "
              f"childFits={pr.contains(g)}")

print("\n== nav group 直接子控件 ==")
try:
    nav = pm.findChild(QGroupBox, "functionModulesGroup")
    if nav is not None:
        print(f"   nav geo={nav.width()}x{nav.height()} layout={type(nav.layout()).__name__ if nav.layout() else None}")
        for c in nav.findChildren(QWidget):
            if c.parentWidget() is nav:
                g = c.geometry()
                print(f"      - {type(c).__name__:16} {g.x()},{g.y()} {g.width()}x{g.height()} vis={c.isVisible()}")
except Exception as e:  # noqa: BLE001
    print("   err:", e)

print("\n== 全页面 GroupBox 溢出检查 ==")
stack = win.stacked_widget
for i in range(stack.count()):
    stack.setCurrentIndex(i)
    pump(5)
    page = stack.widget(i)
    bad = []
    for gb in page.findChildren(QGroupBox):
        if not gb.isVisible():
            continue
        pr = gb.parentWidget().rect() if gb.parentWidget() else None
        for c in gb.findChildren(QWidget):
            if c.parentWidget() is not gb or not c.isVisible():
                continue
            cg = c.geometry()
            gr = gb.rect()
            if not (gr.contains(cg) or (cg.width() <= gr.width() and cg.height() <= gr.height())):
                bad.append(f"{type(c).__name__} {cg.width()}x{cg.height()} vs group {gr.width()}x{gr.height()}")
    name = page.objectName() or type(page).__name__
    print(f"   [{i}] {name:28} groupbox溢出={len(bad)}" + ("  " + "; ".join(bad[:3]) if bad else ""))

win.close()
