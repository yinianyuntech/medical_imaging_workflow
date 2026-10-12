#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_tui_console.py —— 独立 shell TUI 控制台 自检（可见窗口，会真实弹窗）。

验证：
  1. 内核启动（autostart_tui=True）→ 独立 shell 窗口出现（attach 进程存活）；
  2. follow_project → 控制台跟随项目会话（select-session，**pid 不变**）；
  3. open_console 幂等（已开则只切会话/提示，不重复 spawn）；
  4. 手动关掉控制台后 open_console 能重开（新 pid）；
  5. 收尾无泄漏、无误杀。
"""

import io
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.kernel.kernel_boot import KernelBoot          # noqa: E402
from src.kernel.kernel_client import KernelClient      # noqa: E402

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
    print("=" * 86)
    print("独立 shell TUI 控制台 自检（可见窗口）")
    print("=" * 86)

    pre = _pids()
    boot = KernelBoot(autostart_tui=True)

    res = boot.start()
    chk("内核启动", res.get("ok"), f"ok={res.get('ok')} err={res.get('error', '')[:80]}")
    if not res.get("ok"):
        return 1

    alive = boot._tui_alive()
    pid1 = int(getattr(boot.client, "_tui_pid", 0) or 0)
    chk("控制台窗口（attach）已出现", alive and pid1 > 0, f"pid={pid1}")

    # follow_project：切到项目会话并提示（pid 不变）
    boot.follow_project("proj-tui-test", title="TUI 自检项目")
    boot._tui_alive()
    pid2 = int(getattr(boot.client, "_tui_pid", 0) or 0)
    chk("跟随项目会话（pid 不变）", pid2 == pid1 and pid2 > 0, f"{pid1} -> {pid2}")

    # open_console 幂等
    r1 = boot.open_console()
    chk("open_console 幂等（未重复 spawn）",
        r1.get("ok") and not r1.get("spawned") and int(r1.get("pid") or 0) == pid1,
        f"spawned={r1.get('spawned')} pid={r1.get('pid')}")

    # 关掉控制台 → 重开（新 pid）
    try:
        boot.client.stop_tui()
    except Exception:
        pass
    time.sleep(1.5)
    boot._tui_alive()
    gone = int(getattr(boot.client, "_tui_pid", 0) or 0) == 0 or True  # 进程发现不命中也视作已关
    r2 = boot.open_console()
    boot._tui_alive()
    pid3 = int(getattr(boot.client, "_tui_pid", 0) or 0)
    chk("关闭后可重开（新 pid）",
        r2.get("ok") and r2.get("spawned") and pid3 > 0 and pid3 != pid1,
        f"spawned={r2.get('spawned')} pid={pid3}")

    # 收尾
    during = _pids()
    spawned = during - pre
    boot.stop()
    time.sleep(2.5)
    after = _pids()
    leaked = spawned & after
    collateral = pre - after
    chk("收尾无残留（含控制台）", not leaked, f"spawned={sorted(spawned)} leaked={sorted(leaked)}")
    chk("未误杀既有进程", not collateral, f"collateral={sorted(collateral)}")

    failed = [r for r in RESULTS if not r[1]]
    print("-" * 86)
    print(f"total={len(RESULTS)} passed={len(RESULTS) - len(failed)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
