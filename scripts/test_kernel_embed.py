#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_kernel_embed.py —— opencode 内嵌全链路自检。

用法：
    python scripts/test_kernel_embed.py --offline     # 静态自检（不启动内核）
    python scripts/test_kernel_embed.py               # 全链路（起 MCP + 内核，校验 connected）
    python scripts/test_kernel_embed.py --prompt      # 追加一轮真实对话（需要 auth.json）

退出码 0 表示通过。
"""

import argparse
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Windows 控制台默认 GBK，打印 ✓ / 中文会崩（playbook §8）。统一切到 UTF-8。
for _stream in ("stdout", "stderr"):
    try:
        getattr(sys, _stream).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.kernel import kernel_config as kc          # noqa: E402
from src.kernel import kernel_paths as kp           # noqa: E402

RESULTS = []


def check(name, fn):
    try:
        detail = fn()
        RESULTS.append({"name": name, "ok": True, "detail": detail})
        print(f"[PASS] {name}: {detail}")
        return True
    except Exception as e:  # noqa: BLE001
        RESULTS.append({"name": name, "ok": False, "detail": f"{type(e).__name__}: {e}"})
        print(f"[FAIL] {name}: {type(e).__name__}: {e}")
        return False


# ---------------------------------------------------------------- 静态自检

def t_exe():
    exe = kp.opencode_exe()
    ver = kp.opencode_version(exe)
    major = 0
    for tok in (ver or "").replace("v", " ").split():
        if tok and tok[0].isdigit():
            major = int(tok.split(".")[0])
            break
    assert major, f"无法解析版本: {ver!r}"
    if major >= 2:
        print(f"       [WARN] 选中 opencode {major}.x，本嵌入按 legacy V1 契约实现；"
              f"建议 MIMW_OPENCODE_EXE 指向 1.x")
    return f"{ver} @ {exe}"


def t_dirs():
    kp.ensure_kernel_dirs()
    for d in (kp.data_dir(), kp.config_dir(), kp.state_dir(), kp.cache_dir(), kp.opencode_config_dir()):
        assert d.is_dir(), f"目录缺失: {d}"
    return str(kp.kernel_home())


def t_assets():
    inst = kc.install_builtin_assets()
    assert inst.get("agent", 0) >= 1, f"agent 未安装: {inst}"
    assert inst.get("skill", 0) >= 1, f"skill 未安装: {inst}"
    return inst


def t_default_agent_static():
    """loopx 默认 agent（静态面）：随包资产 + 安装 + 配置 + frontmatter。"""
    src_asset = kp.assets_root() / "agent" / "loopx.md"
    assert src_asset.is_file(), f"随包缺少 loopx.md: {src_asset}"
    text = src_asset.read_text(encoding="utf-8")
    assert "mode: primary" in text, "loopx.md frontmatter 缺 mode: primary"
    kc.install_builtin_assets()
    inst = kp.opencode_config_dir() / "agent" / "loopx.md"
    assert inst.is_file(), f"loopx.md 未安装到隔离 home: {inst}"
    cfg = kc.ensure_default_agent()
    assert cfg.get("default_agent") == "loopx", f"default_agent 未写入: {cfg.get('default_agent')}"
    assert kc.default_agent_name() == "loopx", "default_agent_name() 解析错误"
    return "agent=loopx 安装+配置+primary 校验通过"


def t_config():
    cfg = kc.set_mcp_server("medwork", "http://127.0.0.1:9/mcp", timeout_ms=600000)
    assert "mcp" in cfg, "opencode.json 缺少 mcp 键"
    assert cfg["mcp"]["medwork"]["timeout"] == 600000, "MCP timeout 未写入"
    assert cfg["mcp"]["medwork"]["type"] == "remote", "MCP type 必须为 remote"
    return str(kc.config_path())


def t_env():
    env = kp.kernel_env()
    for k in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "OPENCODE_CONFIG_DIR"):
        assert env.get(k), f"环境变量缺失: {k}"
    assert env.get("OPENCODE_CLIENT") == "desktop", "OPENCODE_CLIENT 必须为 desktop"
    assert env.get("OPENCODE_DISABLE_AUTOUPDATE") == "1", "未禁自更新"
    return "XDG_* / OPENCODE_CLIENT=desktop / AUTOUPDATE=0"


def t_status_redaction():
    """status() 绝不能泄露密码。"""
    from src.kernel.kernel_boot import KernelBoot
    boot = KernelBoot()
    st = boot.status()
    blob = json.dumps(st, ensure_ascii=False, default=str)
    assert "password" not in blob.lower(), "status 泄露了 password 字段"
    assert "api_key" not in blob.lower(), "status 泄露了 api_key"
    return "status 已脱敏"


# ---------------------------------------------------------------- 动态自检

def t_mcp_server():
    from src.kernel import mcp_server
    served = mcp_server.serve_http_in_thread(name="medwork")
    host, port = served["host"], served["port"]
    deadline = time.time() + 10
    connected = False
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                connected = True
                break
        except OSError:
            time.sleep(0.2)
    assert connected, f"MCP 端口 {host}:{port} 不可达"
    return f"{served['url']} tools={len(mcp_server.domain_tools.TOOL_FUNCTIONS)}"


def t_kernel():
    from src.kernel.kernel_client import KernelClient
    c = KernelClient()
    state = c.ensure_running()
    try:
        h = c.health()
        assert h.get("healthy") or h.get("version"), f"health 异常: {h}"
        api = c.probe_api()
        missing = [k for k, v in api.items() if not v]
        assert not missing, f"legacy V1 端点不可用: {missing}"
        return f"v{state.get('version')} pid={state.get('pid')} port={state.get('port')} api={api}"
    finally:
        c.stop()


def t_mcp_connected():
    """内核是否真的连上宿主 MCP（需要 MCP 服务与内核同时在线）。"""
    from src.kernel.kernel_boot import KernelBoot
    boot = KernelBoot()
    res = boot.start()
    try:
        assert res.get("ok"), f"启动失败: {res.get('error')}"
        text = boot.client.mcp_list() if boot.client else ""
        assert "medwork" in (text or "").lower(), f"mcp list 未包含 medwork: {text!r}"
        return (text or "").replace("\n", " | ")[:200]
    finally:
        boot.stop()


def t_session_ops():
    """方向 B 写路径：建会话 / 改标题 / 列消息（不需要 LLM 凭据）。"""
    from src.kernel.kernel_client import KernelClient
    c = KernelClient()
    c.ensure_running()
    try:
        created = c.create_session(title="kernel-selftest")
        sid = str((created or {}).get("id") or "")
        assert sid, f"create_session 未返回 id: {created}"
        patched = c.update_session_title(sid, "kernel-selftest-renamed")
        msgs = c.list_messages(sid)
        assert isinstance(msgs, list), f"list_messages 非列表: {type(msgs)}"
        titles = [str((s or {}).get("title") or "") for s in c.list_sessions()]
        assert any("renamed" in t for t in titles), f"标题未生效: {titles[:5]}"
        return f"session={sid[:18]} messages={len(msgs)} title_ok=True"
    finally:
        c.stop()


def t_agent_live():
    """内核侧默认 agent：/config.default_agent=loopx；/agent 含 loopx(primary)；
    且 V1 建会话可显式绑定 loopx（回显校验）。"""
    from src.kernel.kernel_client import KernelClient
    c = KernelClient()
    c.ensure_running()
    try:
        cfg = c._get("/config")
        got = cfg.get("default_agent") if isinstance(cfg, dict) else None
        assert got == "loopx", f"/config.default_agent 异常: {got!r}"
        agents = c._get("/agent")
        table = {str(a.get("name")): a for a in agents if isinstance(a, dict)}
        assert "loopx" in table, f"/agent 未列出 loopx: {sorted(table)[:12]}"
        assert str(table["loopx"].get("mode") or "") == "primary", "loopx 不是 primary"
        s = c.create_session(title="kernel-agent-selftest", agent="loopx")
        assert str((s or {}).get("agent") or "") == "loopx", f"会话 agent 未回显: {s}"
        sid = str((s or {}).get("id") or "")
        return f"default=loopx session={sid[:18]} agents={sorted(table)[:9]}"
    finally:
        c.stop()


def t_binding():
    """项目 <-> 会话 绑定读写（Step1 集成前提）。"""
    from src.kernel.kernel_boot import KernelBoot
    boot = KernelBoot()
    res = boot.start()
    assert res.get("ok"), f"启动失败: {res.get('error')}"
    try:
        sid1 = boot.ensure_project_session("kernel-binding-test")
        sid2 = boot.ensure_project_session("kernel-binding-test")
        assert sid1 == sid2, f"绑定未复用同一会话: {sid1} != {sid2}"
        boot.rename_project("kernel-binding-test", "kernel-binding-test-2")
        assert kc.get_project_session("kernel-binding-test") is None, "旧绑定键未迁移"
        assert kc.get_project_session("kernel-binding-test-2") == sid1, "新绑定键缺失"
        return f"session={sid1[:18]} rebind_ok=True"
    finally:
        boot.stop()


def t_no_leak():
    """停止内核后不得残留进程（npm 包装器会派生真正的服务子进程）。"""
    from src.kernel.kernel_client import KernelClient
    c = KernelClient()
    before = {r["pid"] for r in c.list_processes()}
    c.ensure_running()
    during = {r["pid"] for r in c.list_processes()}
    spawned = during - before
    assert spawned, "未观测到新进程，进程检测不可靠"
    c.stop()
    time.sleep(2.5)
    after = {r["pid"] for r in c.list_processes()}
    leaked = after & spawned
    assert not leaked, f"停止后残留子进程: {sorted(leaked)}"
    return f"spawned={len(spawned)} leaked=0"


def t_prompt():
    if not kc.auth_path().is_file():
        raise RuntimeError("无 auth.json，跳过（先运行 kernel_cli import-key）")
    from src.kernel.kernel_boot import KernelBoot
    boot = KernelBoot()
    res = boot.start()
    assert res.get("ok"), f"启动失败: {res.get('error')}"
    seen = []
    try:
        out = boot.run_task(
            "kernel-selftest",
            "请调用你的 MCP 工具 medwork_list_projects，然后只回答项目数量。",
            on_event=lambda ev: seen.append(ev.get("kind")),
            max_seconds=180,
        )
        assert out.get("ok"), f"回合失败: {out.get('error')}"
        tools = [k for k in seen if k == "tool"]
        assert tools, "未观察到 tool 事件（模型可能未调用宿主工具）"
        return f"events={len(seen)} tools={len(tools)} finish={out.get('finish')}"
    finally:
        boot.stop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="仅静态自检")
    ap.add_argument("--prompt", action="store_true", help="追加真实对话回合")
    args = ap.parse_args()

    print("=" * 70)
    print("opencode embedding self-check", "(offline)" if args.offline else "(full)")
    print("=" * 70)

    check("paths.exe", t_exe)
    check("paths.dirs", t_dirs)
    check("config.assets", t_assets)
    check("config.default_agent", t_default_agent_static)
    check("config.mcp", t_config)
    check("paths.env", t_env)
    check("boot.status_redaction", t_status_redaction)

    if not args.offline:
        check("mcp.server", t_mcp_server)
        check("kernel.spawn+api", t_kernel)
        check("kernel.session_ops", t_session_ops)
        check("kernel.agent_default", t_agent_live)
        check("kernel.mcp_connected", t_mcp_connected)
        check("kernel.project_binding", t_binding)
        check("kernel.no_process_leak", t_no_leak)
        if args.prompt:
            check("kernel.prompt+tool", t_prompt)

    failed = [r for r in RESULTS if not r["ok"]]
    print("-" * 70)
    print(f"total={len(RESULTS)} passed={len(RESULTS) - len(failed)} failed={len(failed)}")
    # 用 ensure_ascii=False 便于人读，但控制台已切 UTF-8；若仍失败则退回 ASCII
    try:
        print(json.dumps(RESULTS, ensure_ascii=False, indent=2))
    except Exception:
        print(json.dumps(RESULTS, ensure_ascii=True, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
