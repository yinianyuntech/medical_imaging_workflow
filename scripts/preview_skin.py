#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""preview_skin.py —— 离屏渲染「光影拟物化」皮肤预览图（不弹窗）。

用法：
    python scripts/preview_skin.py [输出目录]
产物：
    <out>/skin_main_window.png    主窗口整幅
    <out>/skin_title_bar.png      标题栏局部
    <out>/skin_widgets.png        控件墙（按钮/输入框/表格/滚动条…）
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# 注意：offscreen QPA 在本构建下**没有任何字体**（font families = 0），
# 渲染出来全是方框，无法用于评审外观。因此默认使用真实 windows 平台。
if "--offscreen" in sys.argv:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("MIMW_SKIN", "metal")

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.core.qt_compat.QtCore import Qt, QTimer  # noqa: E402
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QLineEdit, QTextEdit, QComboBox, QCheckBox, QSlider,
    QProgressBar, QGroupBox, QTableWidget, QTableWidgetItem, QTabWidget,
    QListWidget, QFrame, QSizePolicy, QHeaderView,
)

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots")
)


def pump(app, n=8):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.05)


def build_widget_wall(parent):
    """控件墙：覆盖 QSS 里定义的主要控件，便于一次性检查光影效果。"""
    w = QWidget(parent)
    w.setObjectName("mimwGlass")
    root = QVBoxLayout(w)
    root.setContentsMargins(22, 18, 22, 18)
    root.setSpacing(14)

    head = QLabel("光影拟物化 · 控件样式墙（金属 / 玻璃）")
    head.setStyleSheet("font-size:17px; font-weight:bold; color:#E6EBF2;")
    root.addWidget(head)

    # 按钮行
    g1 = QGroupBox("凸起按钮（金属倒角）")
    h1 = QHBoxLayout(g1)
    for txt, en in (("主要操作", True), ("次要操作", True), ("禁用状态", False)):
        b = QPushButton(txt)
        b.setEnabled(en)
        if txt == "主要操作":
            b.setDefault(True)
        h1.addWidget(b)
    h1.addStretch()
    root.addWidget(g1)

    # 输入区
    g2 = QGroupBox("内凹输入（下沉光影）")
    grid = QGridLayout(g2)
    le = QLineEdit()
    le.setPlaceholderText("单行输入框…")
    grid.addWidget(le, 0, 0)
    cb = QComboBox()
    cb.addItems(["下拉选项 A", "下拉选项 B"])
    grid.addWidget(cb, 0, 1)
    grid.addWidget(QCheckBox("复选框（选中/未选）"), 1, 0)
    te = QTextEdit()
    te.setPlainText("多行文本区域，用于检查内凹阴影与选区高亮。")
    te.setMaximumHeight(64)
    grid.addWidget(te, 2, 0, 1, 2)
    root.addWidget(g2)

    # 滑块 / 进度
    g3 = QGroupBox("滑块与进度条")
    h3 = QHBoxLayout(g3)
    s = QSlider(Qt.Horizontal)
    s.setValue(62)
    h3.addWidget(s, 1)
    pb = QProgressBar()
    pb.setValue(47)
    h3.addWidget(pb, 1)
    root.addWidget(g3)

    # 表格 + 列表
    g4 = QGroupBox("表格 / 列表（玻璃面 + 金属表头）")
    h4 = QHBoxLayout(g4)
    t = QTableWidget(4, 3)
    t.setHorizontalHeaderLabels(["样本", "面积", "置信度"])
    for r in range(4):
        for c, v in enumerate([f"S-{r+1}", f"{12.4 + r:.1f}", f"{0.81 + r*0.03:.2f}"]):
            t.setItem(r, c, QTableWidgetItem(v))
    t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
    t.setAlternatingRowColors(True)
    h4.addWidget(t, 3)
    lw = QListWidget()
    for i in range(6):
        lw.addItem(f"项目条目 {i+1}")
    lw.setCurrentRow(2)
    h4.addWidget(lw, 2)
    root.addWidget(g4)

    # 标签页
    tabs = QTabWidget()
    for name in ("概览", "参数", "日志"):
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.addWidget(QLabel(f"{name} 页内容"))
        pl.addWidget(QPushButton("页内按钮"))
        pl.addStretch()
        tabs.addTab(page, name)
    root.addWidget(tabs, 1)
    return w


def main() -> int:
    app = QApplication.instance() or QApplication([])

    from src.utils.skeuomorphic import apply_global, SKIN_ENABLED
    apply_global(app)
    try:
        from src.utils.skeuo_style import install as install_skeuo_style
        install_skeuo_style(app)
    except Exception as _e:
        print("skeuo style install failed:", _e)
    print("skin enabled:", SKIN_ENABLED)

    os.makedirs(OUT, exist_ok=True)

    # ---------- 1) 控件墙 ----------
    wall = QWidget()
    wall.setWindowTitle("widgets")
    wall.resize(940, 860)
    lay = QVBoxLayout(wall)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(build_widget_wall(wall))
    wall.show()
    pump(app, 10)
    p1 = os.path.join(OUT, "skin_widgets.png")
    wall.grab().save(p1)
    print("saved:", p1)
    wall.hide()
    wall.close()

    # ---------- 2) 主窗口 ----------
    try:
        from ui.widgets.main_window import MainWindow
        win = MainWindow(remaining_seconds=0, license_exp_ts=0)
        win.resize(1680, 1000)
        win.show()
        pump(app, 14)
        p2 = os.path.join(OUT, "skin_main_window.png")
        win.grab().save(p2)
        print("saved:", p2)

        try:
            p3 = os.path.join(OUT, "skin_title_bar.png")
            win._title_frame.grab().save(p3)
            print("saved:", p3)
        except Exception as e:  # noqa: BLE001
            print("title bar grab failed:", e)
        win.hide()
        win.close()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("main window preview failed:", e)
        return 1

    QTimer.singleShot(0, app.quit)
    print("PREVIEW OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
