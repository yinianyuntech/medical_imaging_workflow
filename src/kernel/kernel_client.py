#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kernel_client —— opencode 内核传输层。

职责：
  * 方向 D：进程托管（spawn / adopt / stop / 进程列举）
  * 方向 B：legacy V1 HTTP（会话、投递、消息、标题、中断）
  * 问答 / 权限回灌（question / permission）
  * TUI 控制（attach / select-session / show-toast / execute-command）

安全性：HTTP 密码只通过环境变量注入子进程，**绝不进命令行**；`status()` 会剔除密码。
兼容性：不硬编码假设 —— `probe_api()` 启动后探测端点可用性，供上层自适应。
"""

from __future__ import annotations

import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

from . import kernel_paths as kp

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_LISTEN_RE = re.compile(r"listening on\s+(https?://[^\s]+)", re.IGNORECASE)


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s or "")


def _pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        if os.name == "nt":
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=10, creationflags=0x08000000,
            ).stdout or ""
            return str(int(pid)) in out
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


class KernelClient:
    """opencode 内核客户端。"""

    def __init__(
        self,
        exe: Optional[str] = None,
        *,
        hostname: str = "127.0.0.1",
        port: int = 0,
        password: Optional[str] = None,
        username: str = "opencode",
        startup_timeout: float = 60.0,
        request_timeout: float = 600.0,
        project_dir: Optional[str] = None,
    ):
        self.exe_arg = exe
        self.hostname = hostname
        self.port = int(port)
        self.username = username
        self._password = password or secrets.token_urlsafe(24)
        self.startup_timeout = float(startup_timeout)
        self.request_timeout = float(request_timeout)
        self.project_dir = project_dir

        self.proc: Optional[subprocess.Popen] = None
        self.url: str = ""
        self.pid: int = 0
        self.version: str = ""
        self.api: Dict[str, bool] = {}
        self._tui_proc: Optional[subprocess.Popen] = None
        self._tui_pid: int = 0

    # ------------------------------------------------------------ 基础

    @property
    def exe(self) -> str:
        if self.exe_arg:
            return self.exe_arg
        return str(kp.opencode_exe())

    @property
    def password(self) -> str:
        return self._password

    def _auth(self):
        return (self.username, self._password)

    def _url(self, path: str) -> str:
        base = self.url.rstrip("/")
        if not path.startswith("/"):
            path = "/" + path
        return base + path

    def _get(self, path: str, timeout: Optional[float] = None) -> Any:
        r = requests.get(self._url(path), auth=self._auth(), timeout=timeout or self.request_timeout)
        r.raise_for_status()
        return _maybe_json(r)

    def _post(self, path: str, payload: Optional[dict] = None, timeout: Optional[float] = None) -> Any:
        r = requests.post(self._url(path), json=(payload or {}), auth=self._auth(),
                          timeout=timeout or self.request_timeout)
        r.raise_for_status()
        return _maybe_json(r)

    def _patch(self, path: str, payload: Optional[dict] = None, timeout: Optional[float] = None) -> Any:
        r = requests.patch(self._url(path), json=(payload or {}), auth=self._auth(),
                           timeout=timeout or self.request_timeout)
        r.raise_for_status()
        return _maybe_json(r)

    # ------------------------------------------------------------ 方向 D

    def ensure_running(self) -> Dict:
        """优先接管存活实例，否则启动新实例。"""
        adopted = self.adopt_state()
        if adopted:
            return adopted
        return self.spawn()

    def adopt_state(self) -> Optional[Dict]:
        state = kp.read_state()
        pid = int(state.get("pid") or 0)
        port = int(state.get("port") or 0)
        pw = str(state.get("password") or "")
        url = str(state.get("url") or "")
        if not (pid and port and url):
            return None
        if not _pid_alive(pid):
            kp.clear_state()
            return None
        self.pid = pid
        self.port = port
        self.url = url
        if pw:
            self._password = pw
        try:
            h = self.health()
            if h.get("healthy") or h.get("version"):
                self.version = str(h.get("version") or self.version)
                self.api = self.probe_api()
                return self.status()
        except Exception:
            pass
        # 存活但不可用：视为无效
        kp.clear_state()
        self.pid = 0
        self.url = ""
        return None

    def spawn(self) -> Dict:
        if requests is None:
            raise RuntimeError("requests 不可用，无法启动内核")
        exe = self.exe
        env = kp.kernel_env({
            "OPENCODE_SERVER_PASSWORD": self._password,
            "OPENCODE_SERVER_USERNAME": self.username,
        })
        args = [exe, "serve", "--hostname", self.hostname, "--port", str(self.port)]
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        self.proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            cwd=self.project_dir or None,
            creationflags=flags,
        )
        self.pid = int(self.proc.pid or 0)
        url = self._read_listen_url(self.proc, self.startup_timeout)
        if not url:
            self.stop()
            raise RuntimeError("内核启动超时：未捕获 'listening on http://...'")
        self.url = url.rstrip("/")
        self.port = int(url.rsplit(":", 1)[-1].split("/")[0])
        # 健康检查
        deadline = time.time() + 30
        last_err = None
        while time.time() < deadline:
            try:
                h = self.health()
                self.version = str(h.get("version") or "")
                last_err = None
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(0.4)
        if last_err is not None:
            self.stop()
            raise RuntimeError(f"内核健康检查失败: {last_err}")
        self.api = self.probe_api()
        kp.write_state({
            "pid": self.pid,
            "port": self.port,
            "password": self._password,
            "url": self.url,
            "version": self.version,
        })
        return self.status()

    def _read_listen_url(self, proc: subprocess.Popen, timeout: float) -> str:
        deadline = time.time() + timeout
        stream = proc.stdout
        if stream is None:
            return ""
        while time.time() < deadline:
            if proc.poll() is not None:
                return ""
            line = stream.readline()
            if not line:
                time.sleep(0.05)
                continue
            m = _LISTEN_RE.search(_strip_ansi(line))
            if m:
                return m.group(1).strip()
        return ""

    def stop(self) -> None:
        """停止内核：先礼貌 terminate，再**始终**树杀以回收 launcher 派生的子进程。"""
        self.stop_tui()
        proc = self.proc
        pid = int(self.pid or (getattr(proc, "pid", 0) or 0) or 0)
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        pass
            except Exception:
                pass
        # 关键：npm 包装器会派生真正的服务进程，terminate 只杀父进程会留下孤儿。
        if pid:
            _kill_tree(pid)
        self.proc = None
        self.pid = 0
        kp.clear_state()

    def health(self) -> Dict:
        return self._get("/global/health", timeout=15)

    def status(self) -> Dict:
        """脱敏状态（不含密码）。"""
        return {
            "running": bool(self.pid and self.url),
            "pid": self.pid,
            "port": self.port,
            "url": self.url,
            "version": self.version,
            "api": dict(self.api),
            "exe": self.exe,
        }

    def probe_api(self) -> Dict[str, bool]:
        """探测 legacy V1 端点可用性（用于版本自适应）。"""
        out: Dict[str, bool] = {}
        for name, path in (
            ("health", "/global/health"),
            ("session_list", "/session"),
            ("question", "/question"),
            ("permission", "/permission"),
        ):
            try:
                self._get(path, timeout=8)
                out[name] = True
            except Exception:
                out[name] = False
        return out

    def list_processes(self) -> List[Dict]:
        """列举 opencode.exe 进程（Windows），**带命令行**。

        ⚠️ 为什么必须带 cmdline
        ---------------------
        playbook §8.1 的清理规则是：

            「清理只匹配**自己 spawn 的确切参数**（如 `serve --hostname 127.0.0.1 --port 0`）
              并显式排除 `@opencode\\cli` / `--service`」

        这台机器上**同时装着 opencode 1.x 和 2.x**，还有别的宿主在用 npm 全局那份，
        所以"按 pid 猜"很危险 —— 必须能看到命令行才能安全区分。
        而 `tasklist` **拿不到命令行**（只有 image/pid/session），
        实测表现就是 `cmdline=None` → `spawn_tui` 的进程发现、
        `_reap_extra_attach` 的参数匹配全部失效。

        因此优先用 CIM（PowerShell `Get-CimInstance` → JSON），
        WMIC 次之，`tasklist` 仅作最后兜底（此时只有 pid，
        调用方**不得**按参数匹配，只能按 pid 精确操作）。
        """
        rows = self._list_processes_cim()
        if rows is not None:
            return rows
        rows = self._list_processes_wmic()
        if rows is not None:
            return rows
        return self._list_processes_tasklist()

    def _list_processes_cim(self) -> Optional[List[Dict]]:
        """PowerShell CIM → JSON（带 CommandLine/ParentProcessId）。失败返回 None。"""
        try:
            script = (
                "Get-CimInstance Win32_Process -Filter \"Name='opencode.exe'\" | "
                "Select-Object ProcessId,ParentProcessId,CommandLine | "
                "ConvertTo-Json -Compress -Depth 3"
            )
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=25, creationflags=0x08000000 if os.name == "nt" else 0,
            ).stdout or ""
            out = out.strip()
            if not out:
                return []
            data = json.loads(out)
            if isinstance(data, dict):
                data = [data]
            rows = []
            for it in data:
                try:
                    pid = int(it.get("ProcessId") or 0)
                except Exception:
                    continue
                if pid <= 0:
                    continue
                rows.append({
                    "image": "opencode.exe",
                    "pid": pid,
                    "ppid": int(it.get("ParentProcessId") or 0),
                    "cmdline": str(it.get("CommandLine") or ""),
                    "session": "",
                })
            return rows
        except Exception:
            return None

    def _list_processes_wmic(self) -> Optional[List[Dict]]:
        """WMIC 兜底（部分系统已移除）。失败返回 None。"""
        try:
            out = subprocess.run(
                ["wmic", "process", "where", "name='opencode.exe'",
                 "get", "ProcessId,ParentProcessId,CommandLine", "/format:csv"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=20, creationflags=0x08000000 if os.name == "nt" else 0,
            ).stdout or ""
            rows = []
            header = None
            for line in out.splitlines():
                line = line.strip()
                if not line:
                    continue
                cols = line.split(",")
                if header is None:
                    header = [c.strip().lower() for c in cols]
                    continue
                rec = dict(zip(header, cols))
                try:
                    pid = int(rec.get("processid") or 0)
                except Exception:
                    continue
                if pid <= 0:
                    continue
                rows.append({
                    "image": "opencode.exe",
                    "pid": pid,
                    "ppid": int(rec.get("parentprocessid") or 0 or 0),
                    "cmdline": str(rec.get("commandline") or ""),
                    "session": "",
                })
            return rows
        except Exception:
            return None

    def _list_processes_tasklist(self) -> List[Dict]:
        """最后兜底：只有 pid（**无命令行**，调用方不得按参数匹配）。"""
        rows: List[Dict] = []
        try:
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq opencode.exe", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=15, creationflags=0x08000000 if os.name == "nt" else 0,
            ).stdout or ""
            for line in out.splitlines():
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 2 and parts[0].lower().endswith("opencode.exe"):
                    rows.append({"image": parts[0], "pid": int(parts[1]),
                                 "ppid": 0, "cmdline": "",
                                 "session": parts[2] if len(parts) > 2 else ""})
        except Exception:
            pass
        return rows

    # ------------------------------------------------------------ 方向 B（legacy V1）

    def create_session(self, title: str = "", model: Optional[dict] = None, agent: Optional[str] = None) -> Dict:
        payload: Dict[str, Any] = {}
        if title:
            payload["title"] = title
        if model:
            payload["model"] = model
        if agent:
            payload["agent"] = agent
        return self._post("/session", payload)

    def list_sessions(self) -> List[Dict]:
        r = self._get("/session")
        return r if isinstance(r, list) else []

    def prompt_legacy(self, session_id: str, text: str, model: Optional[dict] = None,
                      timeout: Optional[float] = None) -> Dict:
        """阻塞投递一轮任务，返回 {info, parts}。timeout 缺省走 request_timeout。"""
        payload: Dict[str, Any] = {"parts": [{"type": "text", "text": str(text)}]}
        if model:
            payload["model"] = model
        return self._post(f"/session/{session_id}/message", payload, timeout=timeout)

    def post_message_noreply(self, session_id: str, text: str, model: Optional[dict] = None) -> Dict:
        payload: Dict[str, Any] = {"parts": [{"type": "text", "text": str(text)}], "noReply": True}
        if model:
            payload["model"] = model
        return self._post(f"/session/{session_id}/message", payload)

    def list_messages(self, session_id: str) -> List[Dict]:
        r = self._get(f"/session/{session_id}/message")
        return r if isinstance(r, list) else []

    def update_session_title(self, session_id: str, title: str) -> Dict:
        return self._patch(f"/session/{session_id}", {"title": str(title)})

    def abort(self, session_id: str) -> None:
        try:
            self._post(f"/session/{session_id}/abort", {})
        except Exception:
            pass

    # ------------------------------------------------------------ 问答 / 权限

    def legacy_questions(self) -> List[Dict]:
        try:
            r = self._get("/question", timeout=15)
            return r if isinstance(r, list) else []
        except Exception:
            return []

    def reply_question(self, request_id: str, answers: List[List[str]]) -> Any:
        return self._post(f"/question/{request_id}/reply", {"answers": answers})

    def reject_question(self, request_id: str) -> Any:
        return self._post(f"/question/{request_id}/reject", {})

    def legacy_permissions(self) -> List[Dict]:
        try:
            r = self._get("/permission", timeout=15)
            return r if isinstance(r, list) else []
        except Exception:
            return []

    def reply_permission(self, request_id: str, reply: str = "once", message: str = "") -> Any:
        payload: Dict[str, Any] = {"reply": reply}
        if message:
            payload["message"] = message
        return self._post(f"/permission/{request_id}/reply", payload)

    # ------------------------------------------------------------ TUI

    def tui_select_session(self, session_id: str) -> bool:
        try:
            r = self._post("/tui/select-session", {"sessionID": str(session_id)}, timeout=20)
            return bool(r) if not isinstance(r, dict) else bool(r.get("success", True))
        except Exception:
            return False

    def tui_show_toast(self, message: str, variant: str = "info", title: str = "") -> bool:
        payload: Dict[str, Any] = {"message": str(message), "variant": str(variant)}
        if title:
            payload["title"] = str(title)
        try:
            r = self._post("/tui/show-toast", payload, timeout=20)
            return True if r is None else bool(r if not isinstance(r, dict) else r.get("success", True))
        except Exception:
            return False

    def tui_execute_command(self, command: str) -> bool:
        try:
            r = self._post("/tui/execute-command", {"command": str(command)}, timeout=20)
            return True if r is None else bool(r if not isinstance(r, dict) else r.get("success", True))
        except Exception:
            return False

    def spawn_tui(self, session_id: Optional[str] = None, project_dir: Optional[str] = None) -> int:
        """直接 spawn `opencode attach <url>`；返回真实 attach 进程 pid（经进程发现）。"""
        if not self.url:
            return 0
        exe = self.exe
        env = kp.kernel_env({
            "OPENCODE_SERVER_PASSWORD": self._password,
            "OPENCODE_SERVER_USERNAME": self.username,
        })
        args = [exe, "attach", self.url]
        workdir = project_dir or self.project_dir
        if workdir:
            args += ["--dir", str(workdir)]
        if session_id:
            args += ["--session", str(session_id)]
        # 可见控制台：TUI 需要真实终端才能渲染 → CREATE_NEW_CONSOLE（独立 shell 窗口）；
        # MIMW_TUI_VISIBLE=0 时退回隐藏窗口（测试/无桌面场景）。
        if os.name == "nt":
            _visible = str(os.environ.get("MIMW_TUI_VISIBLE", "1")).strip() != "0"
            flags = 0x00000010 if _visible else 0x08000000
        else:
            flags = 0
        before = {r["pid"] for r in self.list_processes()}
        proc = subprocess.Popen(args, env=env, creationflags=flags, cwd=workdir or None)
        self._tui_proc = proc
        time.sleep(2.5)
        # 进程发现：拿到真正的 attach pid（避开 wt.exe 的 Popen.pid 陷阱）
        after = self.list_processes()
        new = [r for r in after if r["pid"] not in before]
        if new:
            self._tui_pid = int(new[-1]["pid"])
        else:
            self._tui_pid = int(proc.pid or 0)
        return self._tui_pid

    def stop_tui(self) -> None:
        if self._tui_proc is not None:
            try:
                if self._tui_proc.poll() is None:
                    _kill_tree(self._tui_proc.pid)
            except Exception:
                pass
            self._tui_proc = None
        if self._tui_pid:
            try:
                _kill_tree(self._tui_pid)
            except Exception:
                pass
            self._tui_pid = 0

    # ------------------------------------------------------------ MCP 清点

    def mcp_list(self, timeout: float = 90.0) -> str:
        """执行 `opencode mcp list` 返回文本。"""
        try:
            flags = 0x08000000 if os.name == "nt" else 0
            env = kp.kernel_env()
            p = subprocess.run([self.exe, "mcp", "list"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=timeout, env=env, creationflags=flags)
            return _strip_ansi((p.stdout or "") + (p.stderr or "")).strip()
        except Exception as e:  # noqa: BLE001
            return f"[mcp list failed] {e}"


# ---------------------------------------------------------------- 工具函数

def _maybe_json(resp) -> Any:
    try:
        return resp.json()
    except Exception:
        txt = (resp.text or "").strip()
        return txt if txt else None


def _kill_tree(pid: int) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(int(pid))],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=15, creationflags=0x08000000)
        else:
            os.kill(int(pid), 9)
    except Exception:
        pass


def free_port() -> int:
    """获取一个空闲端口。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port
