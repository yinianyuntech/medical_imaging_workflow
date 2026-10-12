#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""preview_icons.py —— 离屏渲染应用图标总览（深/浅两套主题）。

用法：
    python scripts/preview_icons.py [输出目录]

产物：
    <out>/icons_dark.png    深色主题下的全部图标（16/20/28px 三档 + 按钮实测行）
    <out>/icons_light.png   浅色主题下的全部图标
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

from src.core.qt_compat.QtCore import Qt  # noqa: E402
from src.core.qt_compat.QtGui import QColor, QFont, QPainter, QPixmap  # noqa: E402
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
)

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots")
)

CELL_W, CELL_H = 132, 44
COLS = 8


def pump(app, n=6):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.02)


def render_theme(app, theme: str) -> str:
    os.environ["MIMW_THEME"] = theme
    import importlib
    import src.utils.app_icons as ai
    importlib.reload(ai)
    from src.utils.skeuomorphic import current_palette
    pal = current_palette()

    names = ai.names()
    rows = (len(names) + COLS - 1) // COLS
    W = COLS * CELL_W + 40
    H = rows * CELL_H + 220
    pm = QPixmap(W, H)
    pm.fill(QColor(pal.s800 if theme == "dark" else pal.s700))

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.fillRect(0, 0, W, 44, QColor(pal.s900))

    # 标题
    f = QFont("Bahnschrift")
    f.setPointSizeF(15)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(pal.chip_text))
    p.drawText(20, 30, f"app_icons · {theme} · {len(names)} icons")

    # 图标网格
    body_font = QFont("Cascadia Mono")
    body_font.setPointSizeF(8.5)
    for i, name in enumerate(names):
        r, c = divmod(i, COLS)
        x, y = 20 + c * CELL_W, 60 + r * CELL_H
        src = QPixmap(ai.pixmap(name, "text", 20))
        p.drawPixmap(x, y, src)
        src2 = QPixmap(ai.pixmap(name, "accent", 16))
        p.drawPixmap(x + 28, y + 2, src2)
        src3 = QPixmap(ai.pixmap(name, "chip", 16))
        p.drawPixmap(x + 50, y + 2, src3)
        p.setFont(body_font)
        p.setPen(QColor(pal.text_dim))
        p.drawText(x + 74, y + 17, name)

    # 按钮实测行（引擎接管后的真实按钮上的图标）
    from src.utils.skeuo_style import SkeuomorphicStyle  # noqa: F401
    y0 = 60 + rows * CELL_H + 24
    x = 20
    for label, nm, role, kind in (
        ("新建项目", "plus", "text", "normal"),
        ("删除勾选", "trash", "text", "normal"),
        ("刷新", "refresh", "text", "normal"),
        ("开始处理", "play", "on", "accent"),
        ("保存结果", "save", "on", "success"),
        ("删除样本", "trash", "on", "danger"),
        ("导出数据", "export", "text", "normal"),
        ("提示词修改", "edit", "text", "normal"),
    ):
        btn = QPushButton(label)
        ai.apply_icon(btn, nm, role, 16)
        btn.resize(118, 32)
        btn.setFixedSize(118, 32)
        bk = {"accent": pal.accent, "success": "#3E9E5B", "danger": "#C0504D"}.get(kind)
        if bk:
            btn.setStyleSheet(
                f"QPushButton{{background-color:{bk};color:#FFFFFF;"
                f"border-radius:5px;font-weight:600;}}")
        btn.move(x, y0)
        btn.show()
        pump(app, 3)
        p.drawPixmap(x, y0, btn.grab())
        btn.hide()
        x += 128
    p.end()

    pth = os.path.join(OUT, f"icons_{theme}.png")
    pm.save(pth)
    print("saved:", pth)
    return pth


def main() -> int:
    app = QApplication.instance() or QApplication([])
    from src.utils.skeuomorphic import apply_global
    apply_global(app)
    try:
        from src.utils.skeuo_style import install as install_skeuo_style
        install_skeuo_style(app)
    except Exception as e:  # noqa: BLE001
        print("skeuo style install failed:", e)

    os.makedirs(OUT, exist_ok=True)
    render_theme(app, "dark")
    render_theme(app, "light")
    print("PREVIEW ICONS OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
