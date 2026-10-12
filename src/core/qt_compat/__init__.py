#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qt_compat —— PyQt5 API 形状的 PyQt6 兼容层。

目的：**把 GUI 框架换成 PyQt6，但不改动业务/布局代码**。

原理：
  * `QtCore / QtGui / QtWidgets` 三个子模块从 PyQt6 `import *`，命名空间与 PyQt5 对齐；
  * `Qt` 用 `NamespaceProxy` 代理，恢复 `Qt.AlignCenter` 这类无作用域枚举；
  * 各控件类用 `compat_class()` 生成子类，把枚举成员挂成类属性，恢复
    `QMessageBox.Yes` / `QPalette.Base` 等写法，并补齐 `exec_()`；
  * `QDesktopWidget`（Qt6 已删除）由 shim 提供。

因此源码只需要把
    from PyQt5.QtWidgets import ...
改成
    from src.core.qt_compat.QtWidgets import ...
即可，其余 430 余处调用点**零改动**。
"""

from . import QtCore, QtGui, QtWidgets  # noqa: F401

__all__ = ["QtCore", "QtGui", "QtWidgets"]
