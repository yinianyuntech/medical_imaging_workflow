#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qt_compat 自检：验证 PyQt5 写法在 PyQt6 兼容层下全部可用。"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.core.qt_compat.QtCore import (  # noqa: E402
    Qt, QEvent, QTimer, pyqtSignal, QSize, QPoint, QObject,
)
from src.core.qt_compat.QtGui import (  # noqa: E402
    QPalette, QFont, QPainter, QImage, QTextCursor, QIcon, QColor, QPixmap,
)
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QMessageBox, QDialog, QFrame, QFileDialog, QLineEdit,
    QTextEdit, QSizePolicy, QHeaderView, QTableWidget, QDialogButtonBox,
    QDesktopWidget, QAction, QMenu, QGraphicsView, QAbstractItemView, QTreeWidget,
    QMainWindow, QVBoxLayout, QLabel, QPushButton, QTabWidget, QStackedWidget,
    QListWidget, QComboBox, QCheckBox, QGroupBox, QSplitter, QScrollArea, QSlider,
    QGridLayout, QHBoxLayout, QProgressDialog, QInputDialog, QTextBrowser,
    QTreeWidgetItem, QListWidgetItem, QTableWidgetItem, QShortcut, QActionGroup,
)

RESULTS = []

# QApplication 必须最先创建：Qt 不允许在它之前创建 QObject/QWidget（否则原生崩溃）
app = QApplication.instance() or QApplication([])


def chk(label, fn):
    try:
        fn()
        RESULTS.append((label, True, ""))
    except Exception as e:  # noqa: BLE001
        RESULTS.append((label, False, f"{type(e).__name__}: {e}"))


# ---- Qt 命名空间（无作用域枚举） ----
chk("Qt.AlignCenter", lambda: Qt.AlignCenter)
chk("Qt.AlignTop", lambda: Qt.AlignTop)
chk("Qt.UserRole", lambda: Qt.UserRole)
chk("Qt.LeftButton", lambda: Qt.LeftButton)
chk("Qt.Checked", lambda: Qt.Checked)
chk("Qt.CustomContextMenu", lambda: Qt.CustomContextMenu)
chk("Qt.AlignmentFlag.AlignCenter (scoped)", lambda: Qt.AlignmentFlag.AlignCenter)
chk("Qt.AlignCenter|AlignTop", lambda: Qt.AlignCenter | Qt.AlignTop)
chk("Qt.AlignCenter == scoped", lambda: (_ for _ in ()).throw(AssertionError())
    if Qt.AlignCenter != Qt.AlignmentFlag.AlignCenter else None)
chk("int(Qt.AlignCenter)", lambda: int(Qt.AlignCenter))

# ---- QtCore ----
chk("QEvent.MouseButtonPress", lambda: QEvent.MouseButtonPress)
chk("QEvent.Move / Resize / Show", lambda: (QEvent.Move, QEvent.Resize, QEvent.Show))
chk("pyqtSignal", lambda: pyqtSignal(str))
chk("QTimer.singleShot callable", lambda: QTimer.singleShot)

# ---- QtGui ----
chk("QPalette.Base/Text/Button", lambda: (QPalette.Base, QPalette.Text, QPalette.Button))
chk("QPalette.Highlight/Window/Base", lambda: (QPalette.Highlight, QPalette.Window, QPalette.Base))
chk("QFont.Bold", lambda: QFont.Bold)
chk("QPainter.Antialiasing", lambda: QPainter.Antialiasing)
chk("QImage.Format_RGB888 / Format_Grayscale8", lambda: (QImage.Format_RGB888, QImage.Format_Grayscale8))
chk("QTextCursor.EndOfBlock/KeepAnchor", lambda: (QTextCursor.EndOfBlock, QTextCursor.KeepAnchor))

# ---- QtWidgets enums ----
chk("QMessageBox.Yes/No/Ok/NoButton", lambda: (QMessageBox.Yes, QMessageBox.No, QMessageBox.Ok, QMessageBox.NoButton))
chk("QMessageBox.Retry", lambda: QMessageBox.Retry)
chk("QMessageBox.Yes|No", lambda: QMessageBox.Yes | QMessageBox.No)
chk("QMessageBox.AcceptRole/RejectRole", lambda: (QMessageBox.AcceptRole, QMessageBox.RejectRole))
chk("QMessageBox.warning callable", lambda: QMessageBox.warning)
chk("QMessageBox.question callable", lambda: QMessageBox.question)
chk("QDialog.Accepted/Rejected", lambda: (QDialog.Accepted, QDialog.Rejected))
chk("QFrame.StyledPanel|Raised", lambda: QFrame.StyledPanel | QFrame.Raised)
chk("QFrame.Box / NoFrame", lambda: (QFrame.Box, QFrame.NoFrame))
chk("QFileDialog.getExistingDirectory", lambda: QFileDialog.getExistingDirectory)
chk("QFileDialog.getOpenFileName", lambda: QFileDialog.getOpenFileName)
chk("QLineEdit.Normal/Password/PasswordEchoOnEdit", lambda: (QLineEdit.Normal, QLineEdit.Password, QLineEdit.PasswordEchoOnEdit))
chk("QTextEdit.NoWrap", lambda: QTextEdit.NoWrap)
chk("QAbstractItemView.NoEditTriggers/NoSelection", lambda: (QAbstractItemView.NoEditTriggers, QAbstractItemView.NoSelection))
chk("QGraphicsView.AnchorUnderMouse/ScrollHandDrag", lambda: (QGraphicsView.AnchorUnderMouse, QGraphicsView.ScrollHandDrag))
chk("QDialogButtonBox.Ok/Cancel", lambda: (QDialogButtonBox.Ok, QDialogButtonBox.Cancel))
chk("QTableWidget.SelectRows/SingleSelection", lambda: (QTableWidget.SelectRows, QTableWidget.SingleSelection))
chk("QTreeWidget.NoSelection", lambda: QTreeWidget.NoSelection)
chk("QHeaderView.ResizeToContents/Stretch", lambda: (QHeaderView.ResizeToContents, QHeaderView.Stretch))
chk("QSizePolicy.Expanding", lambda: QSizePolicy.Expanding)
chk("QAction via QtWidgets", lambda: QAction("x", None))
chk("QAction with parent widget", lambda: QAction("y", QWidget()))
chk("QShortcut via QtWidgets", lambda: QShortcut)

# ---- Qt6 移除项 shim ----
chk("QDesktopWidget() ctor", lambda: QDesktopWidget())
dw = QDesktopWidget()
chk("QDesktopWidget.primaryScreen()", lambda: dw.primaryScreen())
chk("QDesktopWidget.screenGeometry()", lambda: dw.screenGeometry(dw.primaryScreen()))
chk("QDesktopWidget.availableGeometry()", lambda: dw.availableGeometry(0))

# ---- 真实运行时 ----
# ⚠️ 下面两条测试**故意不再只是"取一下属性"**。
#    历史上它们写成 `lambda: app.exec_` / `lambda: dlg.exec_` —— 只断言属性**存在**，
#    而兼容层当时把"已绑定到类、且非描述符"的 builtin 塞进了命名空间：
#    属性确实存在、取值也不报错，于是 58 条测试全绿，
#    但真实调用 `dialog.exec_()` 会抛
#    `exec(self): first argument of unbound method must have type 'QDialog'`
#    （新建项目 / 首启向导 / 全部 29 处 exec_() 调用都失效）。
#    教训：**"属性存在"不等于"能正确调用"** —— 必须验证绑定与真实调用。
chk("QApplication.exec_ 存在且可调用", lambda: None if callable(app.exec_) else
    (_ for _ in ()).throw(AssertionError("app.exec_ 不可调用")))
chk("QApplication.instance()", lambda: QApplication.instance())
chk("QApplication.clipboard()", lambda: QApplication.clipboard())


def _app_exec_really_runs():
    QTimer.singleShot(0, app.quit)
    rc = app.exec_()
    if rc is None:
        raise AssertionError("app.exec_() 未返回退出码")


chk("QApplication.exec_() 真的能跑事件循环（0ms 后 quit）", _app_exec_really_runs)


def _exec_binding_all_classes():
    """每个 compat 类的 `.exec_` 在**实例级访问**时必须绑定到实例。"""
    bad = []
    for cls in (QDialog, QMessageBox, QFileDialog, QInputDialog,
                QProgressDialog, QMenu):
        if not hasattr(cls, "exec_"):
            bad.append(f"{cls.__name__}: 无 exec_")
            continue
        try:
            inst = cls()
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{cls.__name__}(): 构造失败 {exc}")
            continue
        e = getattr(inst, "exec_", None)
        if e is None:
            bad.append(f"{cls.__name__}: 实例上取不到 exec_")
            continue
        owner = getattr(e, "__self__", None)
        if owner is not inst:
            bad.append(f"{cls.__name__}.exec_ 绑定到了 {owner!r}（应为实例）")
    if bad:
        raise AssertionError("; ".join(bad))


chk("所有 compat 类的 .exec_ 都绑定到**实例**（而非类）", _exec_binding_all_classes)


def _dialog_subclass_exec_runs():
    """真实调用：子类化 compat QDialog 后 exec_ 必须能进/出模态循环。"""
    class _D(QDialog):
        pass

    d = _D()
    QTimer.singleShot(0, d.reject)
    r = d.exec_()
    if r != QDialog.Rejected:
        raise AssertionError(f"exec_ 返回 {r}，期望 QDialog.Rejected")


chk("QDialog 子类 .exec_() 真的能调用并返回", _dialog_subclass_exec_runs)


def _msgbox_exec_runs():
    box = QMessageBox()
    box.setText("自检")
    box.setStandardButtons(QMessageBox.Ok)
    QTimer.singleShot(0, box.accept)
    r = box.exec_()
    if r != QDialog.Accepted:
        raise AssertionError(f"exec_ 返回 {r}，期望 QDialog.Accepted")


chk("QMessageBox.exec_() 真的能调用并返回", _msgbox_exec_runs)

dlg = QDialog()
chk("isinstance(dlg, QDialog)", lambda: None if isinstance(dlg, QDialog) else (_ for _ in ()).throw(AssertionError()))
frm = QFrame()
chk("QFrame.setFrameStyle(QFrame.StyledPanel|Raised)", lambda: frm.setFrameStyle(QFrame.StyledPanel | QFrame.Raised))
chk("isinstance(frm, QFrame)", lambda: None if isinstance(frm, QFrame) else (_ for _ in ()).throw(AssertionError()))
w = QWidget()
lay = QVBoxLayout(w)
chk("QVBoxLayout.addWidget", lambda: lay.addWidget(QLabel("hi")))
chk("QLabel.setAlignment(Qt.AlignCenter)", lambda: QLabel("x").setAlignment(Qt.AlignCenter))


class _Sig(QObject):
    sig = pyqtSignal(str)


chk("QObject + pyqtSignal subclass", lambda: _Sig())
chk("QMainWindow() ctor", lambda: QMainWindow())

failed = [r for r in RESULTS if not r[1]]
for label, good, msg in RESULTS:
    if not good:
        print(f"[FAIL] {label}: {msg}")
print(f"\ntotal={len(RESULTS)} passed={len(RESULTS) - len(failed)} failed={len(failed)}")
sys.exit(1 if failed else 0)
