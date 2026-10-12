#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kernel_config —— 隔离 home 的配置 / 凭据 / 项目<->会话 绑定 / 随包资产安装。"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from . import kernel_paths as kp

DEFAULT_MODEL = "deepseek/deepseek-flash"
# 内嵌 opencode 的默认 agent：随包定义在 kernel_assets/agent/loopx.md，
# 启动时经 install_builtin_assets() 安装进隔离 home，并以 `default_agent` 写入配置。
DEFAULT_AGENT = "loopx"


# ---------------------------------------------------------------- opencode.json

def config_path() -> Path:
    return kp.opencode_config_dir() / "opencode.json"


def read_config() -> Dict:
    p = config_path()
    if not p.is_file():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def write_config(cfg: Dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cfg or {}, f, ensure_ascii=False, indent=2)


def merge_config(patch: Dict) -> Dict:
    cfg = read_config()
    _deep_merge(cfg, patch or {})
    write_config(cfg)
    return cfg


def _deep_merge(dst: Dict, src: Dict) -> None:
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v


def set_mcp_server(name: str, url: str, timeout_ms: int = 600000, enabled: bool = True) -> Dict:
    """注册宿主的 MCP 端点。注意键名是 `mcp`（非 mcpServers）。"""
    return merge_config({
        "mcp": {
            name: {
                "type": "remote",
                "url": url,
                "enabled": bool(enabled),
                "timeout": int(timeout_ms),
            }
        }
    })


def ensure_default_model(model: str = "") -> Dict:
    return merge_config({"model": (model or os.environ.get("MIMW_KERNEL_MODEL") or DEFAULT_MODEL)})


def default_agent_name() -> str:
    """默认 agent 名（MIMW_KERNEL_AGENT 可覆盖；缺省 loopx）。"""
    return (os.environ.get("MIMW_KERNEL_AGENT") or DEFAULT_AGENT).strip() or DEFAULT_AGENT


def ensure_default_agent(agent: str = "") -> Dict:
    """把 `default_agent`（opencode 全局默认 agent）写进隔离 home 配置。

    实测（opencode 1.18.35）：该键要求目标 agent 已存在、mode=primary、非 hidden，
    否则内核直接抛 `default agent "X" not found` —— 所以必须先安装
    kernel_assets/agent/loopx.md（install_builtin_assets 负责）。
    """
    return merge_config({"default_agent": (agent or default_agent_name())})


# ---------------------------------------------------------------- 凭据 auth.json

def auth_path() -> Path:
    return kp.data_dir() / "opencode" / "auth.json"


def read_auth() -> Dict:
    p = auth_path()
    if not p.is_file():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def write_auth(auth: Dict) -> None:
    p = auth_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(auth or {}, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass


def _host_llm_profiles_paths() -> List[Path]:
    """宿主 LLM 档案文件的候选位置（按优先级）。

    实探（本机）：宿主把档案写在 **coco_data/** 下（`src/core/path_config.get_coco_data_dir`：
    dev=仓库/coco_data，frozen=%LOCALAPPDATA%/MedicalImagingWorkflow/coco_data，
    另支持 COCO_DATA_DIR 覆盖）——而内核原来只查 `config/`，导致凭据永远导不进来。
    """
    out: List[Path] = []
    env_dir = os.environ.get("COCO_DATA_DIR", "").strip()
    if env_dir:
        out.append(Path(env_dir) / "custom_api_profiles.json")
    try:
        out.append(kp.app_home() / "config" / "custom_api_profiles.json")   # 旧位置（兼容保留）
        out.append(kp.app_home() / "coco_data" / "custom_api_profiles.json")  # dev/frozen 主位置
    except Exception:
        pass
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if root:
        # 冻结版写入的位置（源码版在开发机上也要能读到）
        out.append(Path(root) / "MedicalImagingWorkflow" / "coco_data"
                   / "custom_api_profiles.json")
    seen, uniq = set(), []
    for p in out:
        s = str(p)
        if s not in seen:
            seen.add(s)
            uniq.append(p)
    return uniq


def _infer_provider(prof: Dict) -> str:
    """从档案推断 provider id：显式 provider > base_url 网关特征 > name > deepseek。"""
    prov = str(prof.get("provider") or "").strip()
    if prov:
        return prov.split("/")[0].strip() or "deepseek"
    base = str(prof.get("base_url") or prof.get("baseUrl") or "").lower()
    name = str(prof.get("name") or "").strip()
    for frag, pid in (("deepseek", "deepseek"), ("openai", "openai"),
                      ("anthropic", "anthropic"), ("siliconflow", "siliconflow"),
                      ("moonshot", "moonshot"), ("dashscope", "alibaba")):
        if frag in base or frag in name.lower():
            return pid
    return name or "deepseek"


def _load_host_profiles() -> List[Dict]:
    for p in _host_llm_profiles_paths():
        if not p.is_file():
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except Exception:
            continue
        if isinstance(obj, list):
            profs = [x for x in obj if isinstance(x, dict)]
        elif isinstance(obj, dict):
            # 可能是 {name: profile} 或 {"profiles": [...]}
            if isinstance(obj.get("profiles"), list):
                profs = [x for x in obj["profiles"] if isinstance(x, dict)]
            else:
                profs = [v for v in obj.values() if isinstance(v, dict)]
        else:
            profs = []
        if profs:
            return profs
    return []


def import_host_llm_key(profile: Optional[Dict] = None) -> Dict:
    """把宿主 LLM 凭据导入内核 auth.json。

    优先级：显式 profile > 环境变量 > 宿主 custom_api_profiles.json。
    返回 {"success": bool, "provider": str, "source": str, ...}
    """
    provider = ""
    api_key = ""
    source = ""

    if profile:
        provider = str(profile.get("provider") or profile.get("name") or "").strip()
        api_key = str(profile.get("api_key") or profile.get("key") or "").strip()
        source = "explicit"

    if not api_key:
        env_key = os.environ.get("MIMW_LLM_API_KEY", "").strip()
        if env_key:
            api_key = env_key
            provider = os.environ.get("MIMW_LLM_PROVIDER", "deepseek").strip() or "deepseek"
            source = "env:MIMW_LLM_API_KEY"

    if not api_key:
        wanted = os.environ.get("MIMW_LLM_PROFILE", "").strip().lower()
        for prof in _load_host_profiles():
            if wanted and str(prof.get("name") or "").strip().lower() != wanted:
                continue
            key = str(prof.get("api_key") or prof.get("key") or "").strip()
            if key:
                api_key = key
                provider = _infer_provider(prof)
                source = "host:custom_api_profiles.json"
                break

    if not api_key:
        return {"success": False, "error": "no_host_key", "source": source or "none"}

    prov = (provider or "deepseek").split("/")[0].strip() or "deepseek"
    auth = read_auth()
    auth[prov] = {"type": "api", "key": api_key}
    write_auth(auth)
    return {"success": True, "provider": prov, "source": source}


# ---------------------------------------------------------------- 项目 <-> 会话 绑定

def bindings_path() -> Path:
    return kp.kernel_home() / "projects.json"


def load_bindings() -> Dict:
    p = bindings_path()
    if not p.is_file():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def save_bindings(data: Dict) -> None:
    p = bindings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data or {}, f, ensure_ascii=False, indent=2)


def get_project_session(project_id: str) -> Optional[str]:
    rec = load_bindings().get(str(project_id or "").strip())
    if isinstance(rec, dict):
        sid = str(rec.get("sessionID") or "").strip()
        return sid or None
    if isinstance(rec, str):
        return rec or None
    return None


def bind_project_session(project_id: str, session_id: str, title: str = "") -> None:
    pid = str(project_id or "").strip()
    if not pid:
        return
    data = load_bindings()
    data[pid] = {
        "sessionID": str(session_id or "").strip(),
        "title": str(title or "").strip(),
        "bound_at": _now_iso(),
    }
    save_bindings(data)


def rename_project_session(old_id: str, new_id: str) -> None:
    old = str(old_id or "").strip()
    new = str(new_id or "").strip()
    if not old or not new or old == new:
        return
    data = load_bindings()
    if old in data:
        data[new] = data.pop(old)
        save_bindings(data)


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- 随包资产安装

def install_builtin_assets() -> Dict[str, int]:
    """把 kernel_assets/{agent,skill} 安装到隔离 home 的 config 目录。"""
    src_root = kp.assets_root()
    installed = {"agent": 0, "skill": 0}
    agents_dst = kp.opencode_config_dir() / "agent"
    skills_dst = kp.opencode_config_dir() / "skill"
    agents_dst.mkdir(parents=True, exist_ok=True)
    skills_dst.mkdir(parents=True, exist_ok=True)

    src_agents = src_root / "agent"
    if src_agents.is_dir():
        for f in sorted(src_agents.glob("*.md")):
            try:
                shutil.copy2(f, agents_dst / f.name)
                installed["agent"] += 1
            except Exception:
                pass

    src_skills = src_root / "skill"
    if src_skills.is_dir():
        for d in sorted(p for p in src_skills.iterdir() if p.is_dir()):
            try:
                dst = skills_dst / d.name
                dst.mkdir(parents=True, exist_ok=True)
                for f in d.glob("**/*"):
                    if f.is_file():
                        rel = f.relative_to(d)
                        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(f, dst / rel)
                installed["skill"] += 1
            except Exception:
                pass
    return installed
