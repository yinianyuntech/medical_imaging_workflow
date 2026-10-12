#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在**绘制时刻**打印 option.state，确认 State_MouseOver 是否真的传进引擎。

这是决定性的：不再推测，直接看 Qt 交给我们的是什么。
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("MIMW_SKIN", "metal")

LOG = open(os.path.join(os.environ.get("TEMP", "."), "state_probe.txt"),
           "w", encoding="utf-8")


def say(*a):
    LOG.write(" ".join(str(x) for x in a) + "\n")
    LOG.flush()


from src.core.qt_compat.QtCore import Qt, QPoint, QEvent  # noqa: E402
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QVBoxLayout, QPushButton, QCheckBox, QLineEdit,
)

from PyQt6.QtTest import QTest  # noqa: E402

app = QApplication([])

from src.utils import skeuo_style as st  # noqa: E402
from src.utils import skeuomorphic as sk  # noqa: E402

sk.apply_global(app)
st.install(app)

# ---------- 打点：包装 _button / _checkbox / _well ----------
CALLS = {"n": 0}


def wrap(name, key):
    orig = getattr(st.SkeuomorphicStyle, name)

    def patched(self, option, painter, widget):
        if CALLS["n"] < 60:
            CALLS["n"] += 1
            try:
                S = st.QStyle.StateFlag
                bits = []
                for f in ("State_MouseOver", "State_Enabled", "State_Sunken",
                          "State_On", "State_HasFocus", "State_Active"):
                    try:
                        v = getattr(S, f)
                        if option.state & v:
                            bits.append(f.replace("State_", ""))
                    except Exception as e:  # noqa: BLE001
                        bits.append(f"<{f}:ERR {e}>")
                um = None
                try:
                    um = widget.underMouse() if widget is not None else None
                except Exception:
                    um = "ERR"
                say(f"[{key}] bits={bits} "
                    f"underMouse={um} type={type(widget).__name__}")
            except Exception:  # noqa: BLE001
                import traceback
                say(f"[{key}] probe error:\n{traceback.format_exc()}")
        return orig(self, option, painter, widget)

    setattr(st.SkeuomorphicStyle, name, patched)


try:
    say("QStyle.StateFlag 是否有 State_MouseOver:",
        hasattr(st.QStyle.StateFlag, "State_MouseOver"))
    if hasattr(st.QStyle.StateFlag, "State_MouseOver"):
        say("  值 =", st.QStyle.StateFlag.State_MouseOver.value)
except Exception as e:  # noqa: BLE001
    say("检查 StateFlag 失败:", e)

wrap("_button", "button")
wrap("_checkbox", "check")
wrap("_well", "well")

host = QWidget()
host.resize(360, 220)
lay = QVBoxLayout(host)
btn = QPushButton("主要操作")
chk = QCheckBox("勾选框")
le = QLineEdit("文本")
for w in (btn, chk, le):
    lay.addWidget(w)
host.show()
for _ in range(14):
    app.processEvents()
    time.sleep(0.04)


def pump(n=10):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.04)


say("=" * 70)
say("A) 常态抓图（WA_UnderMouse=False）")
btn.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
btn.update()
pump()
CALLS["n"] = 0
img_a = btn.grab().toImage()
say("  抓图完成")

say("=" * 70)
say("B) 悬停抓图（WA_UnderMouse=True）")
btn.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
QApplication.sendEvent(btn, QEvent(QEvent.Type.Enter))
btn.update()
pump()
CALLS["n"] = 0
img_b = btn.grab().toImage()
say("  抓图完成")

say("=" * 70)
say("C) 像素差")
mx = 0
n4 = 0
for y in range(img_a.height()):
    for x in range(img_a.width()):
        ca, cb = img_a.pixelColor(x, y), img_b.pixelColor(x, y)
        d = max(abs(ca.red() - cb.red()), abs(ca.green() - cb.green()),
                abs(ca.blue() - cb.blue()))
        mx = max(mx, d)
        if d > 4:
            n4 += 1
say(f"  最大通道差={mx}  >4 像素={n4} / {img_a.width()*img_a.height()}")

say("=" * 70)
say("D) 引擎自报错误")
try:
    say("  last_error =", st.SkeuomorphicStyle.last_error)
except Exception as e:  # noqa: BLE001
    say("  读取失败:", e)
try:
    say("  hits =", dict(st.SkeuomorphicStyle.hits))
except Exception as e:  # noqa: BLE001
    say("  读取 hits 失败:", e)

say("=" * 70)
say("E) 模拟「按下」对比（应当有差异，用来证明 probe 链路本身有效）")
btn.update()
pump(6)
img_c = btn.grab().toImage()
QTest.mousePress(btn, Qt.MouseButton.LeftButton,
                 pos=QPoint(btn.width() // 2, btn.height() // 2))
btn.update()
pump(10)
CALLS["n"] = 0
img_d = btn.grab().toImage()
QTest.mouseRelease(btn, Qt.MouseButton.LeftButton,
                   pos=QPoint(btn.width() // 2, btn.height() // 2))
mx2 = 0
for y in range(img_c.height()):
    for x in range(img_c.width()):
        ca, cb = img_c.pixelColor(x, y), img_d.pixelColor(x, y)
        d = max(abs(ca.red() - cb.red()), abs(ca.green() - cb.green()),
                abs(ca.blue() - cb.blue()))
        mx2 = max(mx2, d)
say(f"  按下 最大通道差={mx2}")

host.close()
LOG.close()
print("OK -> %TEMP%/state_probe.txt")
