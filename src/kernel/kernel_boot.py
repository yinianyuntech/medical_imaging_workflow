#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kernel_boot —— GUI <-> 内核总控。

启动顺序（关键，来自 digitalfly 实测教训）：
  1) 起宿主 MCP 服务（后台线程）
  2) **先**写 opencode.json 注册 MCP（必须早于内核启动）
  3) 安装随包 agent/skill 资产 + 导入宿主 LLM 凭据
  4) ensure_running（adopt 存活实例，否则 spawn）
  5) 校验内核是否连上 MCP；接管来的实例若未连上则重启内核
  6) 绑定/恢复 项目 <-> 会话
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable, Dict, Optional

from . import kernel_config as kc
from . import kernel_paths as kp
from . import mcp_server
from .kernel_client import KernelClient
from .kernel_driver import KernelDriver
from .tools import _common as C
from .tools.ui_bridge import UIBridge

ConfirmHandler = Callable[[str, Dict], bool]


class KernelBoot:
    def __init__(
        self,
        *,
        mcp_name: str = "medwork",
        project_dir: Optional[str] = None,
        exe: Optional[str] = None,
        confirm_handler: Optional[ConfirmHandler] = None,
        model: str = "",
        mcp_timeout_ms: int = 600000,
        autostart_tui: bool = False,
    ):
        self.mcp_name = str(mcp_name or "medwork")
        self.project_dir = str(project_dir or kp.project_root())
        self.exe = exe or os.environ.get("MIMW_OPENCODE_EXE", "")
        self.confirm_handler = confirm_handler
        self.model = str(model or os.environ.get("MIMW_KERNEL_MODEL", "") or "")
        self.mcp_timeout_ms = int(mcp_timeout_ms)
        self.autostart_tui = bool(autostart_tui)

        self.client: Optional[KernelClient] = None
        self.bridge: Optional[UIBridge] = None
        self._driver: Optional[KernelDriver] = None
        self._active_session_id = ""
        self._lock = threading.RLock()
        self._started = False
        self.last_error = ""

    # ------------------------------------------------------------ 启动 / 停止

    def start(self, bridge: Optional[UIBridge] = None) -> Dict:
        with self._lock:
            if self._started:
                return self.status()
            self.last_error = ""
            try:
                kp.ensure_kernel_dirs()
                kc.install_builtin_assets()

                # 1) 宿主 MCP 服务
                bridge = bridge or self.bridge or UIBridge()
                self.bridge = bridge
                mcp_server.set_ui_bridge(bridge)
                served = mcp_server.serve_http_in_thread(name=self.mcp_name)
                url = served["url"]

                # 2) 先注册 MCP（早于内核启动）
                kc.set_mcp_server(self.mcp_name, url, timeout_ms=self.mcp_timeout_ms)
                kc.ensure_default_model(self.model)
                kc.ensure_default_agent()

                # 3) 凭据
                auth = kc.import_host_llm_key()

                # 4) 内核
                self.client = KernelClient(self.exe or None, project_dir=self.project_dir)
                self._driver = KernelDriver(self.client)
                state = self.client.ensure_running()

                # 5) 校验 MCP 连接（接管实例可能没连上）
                if os.environ.get("MIMW_KERNEL_VERIFY_MCP", "1") == "1":
                    if not self._mcp_connected():
                        self._restart_kernel()
                        state = self.status()

                self._started = True
                if self.autostart_tui:
                    try:
                        self.client.spawn_tui(
                            session_id=(self._active_session_id or None),
                            project_dir=self.project_dir)
                    except Exception:
                        pass
                return {
                    "ok": True,
                    "kernel": state,
                    "mcp_url": url,
                    "auth": auth,
                    "assets": None,
                }
            except Exception as e:  # noqa: BLE001
                self.last_error = f"{type(e).__name__}: {e}"
                return {"ok": False, "error": self.last_error}

    def _mcp_connected(self) -> bool:
        try:
            text = self.client.mcp_list() if self.client else ""
        except Exception:
            return False
        low = (text or "").lower()
        if not low.strip():
            return False
        if any(bad in low for bad in ("failed", "error", "not found", "no mcp")):
            return False
        return self.mcp_name.lower() in low

    def _restart_kernel(self) -> None:
        try:
            if self.client:
                self.client.stop()
            if self.client is None:
                return
            self.client.ensure_running()
        except Exception:
            pass

    def stop(self) -> None:
        with self._lock:
            try:
                if self.client:
                    self.client.stop()
            except Exception:
                pass
            try:
                mcp_server.shutdown()
            except Exception:
                pass
            self._started = False

    # ------------------------------------------------------------ 访问器

    def driver(self) -> Optional[KernelDriver]:
        return self._driver

    def is_running(self) -> bool:
        try:
            return bool(self.client and self.client.pid and self.client.url)
        except Exception:
            return False

    def status(self) -> Dict:
        """脱敏状态（不含密码 / 不含 api_key）。"""
        base: Dict[str, Any] = {
            "started": self._started,
            "mcp_name": self.mcp_name,
            "mcp_url": mcp_server.current_url(),
            "last_error": self.last_error,
        }
        try:
            if self.client:
                base["kernel"] = self.client.status()
            else:
                base["kernel"] = {"running": False}
        except Exception as e:  # noqa: BLE001
            base["kernel"] = {"running": False, "error": str(e)}
        for k in ("password", "api_key", "token"):
            base.pop(k, None)
        return base

    # ------------------------------------------------------------ 会话绑定

    def ensure_project_session(self, project_id: str, title: str = "") -> str:
        if not self.client:
            raise RuntimeError("kernel not started")
        pid = str(project_id or "").strip()
        if not pid:
            raise ValueError("project_id is required")
        sid = kc.get_project_session(pid)
        if sid:
            # 校验会话仍存在
            try:
                known = {str(s.get("id")) for s in self.client.list_sessions()}
                if sid in known:
                    self._active_session_id = sid
                    return sid
            except Exception:
                self._active_session_id = sid
                return sid
        created = self.client.create_session(
            title=title or f"project:{pid}",
            agent=kc.default_agent_name(),
        )
        sid = str((created or {}).get("id") or "")
        if not sid:
            raise RuntimeError(f"create_session failed: {created}")
        kc.bind_project_session(pid, sid, title=title or f"project:{pid}")
        self._active_session_id = sid
        return sid

    def switch_project(self, project_id: str, title: str = "") -> str:
        sid = self.ensure_project_session(project_id, title=title)
        try:
            if self.client:
                self.client.tui_select_session(sid)
                self.client.tui_show_toast(f"已切换课题: {title or project_id}", variant="info")
        except Exception:
            pass
        return sid

    # ------------------------------------------------------------ TUI 控制台（独立 shell）

    def _tui_alive(self) -> bool:
        """进程发现：是否存在本内核的 attach（TUI）进程；命中则采纳其 pid。"""
        try:
            url = str(self.client.url or "")
            for r in (self.client.list_processes() or []):
                cl = str(r.get("cmdline") or "")
                if "attach" not in cl:
                    continue
                if url and url not in cl:
                    continue
                self.client._tui_pid = int(r.get("pid") or 0)
                return True
        except Exception:
            pass
        return False

    def open_console(self, session_id: str = "") -> Dict:
        """打开/聚焦**可见的 TUI 控制台**（独立 shell 窗口），并指向当前会话。"""
        if self.client is None or not self.is_running():
            return {"ok": False, "error": "kernel not running"}
        sid = str(session_id or self._active_session_id or "")
        try:
            if self._tui_alive():
                if sid:
                    self.client.tui_select_session(sid)
                self.client.tui_show_toast("控制台已跟随当前会话", variant="info")
                return {"ok": True, "spawned": False,
                        "pid": int(self.client._tui_pid or 0), "session": sid}
            pid = int(self.client.spawn_tui(session_id=sid or None,
                                            project_dir=self.project_dir) or 0)
            return {"ok": bool(pid), "spawned": True, "pid": pid, "session": sid}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def follow_project(self, project_id: str, title: str = "") -> None:
        """让 TUI 控制台**跟随应用当前项目会话**（内核未起/TUI 未开时静默）。"""
        if self.client is None or not self.is_running():
            return
        try:
            sid = self.ensure_project_session(project_id, title=title)
        except Exception:
            return
        try:
            if self._tui_alive():
                self.client.tui_select_session(sid)
                self.client.tui_show_toast(f"已跟随项目: {title or project_id}", variant="info")
        except Exception:
            pass

    def rename_project(self, old_id: str, new_id: str, title: str = "") -> None:
        kc.rename_project_session(old_id, new_id)
        sid = kc.get_project_session(new_id)
        if sid and self.client:
            try:
                self.client.update_session_title(sid, title or f"project:{new_id}")
                self.client.tui_select_session(sid)
                self.client.tui_show_toast(f"课题已重命名: {new_id}", variant="info")
            except Exception:
                pass

    # ------------------------------------------------------------ 任务投递

    def _question_handler(self, payload: Dict) -> list:
        """把内核的 question 弹到 GUI（阻塞等待）。"""
        qs = (payload or {}).get("questions") or []
        prompt = "请选择："
        options = []
        if qs:
            first = qs[0] or {}
            prompt = str(first.get("question") or first.get("header") or prompt)
            for opt in (first.get("options") or []):
                if isinstance(opt, dict) and opt.get("label"):
                    options.append(str(opt["label"]))
                elif isinstance(opt, str):
                    options.append(opt)
        if self.bridge is None:
            return []
        labels = self.bridge.ask(prompt, options=options)
        if not labels and options:
            labels = [options[0]]
        return labels

    def _permission_handler(self, payload: Dict) -> str:
        """把内核的 permission 请求路由到宿主的确认门（默认拒绝更安全）。"""
        detail = {
            "action": (payload or {}).get("action", "permission"),
            "resources": (payload or {}).get("resources", ""),
        }
        if self.confirm_handler is None:
            return "reject"
        try:
            return "once" if self.confirm_handler("kernel_permission", detail) else "reject"
        except Exception:
            return "reject"

    def run_task(self, project_id: str, text: str, on_event=None, **kwargs) -> Dict:
        if self._driver is None or self.client is None:
            return {"ok": False, "error": "kernel not started"}
        sid = self.ensure_project_session(project_id)
        return self._driver.run_turn(
            sid,
            text,
            on_event=on_event,
            question_handler=kwargs.pop("question_handler", self._question_handler),
            permission_handler=kwargs.pop("permission_handler", self._permission_handler),
            **kwargs,
        )

    def run_task_async(self, project_id: str, text: str, on_event=None, **kwargs) -> threading.Thread:
        t = threading.Thread(
            target=self.run_task, args=(project_id, text),
            kwargs={"on_event": on_event, **kwargs}, daemon=True,
        )
        t.start()
        return t
