#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_gui_kernel_link.py —— GUI <-> 内核（方向 A）Qt 线程安全自检。

验证三件事：
  1) MCP 工具线程（后台）调用 UIBridge 时，信号能安全排队到主线程槽；
  2) 阻塞式 `ask()`（内核 question 回灌）能被主线程 `provide_answer()` 唤醒；
  3) `gui_status()` 快照**绝不包含**密码 / api_key。

无 PyQt5 环境时打印 SKIP 并以 0 退出。
"""

import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

for _stream in ("stdout", "stderr"):
    try:
        getattr(sys, _stream).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main() -> int:
    try:
        from src.core.qt_compat.QtCore import QTimer
        from src.core.qt_compat.QtWidgets import QApplication
    except Exception as e:  # noqa: BLE001
        print(f"SKIP: PyQt5 不可用 ({e})")
        return 0

    from src.kernel.tools.ui_bridge import UIBridge

    app = QApplication.instance() or QApplication(sys.argv)
    bridge = UIBridge()

    got = {"toast": [], "navigate": [], "log": [], "ask": None}

    # 主线程槽（跨线程 emit 会自动排队到这里）
    bridge.toastRequested.connect(lambda m: got["toast"].append(m))
    bridge.navigateRequested.connect(lambda s, p: got["navigate"].append((s, p)))
    bridge.logRequested.connect(lambda m: got["log"].append(m))

    def worker():
        """模拟 MCP 工具线程。"""
        bridge.gui_toast("来自后台线程")
        bridge.gui_navigate(3, "p1")
        bridge.gui_log("hello")
        got["ask"] = bridge.ask("是否继续？", ["继续", "停止"], timeout=15)

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    def answer_pending():
        for rid in list(getattr(bridge, "_pending_asks", {}).keys()):
            bridge.provide_answer(rid, ["继续"])

    QTimer.singleShot(400, answer_pending)
    QTimer.singleShot(2500, app.quit)
    app.exec_()
    t.join(timeout=3)

    assert got["toast"] == ["来自后台线程"], f"toast 未跨线程送达: {got['toast']}"
    assert got["navigate"] == [(3, "p1")], f"navigate 未送达: {got['navigate']}"
    assert got["log"] == ["hello"], f"log 未送达: {got['log']}"
    assert got["ask"] == ["继续"], f"ask 未被主线程唤醒: {got['ask']}"

    # 状态脱敏
    bridge.set_status_snapshot({
        "password": "SECRET-PW",
        "api_key": "SECRET-KEY",
        "current_project_id": "p1",
    })
    st = bridge.gui_status()
    blob = json.dumps(st, ensure_ascii=False)
    assert "SECRET-PW" not in blob, f"快照泄露 password: {blob}"
    assert "SECRET-KEY" not in blob, f"快照泄露 api_key: {blob}"
    assert st.get("ok") is True and st["data"]["current_project_id"] == "p1", st

    # 越界导航应被拒绝
    bad = bridge.gui_navigate(9, "p1")
    assert bad.get("ok") is False, f"越界 step 未被拒绝: {bad}"

    print("OK: gui kernel link (thread-safe signals + ask + redaction)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
