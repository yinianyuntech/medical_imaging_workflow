#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mcp_server —— 宿主 MCP 服务（方向 A/C），兼容 mcp SDK v1 与 v2。

在**后台线程**内起 streamable-http 服务（不要用 stdio：windowed 构建会与主进程抢标准流），
把 `domain_tools.TOOL_FUNCTIONS` 全部注册为工具，供 opencode 内核调用。

SDK 差异：
  mcp <2   -> `mcp.server.fastmcp.FastMCP`     (host/port 走 server.settings)
  mcp >=2  -> `mcp.server.mcpserver.MCPServer` (host/port 走 run(**kwargs))
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any, Dict, Optional, Tuple

from .tools import domain_tools
from .tools.ui_bridge import UIBridge

DEFAULT_NAME = "medwork"
STREAMABLE_PATH = "/mcp"

_server = None
_thread: Optional[threading.Thread] = None
_url = ""
_port = 0
_flavor = ""
_bridge: Optional[UIBridge] = None


# ---------------------------------------------------------------- SDK 适配

def _load_server_class() -> Tuple[Any, str]:
    """返回 (类, flavor)。优先 v1 FastMCP，其次 v2 MCPServer。"""
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore
        return FastMCP, "v1"
    except Exception:
        pass
    try:
        from mcp.server.mcpserver import MCPServer  # type: ignore
        return MCPServer, "v2"
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "未安装可用的 MCP 服务端 SDK。请 `pip install 'mcp>=1.2.0'`"
            "（v1 用 FastMCP，v2 用 MCPServer）。原始错误: " + str(e)
        )


def build_server(name: str = DEFAULT_NAME, host: str = "127.0.0.1", port: int = 0):
    cls, flavor = _load_server_class()
    server = cls(name)

    if flavor == "v1":
        # v1：host/port/path 从 settings 读取
        try:
            server.settings.host = host
            server.settings.port = int(port)
            server.settings.streamable_http_path = STREAMABLE_PATH
        except Exception:
            pass

    _register_tools(server)
    return server, flavor


def _run_kwargs(flavor: str, host: str, port: int, path: str) -> Dict[str, Any]:
    if flavor == "v2":
        return {
            "transport": "streamable-http",
            "host": host,
            "port": int(port),
            "streamable_http_path": path,
        }
    return {"transport": "streamable-http"}


def _register_tools(server) -> int:
    count = 0
    for fn in domain_tools.TOOL_FUNCTIONS:
        added = False
        add = getattr(server, "add_tool", None)
        if callable(add):
            try:
                add(fn)
                added = True
            except Exception:
                added = False
        if not added:
            deco = getattr(server, "tool", None)
            if callable(deco):
                try:
                    deco()(fn)
                    added = True
                except Exception:
                    added = False
        if added:
            count += 1
    return count


def _wait_port(host: str, port: int, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.15)
    return False


# ---------------------------------------------------------------- 生命周期

def set_ui_bridge(bridge: UIBridge) -> None:
    """注入界面桥（MCP 工具只能 emit 信号，不能碰控件）。"""
    global _bridge
    _bridge = bridge
    domain_tools.set_ui_bridge(bridge)


def ui_bridge() -> Optional[UIBridge]:
    return _bridge


def serve_http_in_thread(
    name: str = DEFAULT_NAME,
    host: str = "127.0.0.1",
    port: int = 0,
    path: str = STREAMABLE_PATH,
) -> Dict[str, Any]:
    """后台线程启动 MCP 服务，返回 {"url","port","host","tools","flavor","server"}。"""
    global _server, _thread, _url, _port, _flavor

    # pythonw 下 sys.stdout/stderr 为 None，会让 uvicorn 日志初始化崩溃（实测）→ 兜底
    try:
        import os as _os
        if sys.stdout is None or sys.stderr is None:
            _devnull = open(_os.devnull, "w", encoding="utf-8")
            if sys.stdout is None:
                sys.stdout = _devnull
            if sys.stderr is None:
                sys.stderr = _devnull
    except Exception:
        pass

    if _server is not None and _url:
        return {"url": _url, "port": _port, "host": host, "server": _server,
                "tools": len(domain_tools.TOOL_FUNCTIONS), "flavor": _flavor, "reused": True}

    if int(port) <= 0:
        s = socket.socket()
        s.bind((host, 0))
        port = int(s.getsockname()[1])
        s.close()

    server, flavor = build_server(name=name, host=host, port=int(port))
    kwargs = _run_kwargs(flavor, host, int(port), path)

    def _diag(msg: str):
        """必落盘诊断（server.run 异常曾被吞）。"""
        try:
            import os as _os, time as _t
            with open(_os.path.join(_os.getcwd(), "boot_trace.log"),
                      "a", encoding="utf-8") as f:
                f.write(f"mcp:{_t.strftime('%H:%M:%S')} {msg}\n")
        except Exception:
            pass

    def _run():
        import traceback as _tb
        try:
            server.run(**kwargs)
        except TypeError as _te:
            _diag(f"run TypeError: {_te}; retry minimal")
            try:
                server.run(transport="streamable-http")
            except Exception:
                _diag("minimal retry EXC:\n" + _tb.format_exc())
        except Exception:
            _diag("server.run EXC:\n" + _tb.format_exc())

    _thread = threading.Thread(target=_run, name="mcp-server", daemon=True)
    _thread.start()

    if not _wait_port(host, int(port), timeout=30.0):
        raise RuntimeError(f"MCP 服务未能在 {host}:{port} 就绪（flavor={flavor}）")

    _server = server
    _flavor = flavor
    _port = int(port)
    _url = f"http://{host}:{int(port)}{path}"
    return {
        "url": _url, "port": _port, "host": host, "server": server,
        "tools": len(domain_tools.TOOL_FUNCTIONS), "flavor": flavor, "reused": False,
    }


def current_url() -> str:
    return _url


def flavor() -> str:
    return _flavor


def shutdown() -> None:
    """尽力关闭（SDK 无公开 stop；线程为 daemon，进程退出即回收）。"""
    global _server, _url, _port
    _server = None
    _url = ""
    _port = 0
