#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精确测量：状态变化到底是"完全没画"还是"画了但很轻微"。

关键区分：
  * 最大通道差 == 0        → 真的没画（缺失交互反馈，真缺陷）
  * 最大通道差 1..p        → 画了，只是幅度小（需要判断是否够"看得出"）

用 sendEvent 派发 Enter/Leave（PyQt6 里 enterEvent() 需要 QEnterEvent，直接调会 TypeError）。
"""

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

from src.core.qt_compat.QtCore import Qt, QPoint, QEvent  # noqa: E402
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QComboBox, QCheckBox, QRadioButton, QSlider, QScrollBar, QTabWidget, QLabel,
)

from PyQt6.QtTest import QTest  # noqa: E402

app = QApplication([])

from src.utils import skeuo_style as st  # noqa: E402
from src.utils import skeuomorphic as sk  # noqa: E402

sk.apply_global(app)
st.install(app)


def pump(n=8):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.04)


def img_of(w):
    return w.grab().toImage()


def measure(a, b):
    """返回 (最大通道差, 超4的像素数, 超10的像素数, 总像素)。"""
    if a.size() != b.size() or a.width() < 2:
        return -1, 0, 0, 0
    mx = 0
    n4 = n10 = 0
    tot = a.width() * a.height()
    for y in range(a.height()):
        for x in range(a.width()):
            ca, cb = a.pixelColor(x, y), b.pixelColor(x, y)
            d = max(abs(ca.red() - cb.red()),
                    abs(ca.green() - cb.green()),
                    abs(ca.blue() - cb.blue()))
            if d > mx:
                mx = d
            if d > 4:
                n4 += 1
            if d > 10:
                n10 += 1
    return mx, n4, n10, tot


host = QWidget()
host.resize(500, 430)
lay = QVBoxLayout(host)

btn = QPushButton("主要操作")
le = QLineEdit("文本输入")
cb = QComboBox()
cb.addItems(["A", "B"])
chk = QCheckBox("勾选框")
rad = QRadioButton("单选钮")
sld = QSlider(Qt.Horizontal)
sld.setRange(0, 100)
sld.setValue(45)
scr = QScrollBar(Qt.Horizontal)
scr.setRange(0, 100)
scr.setValue(40)
tabs = QTabWidget()
for nm in ("标签一", "标签二"):
    p = QWidget()
    QVBoxLayout(p).addWidget(QLabel(nm))
    tabs.addTab(p, nm)
for w in (btn, le, cb, chk, rad, sld, scr, tabs):
    lay.addWidget(w)
host.show()
pump(14)


def enter(w):
    w.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
    QApplication.sendEvent(w, QEvent(QEvent.Type.Enter))
    w.update()
    pump(8)


def leave(w):
    w.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
    QApplication.sendEvent(w, QEvent(QEvent.Type.Leave))
    w.update()
    pump(8)


print("=" * 78)
print("精确状态测量（最大通道差 == 0 表示真的没画）")
print("=" * 78)
print(f"{'控件':<10} {'状态':<12} {'最大差':>6} {'>4像素':>9} {'>10像素':>9} {'总像素':>9}  判定")
print("-" * 78)

ROWS = []


def case(name, w, label, setup, teardown):
    leave(w)
    if isinstance(w, (QLineEdit,)):
        w.clearFocus()
    w.update()
    pump(10)
    a = img_of(w)
    try:
        setup()
        pump(10)
        b = img_of(w)
        mx, n4, n10, tot = measure(a, b)
        if mx <= 0:
            verdict = "✗ 完全没画"
        elif mx <= 4:
            verdict = "△ 极轻微"
        elif n4 < 20:
            verdict = "△ 轻微"
        else:
            verdict = "✓ 可见"
        ROWS.append((name, label, mx, n4, n10, tot, verdict))
    except Exception as e:  # noqa: BLE001
        ROWS.append((name, label, -1, 0, 0, 0, f"ERR {e}"))
    finally:
        try:
            teardown()
            pump(6)
        except Exception:
            pass


# ---- 按钮 ----
case("button", btn, "hover", lambda: enter(btn), lambda: leave(btn))
case("button", btn, "pressed",
     lambda: (QTest.mousePress(btn, Qt.MouseButton.LeftButton,
                               pos=QPoint(btn.width() // 2, btn.height() // 2)), btn.update()),
     lambda: (QTest.mouseRelease(btn, Qt.MouseButton.LeftButton,
                                 pos=QPoint(btn.width() // 2, btn.height() // 2)), btn.update()))
case("button", btn, "disabled", lambda: btn.setEnabled(False), lambda: btn.setEnabled(True))

# ---- 输入框 ----
case("line", le, "focus", lambda: le.setFocus(), lambda: le.clearFocus())
case("line", le, "hover", lambda: enter(le), lambda: leave(le))
case("line", le, "disabled", lambda: le.setEnabled(False), lambda: le.setEnabled(True))

# ---- 下拉框 ----
case("combo", cb, "hover", lambda: enter(cb), lambda: leave(cb))
case("combo", cb, "disabled", lambda: cb.setEnabled(False), lambda: cb.setEnabled(True))

# ---- 勾选 / 单选 ----
case("check", chk, "checked", lambda: chk.setChecked(True), lambda: chk.setChecked(False))
case("check", chk, "hover", lambda: enter(chk), lambda: leave(chk))
case("check", chk, "disabled", lambda: chk.setEnabled(False), lambda: chk.setEnabled(True))
case("radio", rad, "checked", lambda: rad.setChecked(True), lambda: rad.setChecked(False))
case("radio", rad, "hover", lambda: enter(rad), lambda: leave(rad))

# ---- 滑杆 ----
case("slider", sld, "hover", lambda: enter(sld), lambda: leave(sld))
case("slider", sld, "disabled", lambda: sld.setEnabled(False), lambda: sld.setEnabled(True))

# ---- 滚动条 ----
case("scroll", scr, "hover", lambda: enter(scr), lambda: leave(scr))

# ---- 标签页 ----
case("tabs", tabs, "select-2", lambda: tabs.setCurrentIndex(1), lambda: tabs.setCurrentIndex(0))

for r in ROWS:
    name, label, mx, n4, n10, tot, verdict = r
    pct = f"{n4 / tot:.3%}" if tot else "-"
    print(f"{name:<10} {label:<12} {mx:>6} {n4:>9} {n10:>9} {tot:>9}  {verdict}   (>4 占比 {pct})")

print("-" * 78)
missing = [r for r in ROWS if r[2] <= 0]
light = [r for r in ROWS if 0 < r[2] <= 4]
print(f"合计 {len(ROWS)} 项：完全没画 {len(missing)}，极轻微 {len(light)}")
for r in missing:
    print(f"   ✗ 完全没画: {r[0]} / {r[1]}")
for r in light:
    print(f"   △ 极轻微  : {r[0]} / {r[1]}  最大差={r[2]}")

host.close()
