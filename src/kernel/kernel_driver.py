#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kernel_driver —— 会话驱动层：事件归一化、run_turn、问答/权限回灌、消息轮询。

核心事实（playbook 第 3/5.6 节）：
  * legacy 阻塞投递 `POST /session/:id/message` 返回的 parts **不含 tool**；
    要看工具调用需轮询 `GET /session/:id/message`。
  * 内核会**阻塞等待** question/permission 回复，宿主必须回灌，否则会话挂死。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .kernel_client import KernelClient

EventHandler = Callable[[Dict], None]


class KernelDriver:
    def __init__(self, client: KernelClient):
        self.client = client

    # ------------------------------------------------------------ 归一化

    def normalize_event(self, raw: Dict) -> Dict:
        kind = str((raw or {}).get("kind") or "text")
        return {
            "kind": kind,
            "text": str((raw or {}).get("text") or ""),
            "data": (raw or {}).get("data") or {},
            "raw": raw,
        }

    def parts_to_events(self, parts: List[Dict]) -> List[Dict]:
        events: List[Dict] = []
        for p in parts or []:
            if not isinstance(p, dict):
                continue
            events.extend(self._part_to_events(p))
        return events

    def _part_to_events(self, part: Dict) -> List[Dict]:
        ptype = str(part.get("type") or "").lower()
        if ptype in ("text", "reasoning"):
            txt = str(part.get("text") or "")
            if txt.strip():
                return [{"kind": "text", "text": txt, "data": {"part_type": ptype}}]
            return []
        if ptype == "tool":
            tool = str(part.get("tool") or part.get("name") or "tool")
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            status = str(state.get("status") or part.get("status") or "")
            title = str(state.get("title") or "")
            call_id = str(part.get("callID") or part.get("id") or "")
            summary = f"{tool}"
            if title:
                summary += f": {title}"
            elif status:
                summary += f" ({status})"
            return [{"kind": "tool", "text": summary, "data": {
                "tool": tool, "status": status, "title": title, "call_id": call_id,
                "input": state.get("input"), "output": state.get("output"),
            }}]
        if ptype in ("step-finish", "step-start", "finish"):
            return [{"kind": "step", "text": str(part.get("type")), "data": part}]
        if ptype in ("file", "snapshot", "patch"):
            return [{"kind": "text", "text": f"[{ptype}]", "data": part}]
        return []

    # ------------------------------------------------------------ 消息轮询

    def _fetch_messages(self, session_id: str) -> List[Dict]:
        try:
            return self.client.list_messages(session_id)
        except Exception:
            return []

    def _iter_parts(self, messages: List[Dict]):
        for m in messages or []:
            if not isinstance(m, dict):
                continue
            parts = m.get("parts")
            if isinstance(parts, list):
                for p in parts:
                    yield p

    # ------------------------------------------------------------ 问答 / 权限

    def poll_pending(self, session_id: str) -> List[Dict]:
        """发现并归一化待决 question / permission。"""
        out: List[Dict] = []
        for q in self.client.legacy_questions():
            if self._belongs(q, session_id):
                out.append({"kind": "question", "data": q, "text": self._question_text(q)})
        for perm in self.client.legacy_permissions():
            if self._belongs(perm, session_id):
                out.append({"kind": "permission", "data": perm, "text": self._permission_text(perm)})
        return out

    @staticmethod
    def _belongs(item: Dict, session_id: str) -> bool:
        sid = str((item or {}).get("sessionID") or (item or {}).get("session_id") or "")
        return (not sid) or (sid == str(session_id))

    @staticmethod
    def _question_text(q: Dict) -> str:
        qs = (q or {}).get("questions") or []
        if isinstance(qs, list) and qs:
            first = qs[0] or {}
            return str(first.get("question") or first.get("header") or "question")
        return "question"

    @staticmethod
    def _permission_text(p: Dict) -> str:
        return f"{(p or {}).get('action', 'permission')}: {(p or {}).get('resources', '')}"

    def answer_question(self, request_id: str, labels: List[str]) -> Any:
        return self.client.reply_question(request_id, [list(labels or [])])

    # ------------------------------------------------------------ run_turn

    def run_turn(
        self,
        session_id: str,
        text: str,
        *,
        on_event: Optional[EventHandler] = None,
        model: Optional[dict] = None,
        question_handler: Optional[Callable[[Dict], List[str]]] = None,
        permission_handler: Optional[Callable[[Dict], str]] = None,
        poll_interval: float = 0.8,
        max_seconds: float = 3600.0,
    ) -> Dict:
        """投递一轮任务（阻塞 prompt + 并行轮询问答/权限 + 工具可见）。

        question_handler(q) -> 选中的 label 列表；省略则自动 reject。
        permission_handler(p) -> "once"|"always"|"reject"；省略则自动 once。
        """
        holder: Dict[str, Any] = {}
        done = threading.Event()

        def _worker():
            try:
                holder["result"] = self.client.prompt_legacy(session_id, text, model)
            except Exception as e:  # noqa: BLE001
                holder["error"] = e
            finally:
                done.set()

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

        seen_q: set = set()
        seen_p: set = set()
        seen_tools: set = set()
        deadline = time.time() + float(max_seconds)

        while not done.is_set() and time.time() < deadline:
            # 1) 问答 / 权限
            for ev in self.poll_pending(session_id):
                rid = str((ev.get("data") or {}).get("id") or "")
                if ev["kind"] == "question" and rid and rid not in seen_q:
                    seen_q.add(rid)
                    labels = question_handler(ev["data"]) if question_handler else None
                    try:
                        if labels:
                            self.answer_question(rid, labels)
                        else:
                            self.client.reject_question(rid)
                    except Exception:
                        pass
                    self._emit(on_event, ev)
                elif ev["kind"] == "permission" and rid and rid not in seen_p:
                    seen_p.add(rid)
                    reply = permission_handler(ev["data"]) if permission_handler else "once"
                    try:
                        self.client.reply_permission(rid, reply or "once")
                    except Exception:
                        pass
                    self._emit(on_event, ev)
            # 2) 工具调用（轮询消息）
            for p in self._iter_parts(self._fetch_messages(session_id)):
                if str(p.get("type") or "").lower() == "tool":
                    key = str(p.get("callID") or p.get("id") or "")
                    if key and key not in seen_tools:
                        seen_tools.add(key)
                        for ev in self._part_to_events(p):
                            self._emit(on_event, self.normalize_event(ev))
            time.sleep(poll_interval)

        if not done.is_set():
            try:
                self.client.abort(session_id)
            except Exception:
                pass
            thread.join(timeout=5)

        result = holder.get("result") or {}
        error = holder.get("error")

        # 3) 最终 parts 归一化
        for ev in self.parts_to_events((result or {}).get("parts") or []):
            self._emit(on_event, self.normalize_event(ev))

        finish = ""
        info = (result or {}).get("info") if isinstance(result, dict) else {}
        provider_error = ""
        if isinstance(info, dict):
            finish = str(info.get("finish") or info.get("status") or "")
            # ★ provider 级错误**不以异常抛出**，而是塞在 `info.error` 里。
            #   实测（deepseek 401）返回：
            #     {"info": {"error": {"name":"APIError",
            #        "data": {"message":"Authentication Fails, ...",
            #                 "statusCode":401,
            #                 "metadata":{"url":"https://api.deepseek.com/chat/completions"}}}}}
            #   **没有抛异常、parts 为空**。不读它就会表现为
            #   "成功但没有任何输出" —— 典型的静默失败：
            #   用户点了任务、面板既不报错也不出结果，无从判断。
            e = info.get("error")
            if isinstance(e, dict):
                d = e.get("data") if isinstance(e.get("data"), dict) else {}
                provider_error = str(
                    d.get("message") or e.get("name") or e)[:600]
            elif e:
                provider_error = str(e)[:600]

        err_text = str(error) if error else provider_error
        return {
            "ok": (error is None) and not provider_error,
            "finish": finish,
            "info": info,
            "parts": (result or {}).get("parts") or [],
            "error": err_text,
            # 便于上层区分"链路/传输错误"与"provider 拒绝"（鉴权、限流、模型不可用）
            "provider_error": provider_error,
        }

    def run_turn_async(self, session_id: str, text: str, **kwargs) -> threading.Thread:
        t = threading.Thread(
            target=self.run_turn, args=(session_id, text), kwargs=kwargs, daemon=True
        )
        t.start()
        return t

    @staticmethod
    def _emit(on_event: Optional[EventHandler], ev: Dict) -> None:
        if on_event is None:
            return
        try:
            on_event(ev)
        except Exception:
            pass
