#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""表头悬停定点取证：用真实鼠标移到表头上，打印绘制时刻的 state 位。"""

import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("MIMW_SKIN", "metal")

LOG = open(os.path.join(os.environ.get("TEMP", "."), "header_probe.txt"),
           "w", encoding="utf-8")


def say(*a):
    LOG.write(" ".join(str(x) for x in a) + "\n")
    LOG.flush()


from src.core.qt_compat.QtCore import Qt, QPoint  # noqa: E402
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
)

user32 = ctypes.windll.user32


def set_cursor(x, y):
    user32.SetCursorPos(int(x), int(y))


def hwnd_at(x, y):
    p = wt.POINT(int(x), int(y))
    h = user32.WindowFromPoint(p)
    return (user32.GetAncestor(h, 2) or h) if h else 0


app = QApplication([])
from src.utils import skeuo_style as st  # noqa: E402
from src.utils import skeuomorphic as sk  # noqa: E402

sk.apply_global(app)
st.install(app)

SEEN = []


def wrap(name, key):
    orig = getattr(st.SkeuomorphicStyle, name)

    def patched(self, option, painter, widget):
        try:
            S = st.QStyle.StateFlag
            bits = []
            for f in ("State_MouseOver", "State_Enabled", "State_Sunken",
                      "State_On", "State_Selected", "State_HasFocus"):
                if hasattr(S, f) and (option.state & getattr(S, f)):
                    bits.append(f.replace("State_", ""))
            r = option.rect
            SEEN.append(f"[{key}] bits={bits} rect=({r.x()},{r.y()},{r.width()}x{r.height()}) "
                        f"underMouse={widget.underMouse() if widget is not None else None}")
        except Exception as e:  # noqa: BLE001
            SEEN.append(f"[{key}] ERR {e}")
        return orig(self, option, painter, widget)

    setattr(st.SkeuomorphicStyle, name, patched)


wrap("_header", "header")
wrap("_button", "button")

win = QWidget()
win.setWindowTitle("表头取证")
win.resize(520, 260)
win.move(40, 40)
lay = QVBoxLayout(win)
tbl = QTableWidget(3, 3)
tbl.setHorizontalHeaderLabels(["列A", "列B", "列C"])
for r in range(3):
    for c in range(3):
        tbl.setItem(r, c, QTableWidgetItem(f"{r}{c}"))
lay.addWidget(tbl)
win.show()
win.setWindowFlag(Qt.WindowStaysOnTopHint, True)
win.show()
win.raise_()
win.activateWindow()


def pump(n=12):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.04)


pump(24)
hwnd = int(win.winId())
user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
pump(14)

dpr = float(win.devicePixelRatioF() or 1.0)
hdr = tbl.horizontalHeader()
pos = hdr.mapToGlobal(QPoint(hdr.width() // 3, hdr.height() // 2))
x, y = int(pos.x() * dpr), int(pos.y() * dpr)

say("=" * 70)
say(f"窗口 dpr={dpr}  hwnd={hwnd}")
say(f"表头几何: {hdr.width()}x{hdr.height()}  目标物理坐标=({x},{y})")
say(f"hwnd_at=({hwnd_at(x,y)}) 一致={hwnd_at(x,y)==hwnd}")

say("-" * 70)
say("步骤 1：光标移到别处（远离表头）")
p2 = win.mapToGlobal(QPoint(20, win.height() - 20))
set_cursor(int(p2.x() * dpr), int(p2.y() * dpr))
pump(16)
SEEN.clear()
hdr.viewport().update()
tbl.viewport().update()
pump(12)
say(f"  表头绘制次数={len(SEEN)}")
for s in SEEN[:4]:
    say("   ", s)

say("-" * 70)
say("步骤 2：光标移到表头正上方（真实 WM_MOUSEMOVE）")
set_cursor(x, y)
time.sleep(0.5)
pump(24)
SEEN.clear()
hdr.viewport().update()
hdr.update()
tbl.viewport().update()
pump(16)
say(f"  表头绘制次数={len(SEEN)}")
for s in SEEN[:6]:
    say("   ", s)

say("-" * 70)
say("步骤 3：光标在表头上再抖动 1px（强制新的 WM_MOUSEMOVE）")
set_cursor(x + 1, y)
time.sleep(0.35)
pump(20)
SEEN.clear()
hdr.update()
pump(14)
say(f"  表头绘制次数={len(SEEN)}")
for s in SEEN[:6]:
    say("   ", s)

say("-" * 70)
say("步骤 4：表头 hover 相关 Qt 内部状态")
for attr in ("hover", "hoverIndex"):
    try:
        # QHeaderView 私有状态无法直接读，改用 PyQt 可用的等效信号
        say(f"  hasattr(hdr, {attr!r}) = {hasattr(hdr, attr)}")
    except Exception as e:  # noqa: BLE001
        say(f"  {attr} -> {e}")
try:
    say("  hdr.underMouse() =", hdr.underMouse())
except Exception as e:  # noqa: BLE001
    say("  underMouse 失败:", e)

win.close()
LOG.close()
print("OK -> %TEMP%/header_probe.txt")
