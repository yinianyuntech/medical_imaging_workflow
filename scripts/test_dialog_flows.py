#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端验证：所有 `dialog.exec_()` 流程真的能打开并返回。

背景（用户实测报错）：`程序新建项目报错：exec(self): first argument of unbound
method must have type 'QDialog'`。

根因在兼容层 `_exec_alias`：它把 `getattr(cls, "exec")` 塞进子类命名空间当 `exec_`，
而 PyQt6 的**类级** `exec` 是"已绑定到类、且非描述符"的 builtin → 实例调用时
不会重新绑定 self，于是 sip 拿「类」当 self 调用底层方法 → 报错。
**全工程 29 处 `exec_()` 全部失效**（新建项目 / 首启向导 / 授权对话框 / 所有确认框）。

本脚本用 `QTimer` 自动关掉对话框，逐个**真实调用** `exec_()`。
只验证"能打开并返回"，不改变业务逻辑。

用法：
    python scripts/test_dialog_flows.py
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

from src.core.qt_compat.QtCore import QTimer  # noqa: E402
from src.core.qt_compat.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

app = QApplication.instance() or QApplication([])

from src.utils import skeuomorphic as sk  # noqa: E402
from src.utils import skeuo_style as st  # noqa: E402

sk.apply_global(app)
st.install(app)

RESULTS = []


def chk(label, fn):
    t0 = time.time()
    try:
        fn()
        RESULTS.append((label, True, f"{time.time() - t0:.2f}s"))
    except Exception as e:  # noqa: BLE001
        RESULTS.append((label, False, f"{type(e).__name__}: {e}"))


def auto_close(dlg, ms=350, action="reject"):
    """到点自动关掉对话框，避免模态阻塞。"""
    def _go():
        try:
            getattr(dlg, action)()
        except Exception:
            try:
                dlg.close()
            except Exception:
                pass
    QTimer.singleShot(ms, _go)


def auto_close_modal(ms=450, action="reject"):
    """关掉当前的活动模态对话框（用于"由业务代码自己创建对话框"的流程）。"""
    def _go():
        try:
            d = QApplication.activeModalWidget()
            if d is not None:
                getattr(d, action)()
        except Exception:
            pass
    QTimer.singleShot(ms, _go)


# ---------------------------------------------------------------- 1. 用户报错的那条流程
def flow_add_project():
    """★ 用户报错的确切流程：ProjectManagementWidget.add_project() → ProjectCreateDialog.exec_()"""
    from ui.widgets.project_management_widget import ProjectManagementWidget
    w = ProjectManagementWidget()
    auto_close_modal(500, "reject")
    w.add_project()          # 阻塞直到对话框关闭；修复前这里抛 TypeError
    w.deleteLater()


chk("★ add_project()（新建项目对话框 exec_）", flow_add_project)


# ---------------------------------------------------------------- 2. 首启向导（日志里也失败过）
def flow_first_run():
    from ui.dialogs.first_run_dialog import FirstRunDialog
    d = FirstRunDialog()
    auto_close(d, 300, "reject")
    d.exec_()


chk("FirstRunDialog.exec_()（首启向导）", flow_first_run)


# ---------------------------------------------------------------- 3. 其它对话框
def flow_license():
    from ui.widgets.license_activation_dialog import LicenseActivationDialog
    d = LicenseActivationDialog()
    auto_close(d, 250, "reject")
    d.exec_()


chk("LicenseActivationDialog.exec_()（授权对话框）", flow_license)


def flow_prompt_editor():
    from ui.widgets.prompt_editor_dialog import PromptEditorDialog
    d = PromptEditorDialog()
    auto_close(d, 250, "reject")
    d.exec_()


chk("PromptEditorDialog.exec_()", flow_prompt_editor)


def flow_template_wizard():
    from ui.widgets.template_wizard_dialog import TemplateWizardDialog
    d = TemplateWizardDialog()
    auto_close(d, 250, "reject")
    d.exec_()


chk("TemplateWizardDialog.exec_()", flow_template_wizard)


def flow_custom_api():
    from ui.widgets.ai_summary_widget import CustomAPIDialog
    d = CustomAPIDialog()
    auto_close(d, 250, "reject")
    d.exec_()


chk("CustomAPIDialog.exec_()", flow_custom_api)


# ---------------------------------------------------------------- 4. 消息框（全工程 20+ 处）
def flow_msgbox_accept():
    box = QMessageBox()
    box.setText("自检")
    box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
    auto_close(box, 200, "accept")
    r = box.exec_()
    if r != QDialog.Accepted:
        raise AssertionError(f"返回 {r}，期望 Accepted")


chk("QMessageBox.exec_() 点确定", flow_msgbox_accept)


def flow_project_create_dialog_accept():
    """★ 用户报错的那个对话框：**填好合法输入后**点确定。

    注意：`ProjectCreateDialog.accept()` 被重写过，名称为空时会弹警告并
    **不关闭**（这是业务校验，不是绑定问题）。所以这里必须先填输入，
    否则测的是"校验路径"而不是"接受路径"。
    """
    from ui.widgets.project_management_widget import ProjectCreateDialog
    d = ProjectCreateDialog()
    d.name_input.setText("自检项目")
    d.id_input.setText("selfcheck-1")
    auto_close(d, 300, "accept")
    r = d.exec_()
    if r != QDialog.Accepted:
        raise AssertionError(f"返回 {r}，期望 Accepted")


chk("ProjectCreateDialog.exec_() 填好输入点确定", flow_project_create_dialog_accept)


def flow_project_create_validation_kept():
    """校验仍在工作：空名称点确定，对话框**不得**被接受。"""
    from ui.widgets.project_management_widget import ProjectCreateDialog
    d = ProjectCreateDialog()

    # 空名称 → accept() 会弹出模态警告；用定时器关掉它
    def _kill_warning():
        w = QApplication.activeModalWidget()
        if w is not None:
            try:
                w.close()
            except Exception:
                pass
    QTimer.singleShot(250, _kill_warning)
    d.accept()
    if d.result() == QDialog.Accepted:
        raise AssertionError("空名称竟然被接受了 —— 业务校验被破坏")
    d.deleteLater()


chk("ProjectCreateDialog 空名称校验未被破坏", flow_project_create_validation_kept)


# ---------------------------------------------------------------- 报告
failed = [r for r in RESULTS if not r[1]]
print("=" * 78)
print("对话框流程端到端验证（exec_ 绑定修复）")
print("=" * 78)
for label, ok, msg in RESULTS:
    print(f"   {'PASS' if ok else 'FAIL'}  {label:52} {msg}")
print("-" * 78)
print(f"total={len(RESULTS)} passed={len(RESULTS) - len(failed)} failed={len(failed)}")
if failed:
    print("\n结论：exec_ 仍有问题 —— 对话框无法正常打开")
    sys.exit(1)
print("\n结论：全部对话框 exec_ 可正常打开并返回 ✅")
sys.exit(0)
