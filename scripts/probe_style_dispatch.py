#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针：确认三维引擎对**全部控件**的接管是否生效。"""

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

from src.core.qt_compat.QtCore import Qt  # noqa: E402
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton,
    QLineEdit, QLabel, QComboBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QScrollBar, QSlider, QCheckBox, QRadioButton, QTextEdit,
)

app = QApplication.instance() or QApplication([])
from src.utils.skeuomorphic import apply_global  # noqa: E402
apply_global(app)
from src.utils.skeuo_style import install, SkeuomorphicStyle  # noqa: E402

print("install:", install(app))

w = QWidget()
w.resize(620, 560)
lay = QVBoxLayout(w)

gb = QGroupBox("分组框(面板)")
gl = QVBoxLayout(gb)
gl.addWidget(QPushButton("按钮"))
gl.addWidget(QLineEdit("输入框"))
cb = QComboBox()
cb.addItems(["下拉项 A", "下拉项 B", "下拉项 C"])
gl.addWidget(cb)
row = QHBoxLayout()
row.addWidget(QCheckBox("勾选框"))
row.addWidget(QRadioButton("单选钮"))
gl.addLayout(row)
gl.addWidget(QSlider(Qt.Horizontal))
sc = QScrollBar(Qt.Horizontal)
sc.setRange(0, 100)
sc.setValue(40)
gl.addWidget(sc)
gl.addWidget(QTextEdit("文本域"))
lay.addWidget(gb)

tabs = QTabWidget()
for nm in ("标签一", "标签二", "标签三"):
    p = QWidget()
    QVBoxLayout(p).addWidget(QLabel(nm + " 内容"))
    tabs.addTab(p, nm)
lay.addWidget(tabs)

tb = QTableWidget(3, 3)
tb.setHorizontalHeaderLabels(["列A", "列B", "列C"])
for r in range(3):
    for c in range(3):
        tb.setItem(r, c, QTableWidgetItem(f"{r}{c}"))
lay.addWidget(tb)

w.show()
for _ in range(14):
    app.processEvents()
    time.sleep(0.04)

print("接管命中计数:", SkeuomorphicStyle.hits)
if SkeuomorphicStyle.last_error:
    print("!!! 引擎内部异常:\n", SkeuomorphicStyle.last_error)
else:
    print("无引擎内部异常")

out = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots", "probe_style.png")
w.grab().save(out)
print("saved:", os.path.abspath(out))
