#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实对话回合验证（playbook §13 的待办）。

目的：**把"缺凭据"这个阻塞点精确化**。

用当前 auth.json 里的 key 打一轮真实对话：
  * 若模型正常回话 → 全链路打通（包括模型）
  * 若在 **provider 处** 报鉴权失败 → 证明会话/投递/请求体/模型路由
    **全部正确**，唯一缺的就是一个有效 key
  * 若是其它错误（ModelUnavailableError / 404 / 超时）→ 说明还有别的问题要修

顺带验证：MCP 是否 `connected`（这是模型能调用宿主工具的前提）。

用法：
    python scripts/test_kernel_turn.py            # 用现有 auth.json
    python scripts/test_kernel_turn.py --prompt "..."   # 自定义提示
"""

import argparse
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

OUT = []


def say(s=""):
    OUT.append(str(s))
    print(s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="请只回答两个字：收到")
    ap.add_argument("--model", default="deepseek/deepseek-flash")
    args = ap.parse_args()

    say("=" * 88)
    say("真实对话回合验证")
    say("=" * 88)

    auth = kc.read_auth() or {}
    provs = list(auth.keys())
    say(f"   auth.json providers: {provs or '（空）'}")
    for k in provs:
        v = auth.get(k) or {}
        key = str(v.get("key") or "")
        say(f"     {k}: type={v.get('type')}  key={'len(%d)' % len(key) if key else '空'}")
    say(f"   目标模型: {args.model}")
    say(f"   提示词  : {args.prompt[:60]}")

    boot = KernelBoot(model=args.model)
    t0 = time.time()
    st = boot.start(bridge=None)
    say("")
    say(f"── KernelBoot.start() {time.time() - t0:.2f}s ──")
    say(f"   ok={st.get('ok')}  kernel.running={(st.get('kernel') or {}).get('running')}"
        f"  version={(st.get('kernel') or {}).get('version')}")
    say(f"   api={((st.get('kernel') or {}).get('api'))}")
    say(f"   mcp_url={st.get('mcp_url')}")
    say(f"   auth={st.get('auth')}")

    client = boot.client

    say("")
    say("── 1) MCP 是否已连接（模型调用宿主工具的前提） ──")
    mcp_txt = ""
    try:
        mcp_txt = client.mcp_list_text() if hasattr(client, "mcp_list_text") else ""
    except Exception as e:  # noqa: BLE001
        say(f"   mcp_list 调用失败: {e}")
    if mcp_txt:
        low = mcp_txt.lower()
        say(f"   medwork connected = {'medwork connected' in low}")
        say("   " + "\n   ".join(mcp_txt.strip().splitlines()[:6]))
    else:
        try:
            ok_mcp = boot._verify_mcp() if hasattr(boot, "_verify_mcp") else None
            say(f"   通过 boot 校验: {ok_mcp}")
        except Exception as e:  # noqa: BLE001
            say(f"   校验异常: {e}")

    say("")
    say("── 2) 建会话 ──")
    s = client.create_session(title="turn-verify")
    sid = s.get("id")
    say(f"   session={sid}")

    say("")
    say("── 3) 投递一轮（legacy V1 阻塞式 prompt） ──")
    say("   这是本 playbook §13 未完成的那一步。")
    t1 = time.time()
    err = None
    res = None
    try:
        res = client.prompt_legacy(sid, args.prompt)
    except Exception as e:  # noqa: BLE001
        err = e
    dt = time.time() - t1
    say(f"   耗时 {dt:.2f}s")

    verdict = ""
    if err is not None:
        say(f"   ★ 抛异常: {type(err).__name__}: {str(err)[:400]}")
        low = str(err).lower()
        if any(k in low for k in ("401", "403", "unauthor", "invalid api key",
                                  "authentication", "api key", "invalid_api_key",
                                  "no auth", "没有", "密钥")):
            verdict = ("PROVIDER_AUTH  —— 链路全通，只差有效 key ✅"
                       "（会话/投递/请求体/模型路由均正确）")
        elif "modelunavailable" in low or "model unavailable" in low:
            verdict = "MODEL_UNAVAILABLE —— 走了 V2 面？需检查 api_family"
        else:
            verdict = "OTHER —— 还有别的问题需要定位"
    else:
        parts = (res or {}).get("parts") or []
        info = (res or {}).get("info") or {}
        texts = [p.get("text", "") for p in parts if isinstance(p, dict)
                 and p.get("type") == "text"]
        say(f"   info.finish={info.get('finish')}  parts={len(parts)}")
        for t in texts[:4]:
            say(f"   > {str(t)[:150]}")
        say(f"   工具调用 parts: "
            f"{sum(1 for p in parts if isinstance(p, dict) and p.get('type') in ('tool','tool-invocation'))}")
        verdict = ("FULL_TURN_OK —— 模型已回话，全链路打通 ✅"
                   if texts else "EMPTY_REPLY —— 有返回但无文本")

    say("")
    say(f"   判定: {verdict}")

    say("")
    say("── 4) 收尾 ──")
    boot.stop()
    time.sleep(2.0)
    left = [r for r in client.list_processes()
            if int(r["pid"]) == int(getattr(client, "pid", 0) or 0)]
    say(f"   内核已关闭，残留={len(left)}")

    rep = os.path.join("docs", "screenshots", "kernel_turn.txt")
    os.makedirs(os.path.dirname(rep), exist_ok=True)
    with open(rep, "w", encoding="utf-8") as fh:
        fh.write("\n".join(OUT) + "\n")
    print("\n报告 ->", os.path.abspath(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
