#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_opencode_delegation.py —— 委托式写作管线端到端自检。

验证：
  1. run_delegated_pipeline 能把一次完整写作任务委托给内嵌 opencode 会话；
  2. 返回结构可被旧 UI 消费（status/outline/units/meta/full_text）；
  3. 会话（共享上下文）正确建立；收尾无进程泄漏。

用法：
    python scripts/test_opencode_delegation.py [project_id] [--max 420]
"""

import argparse
import io
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

from src.kernel.kernel_boot import KernelBoot                        # noqa: E402
from src.kernel.inference_gateway import bind_boot                   # noqa: E402
from src.kernel.kernel_client import KernelClient                    # noqa: E402
from src.ai.opencode_delegation import run_delegated_pipeline        # noqa: E402

RESULTS = []


def chk(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    print(f"   [{'PASS' if ok else 'FAIL'}] {label}: {detail}")


def _pids():
    try:
        return {p["pid"] for p in KernelClient().list_processes()}
    except Exception:
        return set()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_id", nargs="?", default="project_1791774057")
    ap.add_argument("--max", type=float, default=420.0, help="本轮最长秒数")
    args = ap.parse_args()

    print("=" * 88)
    print(f"委托式写作管线自检（内嵌 opencode · project={args.project_id} · max={args.max:.0f}s）")
    print("=" * 88)

    pre = _pids()
    boot = KernelBoot()
    bind_boot(boot)

    events = []
    streams = []

    t0 = time.time()
    result = run_delegated_pipeline(
        project_id=args.project_id,
        project_name="",
        raw_content="(自检：请直接用 medwork 工具读取该项目真实数据后完成写作)",
        template_constraints_json="",
        on_progress=lambda m: events.append(str(m)),
        on_stream=lambda t: streams.append(str(t)),
        max_seconds=float(args.max),
    )
    dt = time.time() - t0

    status = str(result.get("status") or "")
    print(f"   status={status!r} engine={result.get('engine')!r} "
          f"elapsed={result.get('elapsed_s')}s session={str(result.get('session_id'))[:22]}")
    if status != "ok":
        print(f"   error={result.get('error')}")
    else:
        units = result.get("units") or {}
        nonempty = [k for k, v in units.items()
                    if isinstance(v, dict) and str(v.get("content") or "").strip()]
        ft = str(result.get("full_text") or "")
        print(f"   units_nonempty={nonempty} refs={len(result.get('references') or [])} "
              f"full_text_len={len(ft)}")
        print(f"   title={json.dumps((result.get('outline') or {}).get('title'), ensure_ascii=False)}")
        print(f"   progress_events={len(events)} stream_chunks={len(streams)}")

    chk("引擎=opencode", result.get("engine") == "opencode", str(result.get("engine")))
    if status == "ok":
        units = result.get("units") or {}
        nonempty = [k for k, v in units.items()
                    if isinstance(v, dict) and str(v.get("content") or "").strip()]
        ft = str(result.get("full_text") or "")
        chk("结构可用（units 非空 ≥2）", len(nonempty) >= 2, str(nonempty))
        chk("full_text 足够长", len(ft) >= 500, f"len={len(ft)}")
        chk("会话建立", bool(result.get("session_id")), str(result.get("session_id"))[:24])
        chk("有过程事件", len(events) >= 1, f"events={len(events)}")
    else:
        # blocked 也必须给出可读错误（供 UI 渲染）
        chk("失败可读（有 error 文本）", bool(str(result.get("error") or "").strip()),
            str(result.get("error"))[:160])

    # 收尾
    during = _pids()
    spawned = during - pre
    boot.stop()
    time.sleep(2.0)
    after = _pids()
    chk("收尾无残留", not (spawned & after), f"spawned={sorted(spawned)} leaked={sorted(spawned & after)}")
    chk("未误杀既有进程", not (pre - after), f"collateral={sorted(pre - after)}")

    failed = [r for r in RESULTS if not r[1]]
    print("-" * 88)
    print(f"total={len(RESULTS)} passed={len(RESULTS) - len(failed)} failed={len(failed)}")
    print(f"总耗时 {dt:.1f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
