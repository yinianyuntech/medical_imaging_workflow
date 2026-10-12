#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kernel_cli —— 内核自检 / 运维命令行。

用法：
    python -m src.kernel.kernel_cli selftest          # 只读自检（不启动内核）
    python -m src.kernel.kernel_cli version           # 显示候选内核与版本
    python -m src.kernel.kernel_cli mcp-list          # opencode mcp list
    python -m src.kernel.kernel_cli import-key        # 导入宿主 LLM 凭据
    python -m src.kernel.kernel_cli probe             # 【会启动内核】探测 API 契约
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict

from . import kernel_config as kc
from . import kernel_paths as kp

# Windows 控制台默认 GBK，打印 ✓ / 中文会崩（playbook §8）。统一切到 UTF-8。
for _stream in ("stdout", "stderr"):
    try:
        getattr(sys, _stream).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def cmd_version(_: argparse.Namespace) -> Dict:
    rows = []
    for p in kp.opencode_candidates():
        exists = p.is_file()
        rows.append({
            "path": str(p),
            "exists": exists,
            "version": kp.opencode_version(p) if exists else "",
        })
    return {"candidates": rows, "selected": str(kp.opencode_exe()) if any(r["exists"] for r in rows) else ""}


def cmd_selftest(_: argparse.Namespace) -> Dict:
    out: Dict[str, Any] = {}
    out["kernel_home"] = str(kp.kernel_home())
    out["dirs"] = {
        "data": kp.data_dir().is_dir(),
        "config": kp.config_dir().is_dir(),
        "state": kp.state_dir().is_dir(),
        "cache": kp.cache_dir().is_dir(),
        "opencode_config": kp.opencode_config_dir().is_dir(),
    }
    try:
        exe = kp.opencode_exe()
        out["exe"] = {"path": str(exe), "version": kp.opencode_version(exe)}
        major = 0
        try:
            major = int((out["exe"]["version"] or "0").lstrip("v").split(".")[0])
        except Exception:
            major = 0
        out["api_family"] = "legacy-v1" if major and major < 2 else ("v2" if major >= 2 else "unknown")
        if major >= 2:
            out["warning"] = ("检测到 opencode >= 2.x；本嵌入按 legacy V1 契约实现。建议设置 "
                              "MIMW_OPENCODE_EXE 指向 1.x 内核。")
    except FileNotFoundError as e:
        out["exe"] = {"error": str(e)}

    cfg = kc.read_config()
    out["mcp"] = cfg.get("mcp", {})
    out["model"] = cfg.get("model", "")
    out["auth_present"] = kc.auth_path().is_file()
    out["auth_providers"] = sorted(kc.read_auth().keys())
    out["assets_root"] = str(kp.assets_root())
    out["bindings"] = kc.load_bindings()
    out["ok"] = bool(out.get("exe", {}).get("path")) and out["auth_present"]
    return out


def cmd_mcp_list(_: argparse.Namespace) -> Dict:
    from .kernel_client import KernelClient
    c = KernelClient()
    return {"raw": c.mcp_list()}


def cmd_import_key(args: argparse.Namespace) -> Dict:
    kp.ensure_kernel_dirs()
    prof = None
    if args.key:
        prof = {"provider": args.provider or "deepseek", "api_key": args.key}
    return kc.import_host_llm_key(prof)


def cmd_probe(args: argparse.Namespace) -> Dict:
    from .kernel_client import KernelClient
    kp.ensure_kernel_dirs()
    kc.install_builtin_assets()
    c = KernelClient(port=int(args.port or 0))
    state = c.ensure_running()
    try:
        return {
            "kernel": state,
            "health": _safe(lambda: c.health()),
            "api": c.probe_api(),
            "sessions": _safe(lambda: c.list_sessions()),
            "questions": _safe(c.legacy_questions),
            "permissions": _safe(c.legacy_permissions),
            "mcp_list": c.mcp_list(),
        }
    finally:
        if not args.keep:
            c.stop()


def _safe(fn):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="kernel_cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("version").set_defaults(func=cmd_version)
    sub.add_parser("selftest").set_defaults(func=cmd_selftest)
    sub.add_parser("mcp-list").set_defaults(func=cmd_mcp_list)

    p_key = sub.add_parser("import-key")
    p_key.add_argument("--provider", default="deepseek")
    p_key.add_argument("--key", default="")
    p_key.set_defaults(func=cmd_import_key)

    p_probe = sub.add_parser("probe")
    p_probe.add_argument("--port", type=int, default=0)
    p_probe.add_argument("--keep", action="store_true")
    p_probe.set_defaults(func=cmd_probe)

    args = parser.parse_args(argv)
    result = args.func(args)
    try:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    except Exception:
        print(json.dumps(result, ensure_ascii=True, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
