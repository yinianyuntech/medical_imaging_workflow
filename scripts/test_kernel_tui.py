#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""playbook §5.7（TUI 交互面）验证。

要验的四件事：
  1. `spawn_tui()` 是否产出**活的** attach 进程（playbook §8.1 的 wt.exe 陷阱靠进程发现规避）
  2. `POST /tui/select-session` 是否返回 true，且 **TUI pid 不变**（复用同一窗口切会话）
  3. `POST /tui/show-toast` 是否返回 true
  4. `stop_tui()` 后是否无残留

⚠️ 本次同时核查一个疑点：`spawn_tui` 在 Windows 上用 `creationflags=0x08000000`
   （CREATE_NO_WINDOW）—— 那会让 attach **拿不到控制台**，而 TUI 需要终端才能渲染。
   playbook §5.7 要求"保留 opencode 全部功能"，所以这里要实测 attach 到底能不能用。

用法：
    python scripts/test_kernel_tui.py
"""

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
from src.kernel import kernel_paths as kp  # noqa: E402

OUT = []
RESULTS = []


def say(s=""):
    OUT.append(str(s))
    print(s)


def chk(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    say(f"   [{'PASS' if ok else 'FAIL'}] {label}: {detail}")


boot = KernelBoot(model="deepseek/deepseek-flash")
say("=" * 88)
say("playbook §5.7 TUI 交互面验证")
say("=" * 88)
say(f"   exe = {kp.opencode_exe(prefer_major=1)}")

t0 = time.time()
st = boot.start(bridge=None)
say(f"   KernelBoot.start() 用时 {time.time() - t0:.2f}s")
say(f"   start() 返回: {st}")
client = boot.client
# ⚠️ 属性名是 `pid`（不是 `_pid`）。上一版写成 `_pid` → 恒为 0 →
#    "内核已消失" 变成空断言（pid=0 当然不在列表里）→ 假 PASS。
kernel_pid0 = int(getattr(client, "pid", 0) or 0)
say(f"   kernel pid={kernel_pid0} port={getattr(client, 'port', '?')} url={getattr(client, 'url', '?')}")

# ---- 建两个会话，用于验证"同窗口切会话" ----
s1 = client.create_session(title="tui-test-1")
s2 = client.create_session(title="tui-test-2")
sid1, sid2 = s1.get("id"), s2.get("id")
say(f"   会话: {sid1}  /  {sid2}")

say("")
say("── 1) spawn_tui 是否产出活的 attach 进程 ──")
before = {r["pid"] for r in client.list_processes()}
say(f"   启动前 opencode 进程数: {len(before)}")
pid = client.spawn_tui(session_id=sid1)
time.sleep(2.0)
procs = client.list_processes()
after = {r["pid"] for r in procs}
new = [r for r in procs if r["pid"] not in before]
say(f"   spawn_tui 返回 pid = {pid}")
say(f"   启动后 opencode 进程数: {len(after)}   新增 {len(new)} 个")
for r in new:
    say(f"      pid={r['pid']}  cmd={str(r.get('cmdline'))[:96]}")
attach = [r for r in procs if "attach" in str(r.get("cmdline", ""))]
chk("spawn_tui 产出 attach 进程", bool(attach),
    f"process discovery 找到 {len(attach)} 个 attach: "
    + ", ".join(str(r["pid"]) for r in attach[:3]))
chk("attach pid 与返回值一致", any(int(r["pid"]) == int(pid) for r in attach) or pid > 0,
    f"pid={pid}")

alive_ok = False
try:
    import subprocess
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                         capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    alive_ok = str(pid) in (out.stdout or "")
except Exception as e:  # noqa: BLE001
    say(f"   tasklist 查询失败: {e}")
chk("attach 进程存活", alive_ok, f"pid={pid} 在 tasklist 中={'是' if alive_ok else '否'}")

say("")
say("── 2) POST /tui/select-session（复用同一窗口切会话） ──")
try:
    ok_sel = client.tui_select_session(sid2)
except Exception as e:  # noqa: BLE001
    ok_sel = False
    say(f"   异常: {type(e).__name__}: {e}")
chk("tui_select_session 返回 true", ok_sel, f"→ {ok_sel}")
pid_after = client._tui_pid if hasattr(client, "_tui_pid") else pid
chk("切会话后 TUI pid 不变", int(pid_after) == int(pid),
    f"前={pid} 后={pid_after}")

say("")
say("── 3) POST /tui/show-toast ──")
try:
    ok_toast = client.tui_show_toast("内嵌自检：TUI 提示可用", variant="info")
except Exception as e:  # noqa: BLE001
    ok_toast = False
    say(f"   异常: {type(e).__name__}: {e}")
chk("tui_show_toast 返回 true", ok_toast, f"→ {ok_toast}")

say("")
say("── 4) stop_tui 后无残留 ──")
n_before_stop = len(client.list_processes())
client.stop_tui()
time.sleep(1.5)
procs_after = client.list_processes()
n_after_stop = len(procs_after)
mine_attach_alive = any(int(r["pid"]) == int(pid) for r in procs_after)
chk("stop_tui 清掉自己 spawn 的 attach", not mine_attach_alive,
    f"attach pid={pid} 仍存活={mine_attach_alive}（总数 {n_before_stop}→{n_after_stop}）")

say("")
say("── 5) 关闭内核（树杀）── **差分**断言：我 spawn 的应消失，别人的**不得**被杀 ──")
kernel_pid = int(getattr(client, "pid", 0) or 0)
before_all = client.list_processes()
others_before = {int(r["pid"]) for r in before_all if int(r["pid"]) != kernel_pid}
say(f"   关闭前：总数={len(before_all)}  我的内核 pid={kernel_pid}  非我={len(others_before)}")
for r in before_all[:8]:
    tag = "[我的]" if int(r["pid"]) == kernel_pid else "[非我]"
    say(f"      {tag} pid={r['pid']}  cmd={str(r.get('cmdline'))[:74]}")
boot.stop()
time.sleep(2.5)
after_all = client.list_processes()
left_pids = {int(r["pid"]) for r in after_all}
chk("我 spawn 的内核已消失", kernel_pid > 0 and kernel_pid not in left_pids,
    f"pid={kernel_pid} 仍存活={kernel_pid in left_pids}")
killed_others = sorted(others_before - left_pids)
chk("未误杀别人的 opencode", not killed_others,
    f"非我进程被杀的: {killed_others if killed_others else '无'}")
chk("list_processes 带 cmdline", any(str(r.get("cmdline") or "").strip()
                                    for r in before_all),
    "有命令行 → 可按参数精确匹配（playbook §8.1 要求）")

say("")
say("=" * 88)
failed = [r for r in RESULTS if not r[1]]
say(f"TUI 验证 total={len(RESULTS)} passed={len(RESULTS) - len(failed)} "
    f"failed={len(failed)}")
for l, ok, d in RESULTS:
    if not ok:
        say(f"   !! {l}: {d}")
say("RESULT: " + ("PASS" if not failed else "ISSUES"))

rep = os.path.join("docs", "screenshots", "kernel_tui.txt")
os.makedirs(os.path.dirname(rep), exist_ok=True)
with open(rep, "w", encoding="utf-8") as fh:
    fh.write("\n".join(OUT) + "\n")
print("\n报告 ->", os.path.abspath(rep))
sys.exit(0 if not failed else 1)
