#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：provider 级错误必须被**显式暴露**，不能静默。

背景（实测发现）
----------------
deepseek 用无效 key 时，legacy V1 的 `POST /session/:id/message` **不抛异常**，
而是把错误塞在返回体的 `info.error` 里：

    {"info": {"error": {"name":"APIError",
       "data": {"message":"Authentication Fails, Your api key: ****0000 is invalid",
                "statusCode":401,
                "metadata":{"url":"https://api.deepseek.com/chat/completions"}}}},
     "parts": []}

原来的 `KernelDriver.run_turn` 只从**异常**取 error → 这种情况返回 `ok: True`
且 parts 为空，面板既不报错也不出结果 → **静默失败**。

本测试**不需要有效凭据**：故意写入一个无效 key，断言
  * `run_turn` 必须 `ok == False`
  * `error` / `provider_error` 非空且能看出是鉴权问题
  * 不把错误当成"成功空回复"

跑完会**恢复原来的 auth.json**（不留假凭据）。

用法：
    python scripts/test_kernel_provider_error.py
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

OUT = []
RESULTS = []


def say(s=""):
    OUT.append(str(s))
    print(s)


def chk(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    say(f"   [{'PASS' if ok else 'FAIL'}] {label}: {detail}")


original_auth = None
try:
    original_auth = kc.read_auth()
except Exception:
    original_auth = None

boot = None
try:
    say("=" * 88)
    say("provider 错误暴露回归测试（用无效 key，无需真实凭据）")
    say("=" * 88)
    say(f"   原始 auth.json = {list((original_auth or {}).keys()) or '（无）'}")

    # 故意写入无效 key
    kc.write_auth({"deepseek": {"type": "api", "key": "sk-INVALID-REGRESSION-0000"}})
    say("   已写入无效 key: sk-INVALID-REGRESSION-0000")

    boot = KernelBoot(model="deepseek/deepseek-flash")
    st = boot.start(bridge=None)
    say(f"   start ok={st.get('ok')} version={(st.get('kernel') or {}).get('version')}")

    say("")
    say("── 投递一轮（预期在 provider 处 401） ──")
    t0 = time.time()
    res = boot.driver().run_turn(
        boot.ensure_project_session("provider-error-test"),
        "请只回答两个字：收到",
        max_seconds=120,
    )
    dt = time.time() - t0
    say(f"   耗时 {dt:.2f}s")
    say(f"   ok={res.get('ok')}  finish={res.get('finish')!r}  "
        f"parts={len(res.get('parts') or [])}")
    say(f"   error={str(res.get('error'))[:260]}")
    say(f"   provider_error={str(res.get('provider_error'))[:200]}")

    chk("run_turn 报 ok=False（未把 401 当成功）", res.get("ok") is False,
        f"ok={res.get('ok')}")
    err_all = (str(res.get("error") or "") + " " +
               str(res.get("provider_error") or "")).lower()
    chk("错误文本非空", bool(err_all.strip()),
        f"len={len(err_all.strip())}")
    chk("能看出是鉴权/provider 问题",
        any(k in err_all for k in ("401", "auth", "invalid", "api key", "鉴权", "密钥")),
        err_all[:120])
    chk("parts 为空（与本结论一致）", not (res.get("parts") or []),
        f"parts={len(res.get('parts') or [])}")

finally:
    if boot is not None:
        try:
            boot.stop()
        except Exception:
            pass
        time.sleep(1.5)
    # 恢复原 auth.json（不留假凭据）
    try:
        if original_auth:
            kc.write_auth(original_auth)
            say(f"   已恢复原 auth.json ({list(original_auth.keys())})")
        else:
            import pathlib
            p = kc.auth_path() if hasattr(kc, "auth_path") else None
            if p and os.path.exists(str(p)):
                os.remove(str(p))
                say("   已删除测试用的 auth.json（原本就没有）")
    except Exception as e:  # noqa: BLE001
        say(f"   恢复 auth.json 失败: {e}")

failed = [r for r in RESULTS if not r[1]]
say("")
say("=" * 88)
say(f"total={len(RESULTS)} passed={len(RESULTS) - len(failed)} failed={len(failed)}")
for l, ok, d in RESULTS:
    if not ok:
        say(f"   !! {l}: {d}")
say("RESULT: " + ("PASS" if not failed else "ISSUES"))

rep = os.path.join("docs", "screenshots", "kernel_provider_error.txt")
os.makedirs(os.path.dirname(rep), exist_ok=True)
with open(rep, "w", encoding="utf-8") as fh:
    fh.write("\n".join(OUT) + "\n")
print("\n报告 ->", os.path.abspath(rep))
sys.exit(0 if not failed else 1)
