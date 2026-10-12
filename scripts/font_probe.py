#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断离屏渲染的中文字形问题。"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.core.qt_compat.QtCore import Qt  # noqa: E402
from src.core.qt_compat.QtGui import QFont, QFontDatabase, QFontMetrics  # noqa: E402
from src.core.qt_compat.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout  # noqa: E402

app = QApplication.instance() or QApplication([])

print("platform:", app.platformName())
fams = QFontDatabase.families()
print("font families:", len(fams))
for want in ("Microsoft YaHei", "Microsoft YaHei UI", "SimSun", "SimHei", "Segoe UI", "Arial"):
    print(f"  {want!r} present:", want in fams)

for fam in ("Microsoft YaHei", "SimHei", "Segoe UI", None):
    f = QFont(fam) if fam else app.font()
    fm = QFontMetrics(f)
    txt = "医疗数据科学 中文渲染 ABC 123"
    print(f"  fam={fam!r:22} inFont(医)={QFontDatabase.families() and QFontMetrics(f).inFont('医')} width={fm.horizontalAdvance(txt)}")

# 实际渲染对比
w = QWidget()
w.resize(760, 220)
lay = QVBoxLayout(w)
for fam in ("Microsoft YaHei", "SimHei", None):
    lb = QLabel("医疗数据科学 中文渲染 ABC 123  ← " + str(fam))
    if fam:
        lb.setFont(QFont(fam, 15))
    else:
        f = lb.font()
        f.setPointSize(15)
        lb.setFont(f)
    lay.addWidget(lb)
w.show()
for _ in range(10):
    app.processEvents()
out = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots", "font_probe.png")
w.grab().save(out)
print("saved:", os.path.abspath(out))
