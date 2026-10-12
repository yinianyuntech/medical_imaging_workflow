#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""domain_tools —— 宿主领域能力暴露给 opencode 的 MCP 工具。

分组：
  数据/巡检（只读）  list_projects / get_project / project_summary / list_samples /
                     list_storage_files / read_tabular / get_schema_cache /
                     aggregate_project / list_dicom_sessions / list_ocr_results / list_documents
  计算（写）          run_step2_mining / ensure_schema_cache / save_draft / export_drafts_to_word
  破坏性（确认门）    create_project / purge_project / delete_sample
  LLM                llm_chat（宿主模型只作工具，内核必须走原生 provider）
  界面               gui_status / gui_toast / gui_navigate / gui_log
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import _common as C

# step2 / step3 的分析与文献工具（拆到独立模块，便于单独验证）
try:
    from .analysis_tools import (
        duckdb_tables, duckdb_query, compute_statistics, plot_nature_figure,
        extract_keywords,
    )
    from .literature_tools import (
        search_papers, download_paper_pdf, render_docx_template,
        literature_to_docx,
    )
except Exception as _e:  # pragma: no cover
    import logging as _lg
    _lg.getLogger(__name__).warning(f"分析与文献工具导入失败: {_e}")
    duckdb_tables = duckdb_query = compute_statistics = None      # type: ignore
    plot_nature_figure = extract_keywords = None                 # type: ignore
    search_papers = download_paper_pdf = None                    # type: ignore
    render_docx_template = literature_to_docx = None             # type: ignore

_MAX_JSON_CHARS = 20000
_UI_BRIDGE = None  # 由 mcp_server 注入


def set_ui_bridge(bridge) -> None:
    global _UI_BRIDGE
    _UI_BRIDGE = bridge


def _truncate(text: str, limit: int = _MAX_JSON_CHARS) -> str:
    s = str(text or "")
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n\n...[truncated {len(s) - limit} chars]"


def _storage_path(project_id: str) -> str:
    try:
        return str(C.storage_service().get_project_storage_path(project_id))
    except Exception:
        return ""


# ============================================================ 数据 / 巡检（只读）

def list_projects() -> Dict:
    def _run():
        projects = C.project_service().get_all_projects()
        return [
            {
                "project_id": p.project_id,
                "name": p.name,
                "description": p.description,
                "status": p.status,
                "created_at": str(p.created_at),
            }
            for p in projects
        ]
    return C.safe(_run)


def get_project(project_id: str) -> Dict:
    def _run():
        p = C.project_service().get_project_by_id(str(project_id))
        if p is None:
            raise ValueError(f"project not found: {project_id}")
        return p.to_dict()
    return C.safe(_run)


def project_summary(project_id: str) -> Dict:
    """项目级数据概览：DICOM/OCR/文本/表格/样本/MagicSeg 计数 + 存储占用。"""
    def _run():
        summary = C.cleaning_service().get_project_sample_summary(str(project_id))
        return json.loads(json.dumps(summary, ensure_ascii=False, default=str))
    return C.safe(_run)


def list_samples(project_id: str) -> Dict:
    def _run():
        rows = C.db_service().execute_query(
            "SELECT user_id, display_name, description, created_at, last_used, is_active "
            "FROM user_ids WHERE project_id = ? ORDER BY created_at DESC",
            (str(project_id),),
        )
        return rows or []
    return C.safe(_run)


def list_storage_files(project_id: str, file_type: str = "") -> Dict:
    def _run():
        files = C.storage_service().list_project_files(str(project_id), file_type or None)
        return files or []
    return C.safe(_run)


def read_tabular(project_id: str, file_id: str, max_chars: int = _MAX_JSON_CHARS) -> Dict:
    """读取某个 tabular 叶子节点的 JSON 内容（含 metadata 与 sheet 结构）。"""
    def _run():
        path = C.storage_service().get_file_path(str(project_id), str(file_id))
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(f"tabular file not found: {file_id}")
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
        return {
            "file_id": file_id,
            "file_path": path,
            "file_name": Path(path).name,
            "content": _truncate(raw, int(max_chars)),
        }
    return C.safe(_run)


def get_schema_cache(project_id: str) -> Dict:
    """跨分支字段语义归一缓存（canonical_mappings）。"""
    def _run():
        cache = C.storage_service().load_schema_cache(str(project_id)) or {}
        return {
            "path": str(C.storage_service().get_schema_cache_path(str(project_id))),
            "canonical_mappings": cache.get("canonical_mappings") or [],
            "branches": list((cache.get("branches") or {}).keys()),
            "updated_at": cache.get("updated_at", ""),
        }
    return C.safe(_run)


def aggregate_project(project_id: str) -> Dict:
    """按样本聚合 OCR/DICOM(+ROI)/文本，返回每个样本的摘要文本。"""
    def _run():
        from src.services.data_aggregation_service import DataAggregationService
        cases = DataAggregationService(C.db_service()).aggregate_project_data(str(project_id))
        out = []
        for c in cases or []:
            out.append({
                "user_id": c.user_id,
                "display_name": c.display_name,
                "n_ocr": len(c.ocr_data or []),
                "n_dicom": len(c.dicom_data or []),
                "n_text": len(c.text_data or []),
                "summary": _truncate(c.get_summary_text(), 4000),
            })
        return {"n_samples": len(out), "samples": out}
    return C.safe(_run)


def list_dicom_sessions(project_id: str) -> Dict:
    def _run():
        rows = C.db_service().execute_query(
            "SELECT ds.session_id, ds.user_id, ds.file_name, ds.created_at, "
            "  (SELECT COUNT(*) FROM roi_data rd WHERE rd.session_id = ds.session_id) AS roi_count "
            "FROM dicom_sessions ds WHERE ds.project_id = ? ORDER BY ds.created_at DESC",
            (str(project_id),),
        )
        return rows or []
    return C.safe(_run)


def list_ocr_results(project_id: str) -> Dict:
    def _run():
        rows = C.db_service().execute_query(
            "SELECT s.session_id, s.user_id, s.image_name, r.result_id, r.confidence, "
            "  substr(COALESCE(r.extracted_text, r.recognized_text, ''), 1, 500) AS text_preview "
            "FROM ocr_sessions s LEFT JOIN ocr_results r ON s.session_id = r.session_id "
            "WHERE s.project_id = ? ORDER BY s.created_at DESC",
            (str(project_id),),
        )
        return rows or []
    return C.safe(_run)


def list_documents(project_id: str) -> Dict:
    def _run():
        rows = C.db_service().execute_query(
            "SELECT d.doc_id, ts.user_id, d.file_name, d.format, d.created_at, "
            "  substr(COALESCE(d.content, ''), 1, 400) AS content_preview "
            "FROM text_sessions ts JOIN documents d ON d.session_id = ts.session_id "
            "WHERE ts.project_id = ? ORDER BY d.created_at DESC",
            (str(project_id),),
        )
        return rows or []
    return C.safe(_run)


# ============================================================ 计算（写）

def run_step2_mining(project_id: str, model: str = "", max_seconds: int = 1800) -> Dict:
    """执行 llm_guided_sklearn 挖掘管线，产物落 <storage>/exports/step2_mining_<ts>/。"""
    def _run():
        from src.services.llm_guided_sklearn_pipeline import run_llm_guided_sklearn_pipeline
        storage = _storage_path(project_id)
        if not storage or not os.path.isdir(storage):
            raise FileNotFoundError(f"project storage missing for {project_id}")
        out_dir = os.path.join(storage, "exports", f"step2_mining_{time.strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(out_dir, exist_ok=True)
        os.environ["SKLEARN_ALLOW_WORKSPACE_CSV_EXCEL"] = "1"
        res = run_llm_guided_sklearn_pipeline(
            llm_service=None,
            model=str(model or ""),
            materials_text="",
            project_storage_path=storage,
            workspace=storage,
            out_dir=out_dir,
        )
        if isinstance(res, dict):
            res["out_dir"] = out_dir
            res["project_id"] = project_id
            res["summary"] = _truncate(str(res.get("summary") or ""), 6000)
        return res or {"success": False, "error": "empty_result"}
    return C.safe(_run)


def ensure_schema_cache(project_id: str, max_new_branches: int = 8) -> Dict:
    """用 LLM 建立/刷新跨分支字段语义映射（tabular/schema_cache.json）。"""
    def _run():
        from src.services.schema_cache_service import SchemaCacheService
        storage = C.storage_service()
        svc = SchemaCacheService(C.db_service(), storage_service=storage)

        def _llm(prompt: str) -> str:
            return _raw_llm(prompt)

        cache, preview = svc.ensure_schema_cache(
            str(project_id), llm_call=_llm, max_new_branches=int(max_new_branches)
        )
        return {
            "n_canonical": len((cache or {}).get("canonical_mappings") or []),
            "preview": _truncate(preview, 3000),
        }
    return C.safe(_run)


def save_draft(project_id: str, title: str, content: str, model: str = "opencode", score: int = 0) -> Dict:
    """把成稿写入 drafts 表（Step5 持久化）。"""
    def _run():
        import uuid
        draft = {
            "id": f"draft_{uuid.uuid4().hex[:12]}",
            "project_id": str(project_id),
            "title": str(title or "Untitled Draft"),
            "content": str(content or ""),
            "model": str(model or "opencode"),
            "score": int(score or 0),
            "logs": json.dumps({"source": "opencode", "ts": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False),
        }
        success = C.project_service().save_draft(draft)
        if not success:
            raise RuntimeError("save_draft failed")
        return {"draft_id": draft["id"], "title": draft["title"]}
    return C.safe(_run)


def export_drafts_to_word(project_id: str) -> Dict:
    """把该项目的 drafts 导出为 Word（优先 batch_folder，否则项目 exports/）。"""
    def _run():
        from docx import Document
        ps = C.project_service()
        proj = ps.get_project_by_id(str(project_id))
        if proj is None:
            raise ValueError(f"project not found: {project_id}")
        drafts = ps.get_project_drafts(str(project_id)) or []
        if not drafts:
            raise ValueError("no drafts for this project")
        base_dir = str((proj.metadata or {}).get("batch_folder") or "").strip()
        if not base_dir:
            base_dir = os.path.join(_storage_path(project_id), "exports")
        os.makedirs(base_dir, exist_ok=True)
        written: List[str] = []
        for i, d in enumerate(drafts, 1):
            doc = Document()
            doc.add_paragraph(str(d.get("content") or ""))
            safe_title = "".join(ch for ch in str(d.get("title") or f"draft_{i}") if ch not in '\\/:*?"<>|')[:60]
            path = os.path.join(base_dir, f"step5_{i:02d}_{safe_title}.docx")
            doc.save(path)
            written.append(path)
        return {"count": len(written), "files": written}
    return C.safe(_run)


# ============================================================ 破坏性（确认门）

def create_project(project_id: str, name: str, description: str = "") -> Dict:
    def _run():
        from src.models.project import Project
        pid = str(project_id or "").strip()
        if not pid:
            raise ValueError("project_id is required")
        if C.project_service().get_project_by_id(pid) is not None:
            raise ValueError(f"project already exists: {pid}")
        proj = Project(project_id=pid, name=str(name or pid), description=str(description or ""), status="active")
        if not C.project_service().create_project(proj):
            raise RuntimeError("create_project failed")
        C.storage_service().create_project_storage(pid)
        return {"project_id": pid, "name": proj.name}
    return C.safe(_run)


def purge_project(project_id: str) -> Dict:
    """【危险】永久删除项目及其数据与文件。需用户确认。"""
    pid = str(project_id or "").strip()
    denied = C.guard("purge_project", {"project_id": pid, "impact": "永久删除该项目全部数据与文件"})
    if denied:
        return denied
    return C.safe(lambda: {"purged": bool(C.project_service().purge_project(pid)), "project_id": pid})


def delete_sample(project_id: str, user_id: str) -> Dict:
    """【危险】删除项目下的样本。需用户确认。"""
    pid = str(project_id or "").strip()
    uid = str(user_id or "").strip()
    denied = C.guard("delete_sample", {"project_id": pid, "user_id": uid, "impact": "删除该样本记录"})
    if denied:
        return denied

    def _run():
        db = C.db_service()
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM user_ids WHERE user_id = ? AND project_id = ?", (uid, pid))
            n = cur.rowcount
            conn.commit()
        if not n:
            raise ValueError(f"sample not found: {uid}")
        return {"deleted": int(n), "project_id": pid, "user_id": uid}
    return C.safe(_run)


# ============================================================ LLM（宿主模型作工具）

def _raw_llm(prompt: str, model: str = "", temperature: float = 0.2) -> str:
    """调用宿主 LLM（Ollama 或 Custom API），返回纯文本。"""
    prof = None
    try:
        from src.services.ollama_local_service import CustomLLMService  # type: ignore
    except Exception:
        CustomLLMService = None  # type: ignore

    try:
        from src.services.ollama_local_service import OllamaLocalService  # type: ignore
    except Exception:
        OllamaLocalService = None  # type: ignore

    errors: List[str] = []
    if CustomLLMService is not None:
        try:
            svc = CustomLLMService()  # 默认读取宿主 profile
            for name in ("generate", "chat", "complete", "generate_text"):
                fn = getattr(svc, name, None)
                if callable(fn):
                    try:
                        out = fn(prompt, model=model) if model else fn(prompt)
                        if out:
                            return _as_text(out)
                    except TypeError:
                        out = fn(prompt)
                        if out:
                            return _as_text(out)
        except Exception as e:  # noqa: BLE001
            errors.append(f"CustomLLMService: {e}")

    if OllamaLocalService is not None:
        try:
            svc = OllamaLocalService()
            for name in ("generate", "chat", "complete", "generate_text"):
                fn = getattr(svc, name, None)
                if callable(fn):
                    try:
                        out = fn(prompt, model=model) if model else fn(prompt)
                        if out:
                            return _as_text(out)
                    except TypeError:
                        out = fn(prompt)
                        if out:
                            return _as_text(out)
        except Exception as e:  # noqa: BLE001
            errors.append(f"OllamaLocalService: {e}")

    raise RuntimeError("no host LLM available: " + "; ".join(errors or ["no service method matched"]))


def _as_text(out: Any) -> str:
    if isinstance(out, str):
        return out
    if isinstance(out, dict):
        for k in ("text", "content", "response", "message", "result"):
            v = out.get(k)
            if isinstance(v, str) and v:
                return v
            if isinstance(v, dict) and isinstance(v.get("content"), str):
                return v["content"]
        return json.dumps(out, ensure_ascii=False)[:4000]
    return str(out)


def llm_chat(prompt: str, model: str = "", temperature: float = 0.2) -> Dict:
    """宿主自己的 LLM（Ollama / 自定义 API）。内核的 function calling 不依赖它。"""
    return C.safe(lambda: {"text": _truncate(_raw_llm(str(prompt), str(model), float(temperature)), 12000)})


# ============================================================ 界面（仅 emit 信号）

def gui_status() -> Dict:
    if _UI_BRIDGE is None:
        return C.err("ui bridge not attached")
    return _UI_BRIDGE.gui_status()


def gui_toast(message: str) -> Dict:
    if _UI_BRIDGE is None:
        return C.err("ui bridge not attached")
    return _UI_BRIDGE.gui_toast(str(message))


def gui_navigate(step: int, project_id: str = "") -> Dict:
    if _UI_BRIDGE is None:
        return C.err("ui bridge not attached")
    return _UI_BRIDGE.gui_navigate(int(step), str(project_id or ""))


def gui_log(message: str) -> Dict:
    if _UI_BRIDGE is None:
        return C.err("ui bridge not attached")
    return _UI_BRIDGE.gui_log(str(message))


# ============================================================ 注册表

TOOL_FUNCTIONS = [
    # 只读
    list_projects, get_project, project_summary, list_samples,
    list_storage_files, read_tabular, get_schema_cache, aggregate_project,
    list_dicom_sessions, list_ocr_results, list_documents,
    # 计算
    run_step2_mining, ensure_schema_cache, save_draft, export_drafts_to_word,
    # step2：分析（DuckDB / 统计 / Nature 级绘图 / 关键词）
    # ⚠️ 均为**只读计算**：只产出新文件（图/表），不改动原始数据
    duckdb_tables, duckdb_query, compute_statistics, plot_nature_figure,
    extract_keywords,
    # step3：文献（检索 / 下载 / docxtpl 出稿）
    #   search_papers、download_paper_pdf 是外部网络只读；
    #   render_docx_template、literature_to_docx 只写项目 exports/ 下的新文件
    search_papers, download_paper_pdf, render_docx_template, literature_to_docx,
    # 破坏性（确认门）
    create_project, purge_project, delete_sample,
    # LLM
    llm_chat,
    # 界面
    gui_status, gui_toast, gui_navigate, gui_log,
]
