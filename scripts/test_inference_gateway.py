#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_inference_gateway.py —— 推理网关（全部推理转入内嵌 opencode）端到端自检。

验证四件事（真实调用，无需人工）：
  1. 网关可启动/接管内核，并把一轮推理投递进内嵌 opencode 会话（简单回话）；
  2. **与 Step2 管线同形**：`OpenCodeLLMService.generate` 走通
     `plan_with_llm`（llm_guided_sklearn 的第一个真实推理点），并返回可解析计划；
  3. **共享上下文**：两轮推理落在同一项目会话（消息累计）；
  4. 收尾无进程泄漏。

用法：
    python scripts/test_inference_gateway.py            # 完整（会起内核，2~4 分钟）
    python scripts/test_inference_gateway.py --prompt-only   # 只测简单回话
"""

import argparse
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

from src.kernel.kernel_boot import KernelBoot                      # noqa: E402
from src.kernel.inference_gateway import (                          # noqa: E402
    OpenCodeLLMService, bind_boot, get_gateway,
)
from src.services.llm_guided_sklearn_pipeline import plan_with_llm  # noqa: E402

RESULTS = []


def chk(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    print(f"   [{'PASS' if ok else 'FAIL'}] {label}: {detail}")


def count_roles(msgs):
    roles = {"user": 0, "assistant": 0}
    for m in msgs or []:
        info = m.get("info") if isinstance(m, dict) and isinstance(m.get("info"), dict) else m
        role = str((info or {}).get("role") or "").strip()
        if role in roles:
            roles[role] += 1
    return roles


def _pids():
    from src.kernel.kernel_client import KernelClient
    try:
        return {p["pid"] for p in KernelClient().list_processes()}
    except Exception:
        return set()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt-only", action="store_true")
    args = ap.parse_args()

    print("=" * 88)
    print("推理网关自检（全部推理转入内嵌 opencode · 共享上下文）")
    print("=" * 88)

    boot = KernelBoot()
    bind_boot(boot)
    gw = get_gateway()
    service = OpenCodeLLMService(gw)
    project_id = "infer-gw-selftest"

    # 差分基准：机器上可能本来就有别人的 opencode 进程（playbook §8 教训）
    pre = _pids()

    t0 = time.time()
    out1 = service.generate("", "请只回答两个字：收到")
    dt1 = time.time() - t0
    chk("网关简单回话", out1.get("success") and "收到" in (out1.get("response") or ""),
        f"{dt1:.1f}s reply={json.dumps((out1.get('response') or '')[:40], ensure_ascii=False)}"
        f" session={str(out1.get('session_id'))[:20]}"
        + (f" err={out1.get('error')}" if not out1.get("success") else ""))
    sid = str(out1.get("session_id") or "")

    if not args.prompt_only:
        # ---- Step2 管线的第一个真实推理点：llm_guided plan ----
        materials = "示例项目：120 例患者的随访表，含年龄、BMI、结局标签（0/1）。"
        profile = {
            "columns": [
                {"name": "age", "dtype": "int"},
                {"name": "bmi", "dtype": "float"},
                {"name": "outcome", "dtype": "int"},
            ],
            "n_rows": 120,
            "numeric_columns": ["age", "bmi", "outcome"],
            "categorical_columns": [],
        }
        t1 = time.time()
        plan = plan_with_llm(service, "", materials, profile)
        dt2 = time.time() - t1
        mode = str(plan.get("mode") or "") if isinstance(plan, dict) else "invalid"
        tasks = plan.get("tasks") if isinstance(plan, dict) else None
        ok2 = isinstance(tasks, list) and mode not in ("llm_failed", "llm_parse_failed")
        chk("Step2 挖掘计划（plan_with_llm）", ok2,
            f"{dt2:.1f}s mode={mode!r} tasks={len(tasks or [])} "
            f"types={[t.get('type') for t in (tasks or [])][:4]}")

        # ---- 项目绑定：交互反馈注入项目会话（≠ _inference） ----
        try:
            from src.kernel.inference_gateway import OpenCodeLLMService as _SVC
            svc_p = _SVC()
            svc_p.set_project(project_id)
            o = svc_p.generate("", "请只回答两个字：收到")
            sid_proj = boot.ensure_project_session(project_id)
            sid_inf = boot.ensure_project_session("_inference")
            chk("反馈注入项目会话（≠_inference）",
                o.get("session_id") == sid_proj and sid_proj != sid_inf,
                f"call={str(o.get('session_id'))[:18]} proj={sid_proj[:18]} inf={sid_inf[:18]}")
        except Exception as e:  # noqa: BLE001
            chk("反馈注入项目会话（≠_inference）", False, f"{type(e).__name__}: {e}")

        # ---- 共享上下文：两轮都在同一会话 ----
        try:
            msgs = boot.client.list_messages(sid) if boot.client else []
            roles = count_roles(msgs)
            chk("共享上下文（同一会话累计）",
                roles["user"] >= 2 and roles["assistant"] >= 2,
                f"session={sid[:20]} user={roles['user']} assistant={roles['assistant']}")
        except Exception as e:  # noqa: BLE001
            chk("共享上下文（同一会话累计）", False, f"{type(e).__name__}: {e}")

    # ---- 收尾（差分断言：只关心"我 spawn 的消失 + 别人的没被杀"）----
    try:
        during = _pids()
        spawned = during - pre
        boot.stop()
        time.sleep(2.0)
        after = _pids()
        leaked = spawned & after
        collateral = pre - after
        chk("收尾无残留", not leaked, f"spawned={sorted(spawned)} leaked={sorted(leaked)}")
        chk("未误杀既有进程", not collateral, f"collateral={sorted(collateral)}")
    except Exception as e:  # noqa: BLE001
        chk("收尾无残留", False, f"{type(e).__name__}: {e}")

    failed = [r for r in RESULTS if not r[1]]
    print("-" * 88)
    print(f"total={len(RESULTS)} passed={len(RESULTS) - len(failed)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
