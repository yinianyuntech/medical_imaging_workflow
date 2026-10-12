#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""opencode_delegation —— 用内嵌 opencode 替代程序内自建的 skill loop。

背景：原程序在 `src/ai/agent_core_loop.py`（AgentCoreLoopExecutor）里自建了一套
「多阶段 + 内嵌 skills（Structurizer/Novelty/Critic/Refiner）+ 评审-精修循环」的
写作编排（core loop），并由 `ui/widgets/ai_summary_widget.py` 的 CoreLoopWorker 驱动。

本模块把这条编排**整体移除出运行路径**（默认引擎改为 opencode），改为把任务
**委托给内嵌 opencode 的项目会话**：
  * 任务 = 一段完整指令（项目上下文 + 模板约束 + 输出格式 + 自审要求）；
  * 数据 = opencode 通过 medwork MCP 工具自行读取（真实数据，不喂幻觉）；
  * 写作/评审/精修 = 由内嵌 opencode 的 agent 在其会话内完成（共享上下文）；
  * 进度 = 轮询 `run_turn` 的 tool/step 事件；结果 = 会话最终文本。

回退：`MIMW_DRAFT_ENGINE=legacy` 时仍走原 core loop（仅供对比/应急）。
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Callable, Dict, List, Optional

_SECTION_TABLE = (
    # (匹配关键词（小写）, 输出键, 规范名)
    ("abstract", "abstract", "Abstract"),
    ("introduction", "intro", "Introduction"),
    ("method", "methods", "Methods"),
    ("result", "results", "Results"),
    ("discussion", "discussion", "Discussion"),
    ("conclusion", "conclusion", "Conclusion"),
    ("reference", "references", "References"),
)

_TASK_TEMPLATE = """你是本项目（运行在内嵌 opencode 中）的科研写作智能体。请完成一次完整的论文初稿写作任务。

[项目]
- 项目ID: {project_id}
- 项目名称: {project_name}

[数据入口 — 必须先用工具读真数据]
使用 medwork_* 工具读取项目数据（如 medwork_project_summary、medwork_list_samples、
medwork_list_ocr_results、medwork_list_documents、medwork_list_storage_files、
medwork_read_tabular、medwork_aggregate_project、medwork_run_step2_mining 等）。
先读数据、再写作；所有数字与结论必须来自工具返回的真实数据，不得编造。

[已有上下文材料（可能截断）]
{raw_excerpt}

[模板约束]
{template_constraints}

[输出要求 — 只输出最终稿]
输出一个 Markdown 文档，结构为：
# <标题>
## Abstract
## Introduction
## Methods
## Results
## Discussion
## Conclusion
## References（能从项目/检索中得到才写）

要求：
1. 先在会话内自审一遍（方法-结果一致性、数字与工具结果一致），再给出最终稿；
2. 只输出最终稿文本本身（不要过程解释、不要“好的”等对话语）；
3. 用中文撰写（专业术语可保留英文）；
4. 本任务为宿主软件直接任务：不要执行 LoopX 工作流/写回（writeback）/目标记录操作。
"""


def _extract_text_parts(parts: Any) -> str:
    texts: List[str] = []
    for p in parts or []:
        if not isinstance(p, dict):
            continue
        if str(p.get("type") or "").lower() == "text":
            t = str(p.get("text") or "")
            if t:
                texts.append(t)
    return "".join(texts)


def _parse_markdown_to_result(md: str, *, project_id: str, project_name: str) -> Dict[str, Any]:
    """把整篇 Markdown 拆成与旧管线兼容的 result dict（供 _format_result_to_md / Step4 消费）。"""
    text = (md or "").strip()
    title = project_name or "Draft"
    sections: Dict[str, str] = {}
    order: List[str] = []
    current: Optional[str] = None
    buf: List[str] = []

    def flush():
        nonlocal buf, current
        if current is not None:
            body = "\n".join(buf).strip()
            if body:
                sections[current] = (sections.get(current, "") + "\n\n" + body).strip() \
                    if current in sections else body
        buf = []

    for line in text.splitlines():
        m = re.match(r"^#{1,4}\s+(.*?)\s*$", line)
        if m:
            heading_raw = m.group(1).strip()
            low = heading_raw.lower()
            hit = None
            for kw, key, _norm in _SECTION_TABLE:
                if kw in low:
                    hit = key
                    break
            if hit is not None:
                flush()
                current = hit
                if hit not in order:
                    order.append(hit)
                continue
            # 第一个非 section 标题 → 标题
            if not title or title == (project_name or "Draft") or title == "Draft":
                if len(heading_raw) >= 4 and current is None:
                    title = heading_raw
                    continue
            flush()
            current = None
            continue
        buf.append(line)
    flush()

    def unit(key: str, name: str) -> Dict[str, Any]:
        return {"name": name, "content": sections.get(key, "")}

    abstract = sections.get("abstract", "")
    refs: List[Dict[str, str]] = []
    for ln in (sections.get("references", "") or "").splitlines():
        s = ln.strip().lstrip("-*•").strip()
        if s and len(s) > 8:
            refs.append({"citation": s})

    units = {
        "intro": unit("intro", "Introduction"),
        "methods": unit("methods", "Methods"),
        "results": unit("results", "Results"),
        "discussion": unit("discussion", "Discussion"),
        "conclusion": unit("conclusion", "Conclusion"),
        "abstract": unit("abstract", "Abstract"),
    }
    skeleton_sections = [name for _kw, key, name in _SECTION_TABLE if key in sections] or [
        "Title", "Abstract", "Introduction", "Methods", "Results", "Discussion",
        "Conclusion", "References",
    ]
    return {
        "status": "ok",
        "outline": {
            "title": title,
            "core_claims": [],
            "target_audience": "scientific readers",
        },
        "units": units,
        "meta": {"content": abstract},
        "references": refs,
        "data_sources": [],
        "sample_sources": [],
        "structure_skeleton": {"sections": skeleton_sections},
        "full_text": text,
    }


def _build_task_prompt(
    *,
    project_id: str,
    project_name: str,
    raw_content: str,
    template_constraints_json: str,
) -> str:
    raw = str(raw_content or "").strip()
    excerpt = raw[:12000] + ("\n...[截断]..." if len(raw) > 12000 else "")
    constraints = str(template_constraints_json or "").strip()
    return _TASK_TEMPLATE.format(
        project_id=project_id or "(未提供)",
        project_name=project_name or project_id or "(未提供)",
        raw_excerpt=excerpt or "(无附加材料，全部数据从 medwork 工具读取)",
        template_constraints=constraints[:4000] if constraints else "(无)",
    )


def skip_local_loop_enabled() -> bool:
    """是否启用「移除本地 skill loop、委托内嵌 opencode」的默认引擎。"""
    return (os.environ.get("MIMW_DRAFT_ENGINE") or "opencode").strip().lower() != "legacy"


def run_delegated_pipeline(
    *,
    project_id: str,
    project_name: str = "",
    raw_content: str = "",
    template_constraints_json: str = "",
    workspace: str = "",
    storage_path: str = "",
    on_progress: Optional[Callable[[str], None]] = None,
    on_stream: Optional[Callable[[str], None]] = None,
    max_seconds: float = 3600.0,
) -> Dict[str, Any]:
    """把整篇论文的写作/评审/精修委托给内嵌 opencode 会话完成。

    返回与旧 core loop 兼容的 result dict（status/outline/units/meta/...）。
    失败时返回 {"status": "blocked", "error": ...} 供 `_format_result_to_md` 渲染。
    """

    def prog(msg: str) -> None:
        if on_progress:
            try:
                on_progress(str(msg))
            except Exception:
                pass

    def stream(tok: str) -> None:
        if on_stream:
            try:
                on_stream(str(tok))
            except Exception:
                pass

    try:
        from src.kernel.inference_gateway import get_gateway
    except Exception as e:  # noqa: BLE001
        return {"status": "blocked", "error": f"推理网关不可用: {e}", "engine": "opencode"}

    gw = get_gateway()
    boot = gw.ensure_boot()
    if boot is None:
        return {"status": "blocked",
                "error": f"内嵌 opencode 未启动: {gw.last_error}", "engine": "opencode"}

    try:
        sid = boot.ensure_project_session(project_id, title=f"write:{project_id}")
    except Exception as e:  # noqa: BLE001
        return {"status": "blocked", "error": f"会话建立失败: {e}", "engine": "opencode"}

    task_text = _build_task_prompt(
        project_id=project_id,
        project_name=project_name,
        raw_content=raw_content,
        template_constraints_json=template_constraints_json,
    )
    prog("已移除本地 skill loop：任务委托给内嵌 opencode 会话（共享上下文）")

    driver = boot.driver()
    if driver is None:
        return {"status": "blocked", "error": "KernelDriver 未就绪", "engine": "opencode"}

    def _on_event(ev: Dict[str, Any]) -> None:
        kind = str((ev or {}).get("kind") or "")
        if kind == "tool":
            prog(f"[tool] {str(ev.get('text') or '')[:160]}")
        elif kind == "text":
            t = str(ev.get("text") or "")
            if t:
                stream(t)

    def _question_handler(payload: Dict[str, Any]) -> List[str]:
        """无人值守：优先选第一个选项（无选项时回『继续』）。"""
        try:
            qs = (payload or {}).get("questions") or []
            if qs:
                first = qs[0] or {}
                opts = [str(o.get("label") if isinstance(o, dict) else o)
                        for o in (first.get("options") or [])]
                opts = [o for o in opts if o and o != "None"]
                if opts:
                    return [opts[0]]
        except Exception:
            pass
        return ["继续"]

    t0 = time.time()
    res = driver.run_turn(
        sid,
        task_text,
        on_event=_on_event,
        question_handler=_question_handler,
        permission_handler=lambda _p: "once",
        poll_interval=1.0,
        max_seconds=float(max_seconds),
    )
    elapsed = time.time() - t0

    final_text = _extract_text_parts((res or {}).get("parts") or []).strip()
    if not (res or {}).get("ok"):
        err = str((res or {}).get("provider_error") or (res or {}).get("error") or "unknown")
        return {"status": "blocked", "error": f"内嵌 opencode 回合失败: {err}",
                "engine": "opencode", "session_id": sid, "elapsed_s": round(elapsed, 1)}

    if len(final_text) < 200:
        return {"status": "blocked",
                "error": "内嵌 opencode 返回内容过短，无法形成初稿（请检查会话/模型配置）",
                "engine": "opencode", "session_id": sid, "elapsed_s": round(elapsed, 1)}

    result = _parse_markdown_to_result(
        final_text, project_id=project_id, project_name=project_name or project_id)
    result.update({
        "engine": "opencode",
        "session_id": sid,
        "elapsed_s": round(elapsed, 1),
        "llm_service_name": "内嵌 opencode（共享上下文）",
        "model_name": "",
        "raw_finish": str((res or {}).get("finish") or ""),
    })
    prog(f"内嵌 opencode 完成初稿：{len(final_text)} 字 / {round(elapsed, 1)}s / session={sid[:18]}")
    return result
