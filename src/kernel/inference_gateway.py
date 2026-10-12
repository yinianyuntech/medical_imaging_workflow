#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inference_gateway —— 宿主推理的统一入口：**全部转入内嵌 opencode（共享上下文）**。

背景（见 docs/step2-inference-audit.md）：
  宿主里所有需要 LLM 推理的功能（Step2 挖掘计划 / 图注、语义映射、文本改写、
  评审……）原先各自直连 Ollama / Custom API —— 调用无状态、上下文彼此隔离。

本模块把它们统一路由到**内嵌 opencode 的项目会话**：
  * 会话按项目持久化（`kernel_boot.ensure_project_session`）→ 所有服务
    **共享同一上下文**：后面的推理能看到此前每一步的消息、工具调用与产物；
  * 兼容层 `OpenCodeLLMService.generate(model, prompt, timeout, ...)` 与既有
    `OllamaLocalService.generate` 的返回契约一致（{"success","response","error"}），
    调用方（如 llm_guided_sklearn_pipeline）可零改动切换；
  * provider 级错误（401/限流/模型不可用）**显式**从 `info.error` 读取并暴露 ——
    否则会静默返回 ok:True + 空响应（playbook §8 实测坑）；
  * 同一会话的并发调用加锁串行，避免"一回合未完又投递"把会话打结。

开关：
  MIMW_INFER_BACKEND = opencode（默认）| legacy（回退旧直连实现）
"""

from __future__ import annotations

import json
import threading
from typing import Any, Dict, Optional

# 无项目上下文的推理（如通用改写）落在这个"伪项目"的会话里，
# 保证它们之间也共享上下文，同时不污染真实项目的会话。
DEFAULT_PROJECT = "_inference"
DEFAULT_TIMEOUT = 900.0

# 宿主"工具型推理"直调提示：抑制 loopx agent 的 LoopX 工作流/写回噪音。
# （实测：默认 agent=loopx 时，改写类任务会被追加 "LoopX writeback ..." 内容）
_DIRECT_HINT_MARK = "[宿主直接任务]"
_DIRECT_HINT = (
    "[宿主直接任务] 这是宿主软件发起的一次直接推理调用：只完成本次任务并输出所需内容；"
    "不要执行 LoopX 工作流、写回（writeback）或目标记录操作，除非任务本身明确要求。\n\n"
)


def _err_text(err: Any) -> str:
    """把 info.error 的任意形状压成可读文本。"""
    if not err:
        return ""
    if isinstance(err, str):
        return err
    try:
        if isinstance(err, dict):
            for key in ("message", "error", "name", "type"):
                v = err.get(key)
                if v:
                    return str(v)
            data = err.get("data")
            if isinstance(data, dict) and data.get("message"):
                return str(data["message"])
            return json.dumps(err, ensure_ascii=False)[:400]
        return str(err)
    except Exception:  # noqa: BLE001
        return "provider_error"


def _extract_text(parts: Any) -> str:
    """从消息 parts 里取文本（只取 type=text；reasoning 仅在没有 text 时兜底）。"""
    texts, reasoning = [], []
    for p in parts or []:
        if not isinstance(p, dict):
            continue
        ptype = str(p.get("type") or "").lower()
        if ptype == "text":
            t = str(p.get("text") or "")
            if t:
                texts.append(t)
        elif ptype == "reasoning":
            t = str(p.get("text") or "")
            if t:
                reasoning.append(t)
    return "".join(texts) if texts else "".join(reasoning)


def _parse_model(model: str) -> Optional[Dict[str, str]]:
    """'provider/modelID' → V1 形状；无 '/' 则返回 None（用内核默认模型）。"""
    m = str(model or "").strip()
    if "/" not in m:
        return None
    prov, mid = m.split("/", 1)
    prov, mid = prov.strip(), mid.strip()
    if not prov or not mid:
        return None
    return {"providerID": prov, "modelID": mid}


class InferenceGateway:
    """宿主 → 内嵌 opencode 的推理网关（进程内单例使用）。"""

    def __init__(self) -> None:
        self._boot = None                 # KernelBoot
        self._boot_lock = threading.Lock()
        self._locks: Dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self.last_error = ""
        self.last_session_id = ""

    # ------------------------------------------------------------ 绑定 / 就绪

    def bind(self, boot: Any) -> None:
        """绑定宿主共享的 KernelBoot（与底部智能体面板同一个实例 → 同会话）。"""
        self._boot = boot

    @property
    def boot(self) -> Any:
        return self._boot

    def is_bound(self) -> bool:
        return self._boot is not None

    def ensure_boot(self) -> Any:
        """公开入口：返回就绪的 KernelBoot（必要时启动内核）；失败返回 None。"""
        return self._ensure_boot()

    def _ensure_boot(self) -> Any:
        with self._boot_lock:
            b = self._boot
            if b is None:
                self.last_error = "kernel_not_bound"
                return None
            try:
                if b.is_running():
                    return b
            except Exception:
                pass
            try:
                st = b.start() if callable(getattr(b, "start", None)) else {}
                if isinstance(st, dict) and st.get("ok"):
                    return b
                self.last_error = str((st or {}).get("error") or "kernel_start_failed")
            except Exception as e:  # noqa: BLE001
                self.last_error = f"{type(e).__name__}: {e}"
            return None

    def _lock_for(self, sid: str) -> threading.Lock:
        with self._locks_guard:
            lk = self._locks.get(sid)
            if lk is None:
                lk = threading.Lock()
                self._locks[sid] = lk
            return lk

    # ------------------------------------------------------------ 核心：infer

    def infer(
        self,
        prompt: str,
        *,
        project_id: str = "",
        model: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        title: str = "",
        direct: bool = True,
    ) -> Dict[str, Any]:
        """把一轮推理投递到（项目）会话，返回宿主统一信封。

        返回：{"success", "response", "error", "session_id", "finish"}
        —— 与 `OllamaLocalService.generate` 的 success/response/error 兼容。
        """
        text = str(prompt or "").strip()
        if not text:
            return {"success": False, "response": "", "error": "empty_prompt",
                    "session_id": "", "finish": ""}
        if direct and _DIRECT_HINT_MARK not in text:
            text = _DIRECT_HINT + text

        boot = self._ensure_boot()
        if boot is None:
            return {"success": False, "response": "",
                    "error": f"kernel_unavailable: {self.last_error}",
                    "session_id": "", "finish": ""}
        try:
            pid = str(project_id or "").strip() or DEFAULT_PROJECT
            sid = boot.ensure_project_session(
                pid, title=title or f"infer:{pid}")
        except Exception as e:  # noqa: BLE001
            return {"success": False, "response": "",
                    "error": f"session_failed: {type(e).__name__}: {e}",
                    "session_id": "", "finish": ""}

        self.last_session_id = sid
        with self._lock_for(sid):
            try:
                res = boot.client.prompt_legacy(
                    sid, text, model=_parse_model(model), timeout=float(timeout))
            except Exception as e:  # noqa: BLE001
                return {"success": False, "response": "",
                        "error": f"prompt_failed: {type(e).__name__}: {e}",
                        "session_id": sid, "finish": ""}

        info = res.get("info") if isinstance(res, dict) else {}
        info = info if isinstance(info, dict) else {}
        # provider 级错误不以异常抛出，必须显式读取（playbook §8）
        err = _err_text(info.get("error"))
        reply = _extract_text(res.get("parts") if isinstance(res, dict) else None)
        success = bool(reply.strip()) and not err
        return {
            "success": success,
            "response": reply,
            "error": err if err else ("" if success else "empty_response"),
            "session_id": sid,
            "finish": str(info.get("finish") or ""),
        }

    # -------------------------------------------------- llm_service 兼容契约

    def generate(
        self,
        model: str,
        prompt: str,
        timeout: Optional[float] = None,
        stream_callback: Any = None,
        project_id: str = "",
        direct: bool = True,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """与 `OllamaLocalService.generate(model, prompt, timeout=...)` 同形。

        额外 kwargs（num_predict/options/response_format/...）被安全忽略；
        stream_callback 若提供，会在拿到完整回复后一次性回调（非增量）。
        project_id 非空时，该轮推理（反馈/交互）注入**该项目的会话上下文**。
        """
        out = self.infer(prompt, model=str(model or ""), project_id=project_id,
                         timeout=float(timeout or DEFAULT_TIMEOUT), direct=direct)
        if stream_callback is not None and out.get("success"):
            try:
                stream_callback(out.get("response") or "")
            except Exception:  # noqa: BLE001
                pass
        return out

    # 别名：`_raw_llm` 一类的探测式调用会按名字找一个可用的方法
    def chat(self, prompt: str, model: str = "", project_id: str = "",
             **kwargs: Any) -> Dict[str, Any]:
        return self.infer(prompt, model=model, project_id=project_id)

    def complete(self, prompt: str, model: str = "", project_id: str = "",
                 **kwargs: Any) -> Dict[str, Any]:
        return self.infer(prompt, model=model, project_id=project_id)

    def generate_text(self, prompt: str, model: str = "", project_id: str = "",
                      **kwargs: Any) -> str:
        return str(self.infer(prompt, model=model,
                              project_id=project_id).get("response") or "")


class OpenCodeLLMService:
    """把网关包装成宿主既有的 llm_service 接口（可整体替换 OllamaLocalService）。"""

    def __init__(self, gateway: Optional[InferenceGateway] = None,
                 project_id: str = ""):
        self._gw = gateway or get_gateway()
        self._project_id = str(project_id or "")

    @property
    def project_id(self) -> str:
        return self._project_id

    def set_project(self, project_id: str) -> None:
        """绑定到项目会话：此后所有交互/反馈注入该项目共享上下文。"""
        self._project_id = str(project_id or "")

    def generate(self, model: str, prompt: str, timeout: Optional[float] = None,
                 stream_callback: Any = None, **kwargs: Any) -> Dict[str, Any]:
        return self._gw.generate(model, prompt, timeout=timeout,
                                 stream_callback=stream_callback,
                                 project_id=self._project_id, **kwargs)

    def chat(self, prompt: str, model: str = "", **kwargs: Any) -> Dict[str, Any]:
        return self._gw.chat(prompt, model=model, project_id=self._project_id)

    def complete(self, prompt: str, model: str = "", **kwargs: Any) -> Dict[str, Any]:
        return self._gw.complete(prompt, model=model, project_id=self._project_id)

    def generate_text(self, prompt: str, model: str = "", **kwargs: Any) -> str:
        return self._gw.generate_text(prompt, model=model,
                                      project_id=self._project_id)


# ============================================================ 模块级单例

_GATEWAY: Optional[InferenceGateway] = None
_GATEWAY_LOCK = threading.Lock()


def get_gateway() -> InferenceGateway:
    global _GATEWAY
    with _GATEWAY_LOCK:
        if _GATEWAY is None:
            _GATEWAY = InferenceGateway()
        return _GATEWAY


def bind_boot(boot: Any) -> InferenceGateway:
    """main.py 在 attach_opencode 后调用：与面板共享同一个 KernelBoot。"""
    gw = get_gateway()
    gw.bind(boot)
    return gw


def infer_backend() -> str:
    import os
    return (os.environ.get("MIMW_INFER_BACKEND") or "opencode").strip().lower()


def make_llm_service(legacy_factory: Any = None) -> Any:
    """统一的服务工厂：默认返回网关适配器；MIMW_INFER_BACKEND=legacy 时回退旧实现。

    legacy_factory: 一个零参工厂（如 `OllamaLocalService`），仅 legacy 模式使用。
    """
    if infer_backend() == "legacy":
        if callable(legacy_factory):
            try:
                return legacy_factory()
            except Exception:  # noqa: BLE001
                pass
        try:
            from src.services.ollama_local_service import OllamaLocalService
            return OllamaLocalService()
        except Exception:  # noqa: BLE001
            return None
    return OpenCodeLLMService()
