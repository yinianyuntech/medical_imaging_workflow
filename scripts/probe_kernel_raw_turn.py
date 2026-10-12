#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定位"空回复"（修正版：用真实的 _post/_get）。

上一轮探针方法名写错（`_request` 不存在）→ 没拿到原始载荷。
本轮用正确的方法，一次性拿全四份证据：
  1. 原始 POST /session/:id/message 返回（判断是 error 还是空 parts）
  2. 该会话的消息列表（playbook 说工具调用要在这里看）
  3. 内核眼里的 MCP 工具面（`opencode mcp list`）
  4. 内核日志里与 provider/错误相关的行
"""

import json
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

from src.kernel.kernel_boot import KernelBoot  # noqa: E402
from src.kernel import kernel_config as kc  # noqa: E402
from src.kernel import kernel_paths as kp  # noqa: E402

OUT = []


def say(s=""):
    OUT.append(str(s))
    print(s)


def jdump(o, limit=2600):
    try:
        return json.dumps(o, ensure_ascii=False, indent=1)[:limit]
    except Exception:
        return str(o)[:limit]


boot = KernelBoot(model="deepseek/deepseek-flash")
st = boot.start(bridge=None)
client = boot.client
say(f"auth.json providers = {list((kc.read_auth() or {}).keys())}")
say(f"kernel url = {client.url}  pid={client.pid}")

say("")
say("=== 3) 内核眼里的 MCP 工具面 ===")
try:
    txt = client.mcp_list(timeout=60)
    say(txt[:900] if txt else "(空)")
except Exception as e:  # noqa: BLE001
    say(f"  mcp_list 失败 {type(e).__name__}: {e}")

s = client.create_session(title="raw-dump2")
sid = s.get("id")
say(f"session = {sid}")

say("")
say("=== 1) 原始 POST /session/:id/message 返回 ===")
raw = None
try:
    raw = client._post(f"/session/{sid}/message",
                       {"parts": [{"type": "text", "text": "请只回答两个字：收到"}],
                        "model": {"providerID": "deepseek", "modelID": "deepseek-flash"}})
except Exception as e:  # noqa: BLE001
    say(f"  抛异常 {type(e).__name__}: {str(e)[:300]}")
say(jdump(raw))

say("")
say("=== 2) 该会话的消息列表 ===")
try:
    msgs = client._get(f"/session/{sid}/message")
    if isinstance(msgs, list):
        say(f"  消息数 = {len(msgs)}")
        for m in msgs[:4]:
            info = m.get("info") or {}
            parts = m.get("parts") or []
            say(f"  --- role={info.get('role')} finish={info.get('finish')} "
                f"error={info.get('error')} parts={len(parts)}")
            for p in parts[:6]:
                t = p.get("type") if isinstance(p, dict) else "?"
                txt = ""
                if isinstance(p, dict):
                    txt = str(p.get("text") or p.get("tool") or p.get("state") or "")
                say(f"      [{t}] {txt[:150]}")
    else:
        say(jdump(msgs))
except Exception as e:  # noqa: BLE001
    say(f"  失败 {type(e).__name__}: {e}")

boot.stop()
time.sleep(1.5)

say("")
say("=== 4) 内核日志里 error/auth/provider 相关行 ===")
log = kp.kernel_home() / "data" / "opencode" / "log" / "opencode.log"
try:
    lines = open(log, encoding="utf-8", errors="replace").read().splitlines()
    keys = ("error", "auth", "401", "403", "provider", "deepseek", "fail",
            "abort", "tool", "mcp", "medwork")
    hits = [ln for ln in lines[-220:]
            if any(k in ln.lower() for k in keys)]
    for ln in hits[-26:]:
        say("   " + ln[:200])
    if not hits:
        say("   （无相关行）")
except Exception as e:  # noqa: BLE001
    say(f"  读取失败: {e}")

rep = os.path.join("docs", "screenshots", "kernel_raw_turn.txt")
with open(rep, "w", encoding="utf-8") as fh:
    fh.write("\n".join(OUT) + "\n")
print("\n报告 ->", os.path.abspath(rep))
