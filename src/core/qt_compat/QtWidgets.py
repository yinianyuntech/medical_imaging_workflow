#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PyQt5 风格 **QtWidgets**（底层为 PyQt6）。

用法与 PyQt5 完全一致：
    from src.core.qt_compat.QtWidgets import QWidget, QMessageBox, QAction
"""

from PyQt6.QtWidgets import *  # noqa: F401,F403
from PyQt6.QtWidgets import (  # 显式导入本工程用到的类
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGraphicsView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# PyQt6 把 QAction/QShortcut 移到了 QtGui —— 这里补回 QtWidgets 命名空间
from PyQt6.QtGui import QAction, QActionGroup, QShortcut  # noqa: F401
from PyQt6.QtCore import QRect

from ._enum import compat_class

# ---- 需要「无作用域枚举」的类（PyQt5 写法 → PyQt6 枚举成员） ----
QMessageBox = compat_class(QMessageBox)          # .Yes/.No/.Ok/.warning/.AcceptRole
QDialog = compat_class(QDialog)                  # .Accepted/.Rejected
QFileDialog = compat_class(QFileDialog)          # 静态方法 + exec_
QInputDialog = compat_class(QInputDialog)
QProgressDialog = compat_class(QProgressDialog)
QFrame = compat_class(QFrame, with_exec=False)   # .StyledPanel/.Raised/.Box/.NoFrame
QLineEdit = compat_class(QLineEdit, with_exec=False)     # .Normal/.Password
QTextEdit = compat_class(QTextEdit, with_exec=False)     # .NoWrap
QTextBrowser = compat_class(QTextBrowser, with_exec=False)
QAbstractItemView = compat_class(QAbstractItemView, with_exec=False)  # .NoEditTriggers/.NoSelection
QGraphicsView = compat_class(QGraphicsView, with_exec=False)          # .AnchorUnderMouse/.ScrollHandDrag
QDialogButtonBox = compat_class(QDialogButtonBox, with_exec=False)    # .Ok/.Cancel
QTableWidget = compat_class(QTableWidget, with_exec=False)            # .SelectRows/.SingleSelection
QTreeWidget = compat_class(QTreeWidget, with_exec=False)              # .NoSelection
QHeaderView = compat_class(QHeaderView, with_exec=False)              # .Stretch/.ResizeToContents
QSizePolicy = compat_class(QSizePolicy, with_exec=False)              # .Expanding
QListWidget = compat_class(QListWidget, with_exec=False)
QMenu = compat_class(QMenu)                      # .exec_()
QApplication = compat_class(QApplication)        # .exec_() / .instance() / .clipboard()


class QDesktopWidget:  # noqa: N801 - 保持 PyQt5 命名
    """Qt6 已删除 QDesktopWidget；这里提供本工程用到的那部分能力。

    旧代码：
        desktop = QDesktopWidget()
        screen = desktop.primaryScreen()
        geo = desktop.screenGeometry(screen)
    """

    def __init__(self):
        from PyQt6.QtGui import QGuiApplication
        self._app = QGuiApplication

    def _screens(self):
        try:
            return list(self._app.screens() or [])
        except Exception:
            return []

    def screenCount(self) -> int:
        return len(self._screens())

    def primaryScreen(self) -> int:
        screens = self._screens()
        for i, s in enumerate(screens):
            try:
                if s is self._app.primaryScreen():
                    return i
            except Exception:
                continue
        return 0

    def screenGeometry(self, index: int = 0) -> QRect:
        screens = self._screens()
        if not screens:
            return QRect(0, 0, 1920, 1080)
        try:
            return screens[int(index)].geometry()
        except Exception:
            return screens[0].geometry()

    def availableGeometry(self, index: int = 0) -> QRect:
        screens = self._screens()
        if not screens:
            return QRect(0, 0, 1920, 1080)
        try:
            return screens[int(index)].availableGeometry()
        except Exception:
            return screens[0].availableGeometry()


__all__ = [n for n in dir() if not n.startswith("_")]
