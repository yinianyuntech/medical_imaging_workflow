#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PyQt5 风格 **QtCore**（底层为 PyQt6）。

用法与 PyQt5 完全一致：
    from src.core.qt_compat.QtCore import Qt, pyqtSignal, QTimer
"""

from PyQt6.QtCore import *  # noqa: F401,F403
from PyQt6.QtCore import (  # 显式导入，避免某些版本 __all__ 缺项
    QT_VERSION_STR,
    PYQT_VERSION_STR,
    QEvent,
    QObject,
    Qt as _QtReal,
    pyqtSignal,
    pyqtSlot,
    pyqtProperty,
)

from ._enum import NamespaceProxy, compat_class

# Qt.AlignCenter / Qt.UserRole / Qt.LeftButton ... （PyQt5 写法）
Qt = NamespaceProxy(_QtReal)

# QEvent.MouseButtonPress / QEvent.Move ...（QEvent.Type）
QEvent = compat_class(QEvent, with_exec=False)

# 版本常量透传
__all__ = [n for n in dir() if not n.startswith("_")]
