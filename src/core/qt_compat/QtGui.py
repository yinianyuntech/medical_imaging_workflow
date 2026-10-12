#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PyQt5 风格 **QtGui**（底层为 PyQt6）。

用法与 PyQt5 完全一致：
    from src.core.qt_compat.QtGui import QIcon, QFont, QPalette, QColor
"""

from PyQt6.QtGui import *  # noqa: F401,F403
from PyQt6.QtGui import (  # 显式导入常用项
    QAction,
    QActionGroup,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPalette,
    QPixmap,
    QShortcut,
    QTextCursor,
    QTextCharFormat,
    QTextDocument,
)

from ._enum import compat_class

# QPalette.Base / QPalette.Text / QPalette.Button ...（ColorRole）
QPalette = compat_class(QPalette, with_exec=False)
# QFont.Bold ...（Weight）
QFont = compat_class(QFont, with_exec=False)
# QImage.Format_RGB888 ...（Format）
QImage = compat_class(QImage, with_exec=False)
# QPainter.Antialiasing ...（RenderHint）
QPainter = compat_class(QPainter, with_exec=False)
# QTextCursor.EndOfBlock / KeepAnchor ...（MoveOperation / SelectionType）
QTextCursor = compat_class(QTextCursor, with_exec=False)

__all__ = [n for n in dir() if not n.startswith("_")]
