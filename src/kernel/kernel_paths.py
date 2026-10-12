#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kernel_paths —— opencode 内核的路径/环境解析。

设计要点（对齐 playbook 第 5.1/5.2 节）：
  * 隔离 home：默认 %LOCALAPPDATA%/MedicalImagingWorkflow/kernel，可用 MIMW_KERNEL_HOME 覆盖。
  * opencode.exe 查找：env -> 随包 opencode/ -> runtime/ -> _internal/ -> PATH -> npm-global（开发便利）。
  * 环境变量（XDG_* / OPENCODE_*）必须在**启动内核之前**注入。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------- 基础目录

def project_root() -> Path:
    """源码运行时返回仓库根；冻结运行时返回 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def app_home() -> Path:
    """可写根目录。"""
    env = os.environ.get("MIMW_APP_HOME")
    if env:
        return Path(env).expanduser().resolve()
    if getattr(sys, "frozen", False):
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if root:
            return Path(root) / "MedicalImagingWorkflow"
        return project_root()
    return project_root()


def kernel_home() -> Path:
    """隔离 home 根。"""
    env = os.environ.get("MIMW_KERNEL_HOME")
    if env:
        return Path(env).expanduser().resolve()
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if root:
        return Path(root) / "MedicalImagingWorkflow" / "kernel"
    return app_home() / "kernel"


def data_dir() -> Path:
    return kernel_home() / "data"


def config_dir() -> Path:
    return kernel_home() / "config"


def state_dir() -> Path:
    return kernel_home() / "state"


def cache_dir() -> Path:
    return kernel_home() / "cache"


def opencode_config_dir() -> Path:
    return config_dir() / "opencode"


# ---------------------------------------------------------------- 资产

def assets_root() -> Path:
    """随包 kernel_assets 目录（源码 / 冻结 / 打平到 _internal 三种布局都要命中）。"""
    cands = [Path(__file__).resolve().parent / "kernel_assets"]
    try:
        cands.append(project_root() / "kernel_assets")
        cands.append(project_root() / "_internal" / "kernel_assets")
        cands.append(project_root() / "src" / "kernel" / "kernel_assets")
    except Exception:
        pass
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        cands.append(Path(meipass) / "kernel_assets")
        cands.append(Path(meipass) / "src" / "kernel" / "kernel_assets")
    for cand in cands:
        try:
            if cand.is_dir():
                return cand
        except OSError:
            continue
    return Path(__file__).resolve().parent / "kernel_assets"


# ---------------------------------------------------------------- opencode 可执行

def _npm_global_candidates() -> List[Path]:
    """开发机便利：扫描 npm 全局安装的 opencode。"""
    out: List[Path] = []
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not root:
        return out
    base = Path(root) / "npm-global" / "node_modules"
    if not base.is_dir():
        return out
    # 优先 1.x（legacy V1 API 兼容），其次其它
    patterns = [
        ".opencode-ai-*/bin/opencode.exe",
        "@opencode/cli/bin/opencode.exe",
        "*/node_modules/opencode-windows-x64/bin/opencode.exe",
    ]
    for pat in patterns:
        for p in sorted(base.glob(pat)):
            out.append(p)
    return out


def opencode_candidates() -> List[Path]:
    """返回按优先级排序的候选可执行路径（Windows 下剔除 .cmd/.ps1/.bat 包装器）。"""
    cands: List[Path] = []
    env = os.environ.get("MIMW_OPENCODE_EXE")
    if env:
        cands.append(Path(env).expanduser())
    exe_name = "opencode.exe" if os.name == "nt" else "opencode"
    cands.append(app_home() / "opencode" / exe_name)
    # runtime/ 下任意深度（轻量包场景）
    for base in (app_home() / "runtime", project_root() / "runtime"):
        if base.is_dir():
            cands.extend(sorted(base.glob(f"**/{exe_name}")))
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            cands.append(Path(meipass) / "opencode" / exe_name)
    which = shutil.which("opencode")
    if which:
        cands.append(Path(which))
    cands.extend(_npm_global_candidates())

    bad_suffix = {".cmd", ".ps1", ".bat", ".vbs"}
    seen = set()
    out: List[Path] = []
    for p in cands:
        if os.name == "nt" and p.suffix.lower() in bad_suffix:
            continue
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


@lru_cache(maxsize=32)
def _version_of(path_str: str) -> str:
    return opencode_version(Path(path_str), timeout=25.0)


def _version_major(path: Path) -> int:
    try:
        raw = _version_of(str(path))
    except Exception:
        return 0
    m = None
    for token in (raw or "").replace("v", " ").split():
        if token and token[0].isdigit():
            m = token
            break
    if not m:
        return 0
    try:
        return int(m.split(".")[0])
    except Exception:
        return 0


def opencode_exe(prefer_major: int = 1) -> Path:
    """返回第一个存在的 opencode 可执行文件。

    `prefer_major`（默认 1）：优先选择主版本匹配的内核。本嵌入的 API 契约基于
    legacy V1；若机器上同时存在 2.x，跳过它以免走 V2 面。
    """
    existing: List[Path] = []
    for p in opencode_candidates():
        try:
            if p.is_file():
                existing.append(p)
        except OSError:
            continue
    if not existing:
        raise FileNotFoundError(
            "未找到 opencode 可执行文件。请设置 MIMW_OPENCODE_EXE，或放到 "
            f"{app_home() / 'opencode' / 'opencode.exe'}"
        )
    if prefer_major:
        for p in existing:
            if _version_major(p) == int(prefer_major):
                return p
    return existing[0]



def opencode_version(exe: Optional[Path] = None, timeout: float = 20.0) -> str:
    """执行 `<exe> --version`，返回版本字符串（失败返回空串）。"""
    try:
        target = str(exe or opencode_exe())
    except FileNotFoundError:
        return ""
    try:
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        proc = subprocess.run(
            [target, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=flags,
        )
        return (proc.stdout or proc.stderr or "").strip()
    except Exception:
        return ""


# ---------------------------------------------------------------- 状态文件

def state_file() -> Path:
    return kernel_home() / "kernel_state.json"


def read_state() -> Dict:
    p = state_file()
    if not p.is_file():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def write_state(state: Dict) -> None:
    p = state_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(state or {}, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass


def clear_state() -> None:
    try:
        state_file().unlink()
    except Exception:
        pass


# ---------------------------------------------------------------- 环境变量

def kernel_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """构造启动内核所需的环境变量（在 Popen 时注入）。"""
    env = dict(os.environ)
    env["XDG_DATA_HOME"] = str(data_dir())
    env["XDG_CONFIG_HOME"] = str(config_dir())
    env["XDG_STATE_HOME"] = str(state_dir())
    env["XDG_CACHE_HOME"] = str(cache_dir())
    env["OPENCODE_CONFIG_DIR"] = str(opencode_config_dir())
    env["OPENCODE_CLIENT"] = "desktop"          # 注册 question 工具
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"    # 嵌入场景禁自更新
    # 随包 loopx CLI：加到 PATH，内嵌 openCode 的 agent 可直接运行 `loopx ...`
    try:
        _lx = loopx_exe()
        if _lx:
            env["PATH"] = str(Path(_lx).resolve().parent) + os.pathsep + env.get("PATH", "")
    except Exception:
        pass
    for k, v in (extra or {}).items():
        env[k] = str(v)
    return env


def loopx_exe() -> str:
    """随包 loopx CLI 定位（V2.0）：

    `MIMW_LOOPX_EXE` 环境变量 → 随包 `assets/loopx/loopx.exe`
    （冻结= _MEIPASS、源码=仓库根）→ `<app_home>/loopx/` → PATH。
    内嵌 openCode 的 agent 用 `loopx` 命令驱动 LoopX 控制平面。
    """
    env = os.environ.get("MIMW_LOOPX_EXE", "").strip()

    def _ok(p) -> str:
        try:
            if p and os.path.isfile(str(p)):
                return str(p)
        except Exception:
            pass
        return ""

    if env:
        got = _ok(env)
        if got:
            return got
    names = ("loopx.exe", "loopx")
    cands = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        for n in names:
            cands.append(Path(meipass) / "assets" / "loopx" / n)
    try:
        for n in names:
            cands.append(project_root() / "assets" / "loopx" / n)
    except Exception:
        pass
    for n in names:
        cands.append(app_home() / "loopx" / n)
    for c in cands:
        got = _ok(c)
        if got:
            return got
    try:
        import shutil as _sh
        w = _sh.which("loopx")
        return w or ""
    except Exception:
        return ""


def ensure_kernel_dirs() -> None:
    for d in (data_dir(), config_dir(), state_dir(), cache_dir(), opencode_config_dir()):
        d.mkdir(parents=True, exist_ok=True)
