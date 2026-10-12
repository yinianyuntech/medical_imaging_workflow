#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""smoke_gui_pyqt6.py —— 在 PyQt6（qt_compat）下完整构建 MainWindow 并退出。

这会实例化**全部**步骤控件（项目/清洗/总结/预览/反馈/opencode 面板…），
是"框架迁移是否成功"最强的单条验证；不显示窗口、不进入事件循环。
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.core.qt_compat.QtCore import Qt, QTimer  # noqa: E402
from src.core.qt_compat.QtWidgets import QApplication  # noqa: E402

RESULTS = []


def main() -> int:
    app = QApplication.instance() or QApplication([])

    # 1) MainWindow 全量构建
    try:
        from ui.widgets.main_window import MainWindow
        win = MainWindow(remaining_seconds=0, license_exp_ts=0)
        RESULTS.append(("MainWindow()", True, ""))
    except Exception as e:  # noqa: BLE001
        RESULTS.append(("MainWindow()", False, f"{type(e).__name__}: {e}"))
        traceback.print_exc()
        print("RESULT: FAIL")
        return 1

    # 2) 页面数量（应为首步 + 5 步 + 辅助页）
    try:
        n = win.stacked_widget.count()
        RESULTS.append(("stacked pages", True, f"{n} pages"))
    except Exception as e:  # noqa: BLE001
        RESULTS.append(("stacked pages", False, str(e)))

    # 3) opencode 面板接入
    try:
        from src.kernel.kernel_boot import KernelBoot
        from src.kernel.mcp_server import set_ui_bridge
        from src.kernel.tools.ui_bridge import UIBridge

        bridge = UIBridge()
        set_ui_bridge(bridge)
        boot = KernelBoot()
        win.attach_opencode(bridge, boot)
        ok = getattr(win, "opencode_panel", None) is not None
        RESULTS.append(("attach_opencode", ok, "panel attached" if ok else "no panel"))
    except Exception as e:  # noqa: BLE001
        RESULTS.append(("attach_opencode", False, f"{type(e).__name__}: {e}"))

    # 4) 破坏性确认门（后台线程 -> 主线程弹窗路径）
    try:
        from src.kernel.tools import _common as kc

        called = {}

        def fake_hook(action, detail):
            called["action"] = action
            return False

        kc.set_confirm_hook(fake_hook)
        r = kc.guard("purge_project", {"project_id": "x"})
        RESULTS.append(("confirm gate denies", bool(r and r.get("ok") is False), str(called)))
    except Exception as e:  # noqa: BLE001
        RESULTS.append(("confirm gate denies", False, f"{type(e).__name__}: {e}"))

    # 5) 关键步骤页面切换不崩
    try:
        for fn in ("show_project_management", "show_data_cleaning", "show_feedback_optimization"):
            getattr(win, fn)()
        RESULTS.append(("step navigation", True, "3 pages switched"))
    except Exception as e:  # noqa: BLE001
        RESULTS.append(("step navigation", False, f"{type(e).__name__}: {e}"))

    QTimer.singleShot(0, app.quit)

    failed = [r for r in RESULTS if not r[1]]
    for label, ok, msg in RESULTS:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {msg}")
    print(f"\ntotal={len(RESULTS)} passed={len(RESULTS) - len(failed)} failed={len(failed)}")
    print("RESULT:", "FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
