#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断：hover 事件派发为何失败；以及"同状态重复抓图"的噪声底噪是多少。"""

import os
import sys
import time
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("MIMW_SKIN", "metal")

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.core.qt_compat.QtCore import Qt, QPoint, QEvent  # noqa: E402
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QVBoxLayout, QPushButton, QLineEdit, QComboBox,
)

try:
    from PyQt6.QtTest import QTest
except Exception as e:  # noqa: BLE001
    print("QTest import failed:", e)
    QTest = None

app = QApplication([])

from src.utils import skeuo_style as st  # noqa: E402
from src.utils import skeuomorphic as sk  # noqa: E402

sk.apply_global(app)
st.install(app)


def pump(n=8):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.04)


host = QWidget()
host.resize(420, 200)
lay = QVBoxLayout(host)
btn = QPushButton("按钮")
le = QLineEdit("文本")
cb = QComboBox()
cb.addItems(["A", "B"])
for w in (btn, le, cb):
    lay.addWidget(w)
host.show()
pump(12)

print("=" * 66)
print("A. QEvent 构造能力")
for name in ("Enter", "Leave", "HoverEnter", "HoverLeave", "MouseMove"):
    try:
        t = getattr(QEvent.Type, name)
        ev = QEvent(t)
        print(f"   QEvent(Type.{name}) OK  type={ev.type()}")
    except Exception:  # noqa: BLE001
        print(f"   QEvent(Type.{name}) FAIL")
        traceback.print_exc()

print("=" * 66)
print("B. hover 序列逐步执行（定位失败点）")
try:
    QTest.mouseMove(btn, QPoint(btn.width() // 2, btn.height() // 2))
    print("   QTest.mouseMove        OK, underMouse=", btn.underMouse())
except Exception:  # noqa: BLE001
    print("   QTest.mouseMove        FAIL")
    traceback.print_exc()

try:
    btn.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
    print("   setAttribute WA_UnderMouse OK, underMouse=", btn.underMouse())
except Exception:  # noqa: BLE001
    print("   setAttribute           FAIL")
    traceback.print_exc()

try:
    btn.enterEvent(QEvent(QEvent.Type.Enter))
    print("   btn.enterEvent(Enter)  OK")
except Exception:  # noqa: BLE001
    print("   btn.enterEvent(Enter)  FAIL")
    traceback.print_exc()

try:
    ok = QApplication.sendEvent(btn, QEvent(QEvent.Type.Enter))
    print("   sendEvent(Enter)       OK, handled=", ok)
except Exception:  # noqa: BLE001
    print("   sendEvent(Enter)       FAIL")
    traceback.print_exc()

print("   underMouse 最终 =", btn.underMouse())

print("=" * 66)
print("C. 底噪：同一状态连抓两次的像素差")
btn.update()
pump(6)


def img_of(w):
    return w.grab().toImage()


def changed_frac(a, b, thr=10):
    if a.size() != b.size() or a.width() < 2:
        return -1.0
    tot = 0
    hit = 0
    for y in range(a.height()):
        for x in range(a.width()):
            ca, cb_ = a.pixelColor(x, y), b.pixelColor(x, y)
            d = max(abs(ca.red() - cb_.red()),
                    abs(ca.green() - cb_.green()),
                    abs(ca.blue() - cb_.blue()))
            tot += 1
            if d > thr:
                hit += 1
    return hit / max(1, tot)


for name, w in (("button", btn), ("line", le), ("combo", cb)):
    a = img_of(w)
    b = img_of(w)
    print(f"   {name:<8} 尺寸={a.width()}x{a.height()}  变化像素占比={changed_frac(a, b):.5%}")

print("=" * 66)
print("D. 悬停前后（WA_UnderMouse 切换）")
btn.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
btn.update()
pump(8)
before = img_of(btn)
btn.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
btn.update()
pump(8)
after = img_of(btn)
print("   button 悬停变化像素占比 =", "%.3f%%" % (changed_frac(before, after) * 100))

host.close()
