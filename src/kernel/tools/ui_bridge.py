#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ui_bridge —— 界面桥（方向 A 的 GUI 层）。

铁律：MCP 工具运行在**后台线程**，绝不能直接操作 PyQt5 控件。
本模块的方法只 `emit` 信号（Qt 队列连接会自动排队到主线程），
主线程的槽函数再落具体动作。

`gui_status()` 返回的是主线程推入的快照，**绝不含内核 HTTP 密码**。
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, List, Optional

try:
    from src.core.qt_compat.QtCore import QObject, pyqtSignal
    _HAS_QT = True
except Exception:  # pragma: no cover - headless / 无 PyQt5
    _HAS_QT = False

    class QObject:  # type: ignore
        def __init__(self, *a, **k):
            pass

    def pyqtSignal(*a, **k):  # type: ignore
        class _Sig:
            def __init__(self, *a2, **k2):
                pass

            def connect(self, *a2, **k2):
                return None

            def emit(self, *a2, **k2):
                return None
        return _Sig()


class UIBridge(QObject):
    """GUI -> agent 的状态快照 + agent -> GUI 的动作信号。"""

    statusRequested = pyqtSignal()
    toastRequested = pyqtSignal(str)
    navigateRequested = pyqtSignal(int, str)   # step, project_id
    logRequested = pyqtSignal(str)
    askRequested = pyqtSignal(str, str, object)   # request_id, prompt, options(list|None)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._snapshot: Dict[str, Any] = {}
        self._log_buffer: List[str] = []
        self._log_cap = 400
        self._pending_asks: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------ 阻塞式提问（供后台线程用）

    def ask(self, prompt: str, options: Optional[List[str]] = None, timeout: float = 300.0) -> List[str]:
        """后台线程调用：弹到主线程并在主线程 answered 后返回所选 label 列表。"""
        rid = uuid.uuid4().hex
        entry: Dict[str, Any] = {"event": threading.Event(), "labels": []}
        self._pending_asks[rid] = entry
        try:
            self.askRequested.emit(rid, str(prompt), list(options) if options else None)
            entry["event"].wait(timeout)
        finally:
            self._pending_asks.pop(rid, None)
        return list(entry.get("labels") or [])

    def provide_answer(self, request_id: str, labels: List[str]) -> None:
        """主线程调用：提交用户选择。"""
        entry = self._pending_asks.get(str(request_id))
        if not entry:
            return
        entry["labels"] = list(labels or [])
        entry["event"].set()

    # ------------------------------------------------ 主线程侧写入

    def set_status_snapshot(self, data: Dict) -> None:
        """由主线程调用，注入当前 GUI 状态（调用方负责脱敏）。"""
        snap = dict(data or {})
        for k in ("password", "OPENCODE_SERVER_PASSWORD", "token", "api_key"):
            snap.pop(k, None)
        snap["_ts"] = time.strftime("%H:%M:%S")
        self._snapshot = snap

    def note_log(self, message: str) -> None:
        self._log_buffer.append(f"[{time.strftime('%H:%M:%S')}] {str(message)}")
        if len(self._log_buffer) > self._log_cap:
            del self._log_buffer[: len(self._log_buffer) - self._log_cap]

    # ------------------------------------------------ MCP 工具侧（后台线程）

    def gui_status(self) -> Dict:
        return {"ok": True, "data": dict(self._snapshot)}

    def gui_toast(self, message: str) -> Dict:
        self.toastRequested.emit(str(message))
        return {"ok": True, "data": "queued"}

    def gui_navigate(self, step: int, project_id: str = "") -> Dict:
        try:
            step_i = int(step)
        except Exception:
            return {"ok": False, "error": "step must be an integer 1-5"}
        if step_i < 1 or step_i > 5:
            return {"ok": False, "error": "step out of range 1-5"}
        self.navigateRequested.emit(step_i, str(project_id or ""))
        return {"ok": True, "data": {"step": step_i, "project_id": project_id}}

    def gui_log(self, message: str) -> Dict:
        self.logRequested.emit(str(message))
        return {"ok": True, "data": "queued"}

    def recent_logs(self, limit: int = 80) -> List[str]:
        n = max(1, int(limit))
        return list(self._log_buffer[-n:])
