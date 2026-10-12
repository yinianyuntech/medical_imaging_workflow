#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具公共件：统一返回信封 + 破坏性操作确认门 + 惰性服务获取。"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

# 破坏性操作确认门：由 KernelBoot 注入（返回 True 表示允许执行）
_CONFIRM_HOOK: Optional[Callable[[str, Dict], bool]] = None


def set_confirm_hook(hook: Optional[Callable[[str, Dict], bool]]) -> None:
    global _CONFIRM_HOOK
    _CONFIRM_HOOK = hook


def ok(data: Any = None, **extra) -> Dict:
    out: Dict[str, Any] = {"ok": True}
    if data is not None:
        out["data"] = data
    out.update(extra)
    return out


def err(message: str, **extra) -> Dict:
    out: Dict[str, Any] = {"ok": False, "error": str(message)}
    out.update(extra)
    return out


def guard(action: str, detail: Dict) -> Optional[Dict]:
    """破坏性操作统一入口。返回 None 表示放行，否则返回拒绝信封。"""
    if _CONFIRM_HOOK is None:
        return err(
            f"destructive action '{action}' requires explicit confirmation, "
            "but no confirmation hook is registered"
        )
    try:
        if _CONFIRM_HOOK(action, detail):
            return None
    except Exception as e:  # noqa: BLE001
        return err(f"confirmation hook failed: {e}")
    return err(f"user denied action '{action}'")


# ---------------------------------------------------------------- 惰性服务

def db_service():
    from src.services.database_service import DatabaseService
    return DatabaseService()


def project_service():
    from src.services.project_service import ProjectService
    return ProjectService(db_service())


def storage_service():
    from src.services.project_storage_service import ProjectStorageService
    return ProjectStorageService(db_service())


def cleaning_service():
    from src.services.data_cleaning_service import DataCleaningService
    return DataCleaningService(db_service())


def safe(fn: Callable, *args, **kwargs) -> Dict:
    """把服务调用包成统一信封，避免异常穿透 MCP 层。"""
    try:
        return ok(fn(*args, **kwargs))
    except Exception as e:  # noqa: BLE001
        return err(f"{type(e).__name__}: {e}")
