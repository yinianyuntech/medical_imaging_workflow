#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""step3 的文献工具（宿主侧 MCP 工具面）：检索 → 下载 → docxtpl 出稿。

三件事，各自独立可验证：

1. `search_papers`  —— Europe PMC（复用既有服务）+ arXiv（Atom API，无需额外依赖）
2. `download_paper_pdf` —— 只对**确定是 PDF** 的响应落盘（校验 `%PDF` 魔数）。
   ⚠️ 这一步最容易骗人：很多出版商的"下载链接"其实返回 HTML 错误页/登录页，
   不校验就会存下一堆假 PDF。
3. `render_docx_template` —— docxtpl 渲染；**自带内建模板**，
   所以即使用户没提供 .docx 也能出稿（模板可换）。
"""

from __future__ import annotations

import json
import os
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

try:
    from src.utils.logger import get_logger
    logger = get_logger(__name__)
except Exception:  # pragma: no cover
    import logging
    logger = logging.getLogger(__name__)

UA = {"User-Agent": "MedicalImagingWorkflow/1.0 (literature-tool)"}
MAX_PDF_MB = 60


def _safe(fn, **kw):
    try:
        return fn(**kw)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"{getattr(fn, '__name__', fn)} 失败: {type(e).__name__}: {e}")
        return {"success": False, "error": f"{type(e).__name__}: {e}"}


def _out_dir(project_id: str, kind: str) -> str:
    from src.kernel.tools.domain_tools import _storage_path
    base = _storage_path(project_id) or ""
    if not base:
        raise FileNotFoundError(f"项目存储不存在: {project_id}")
    d = os.path.join(base, "exports", f"{kind}_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(d, exist_ok=True)
    return d


# ================================================================ 检索

def _search_europepmc(query: str, limit: int) -> tuple:
    """返回 (论文列表, 错误说明)。**错误必须带出来** —— 否则"限流"会被误读成"没有文献"。"""
    try:
        from src.services.europe_pmc_service import EuropePMCService
        svc = EuropePMCService()
        res = svc.search(query, max_results=int(limit)) or []
    except Exception as e:  # noqa: BLE001
        return [], f"异常 {type(e).__name__}: {str(e)[:120]}"
    if not res:
        # 区分"请求失败"与"确实没有命中"：直接探一次 HTTP 状态
        try:
            import requests
            r = requests.get(
                "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                params={"query": query, "format": "json", "pageSize": "1"},
                timeout=15)
            if r.status_code >= 400:
                hint = "（限流，稍后重试）" if r.status_code in (429, 503) else ""
                return [], f"HTTP {r.status_code}{hint}"
            try:
                hits = int((r.json() or {}).get("hitCount") or 0)
            except Exception:
                hits = -1
            return [], f"HTTP 200 但 hitCount={hits}（服务端无命中）"
        except Exception as e:  # noqa: BLE001
            return [], f"探测失败 {type(e).__name__}: {str(e)[:90]}"
    out = []
    for r in res:
        if not isinstance(r, dict):
            continue
        out.append({
            "source": "europepmc",
            "title": str(r.get("title") or "").strip(),
            "authors": str(r.get("authors") or r.get("authorString") or "").strip(),
            "journal": str(r.get("journal") or r.get("journalTitle") or "").strip(),
            "year": str(r.get("year") or r.get("pubYear") or "").strip(),
            "doi": str(r.get("doi") or "").strip(),
            "pmid": str(r.get("pmid") or "").strip(),
            "pmcid": str(r.get("pmcid") or "").strip(),
            "abstract": str(r.get("abstract") or r.get("abstractText") or "")[:1800],
            "url": str(r.get("url") or "").strip(),
        })
    return out, ""


def _search_crossref(query: str, limit: int) -> tuple:
    """CrossRef（覆盖全学科，按需求补的第三源；实测连通性良好）。"""
    import requests
    try:
        r = requests.get(
            "https://api.crossref.org/works",
            params={"query": query, "rows": int(limit),
                    "select": "DOI,title,author,container-title,issued,"
                              "abstract,URL,type"},
            headers=UA, timeout=25)
        if r.status_code >= 400:
            hint = "（限流，稍后重试）" if r.status_code in (429, 503) else ""
            return [], f"HTTP {r.status_code}{hint}"
        items = ((r.json() or {}).get("message") or {}).get("items") or []
    except Exception as e:  # noqa: BLE001
        return [], f"异常 {type(e).__name__}: {str(e)[:120]}"
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        title = (it.get("title") or [""])[0]
        authors = []
        for a in (it.get("author") or [])[:12]:
            fam = str(a.get("family") or "").strip()
            giv = str(a.get("given") or "").strip()
            if fam:
                authors.append(f"{fam} {giv[:1]}".strip())
        year = ""
        try:
            dp = ((it.get("issued") or {}).get("date-parts") or [[None]])[0]
            year = str(dp[0] or "")
        except Exception:
            year = ""
        out.append({
            "source": "crossref",
            "title": re.sub(r"\s+", " ", str(title or "")).strip(),
            "authors": ", ".join(authors)[:400],
            "journal": ((it.get("container-title") or [""])[0] or "").strip(),
            "year": year,
            "doi": str(it.get("DOI") or "").strip(),
            "abstract": re.sub(r"<[^>]+>", "", str(it.get("abstract") or ""))[:1800],
            "url": str(it.get("URL") or "").strip(),
        })
    return out, ""


_ARXIV_NS = {"a": "http://www.w3.org/2005/Atom"}


def _search_arxiv(query: str, limit: int) -> tuple:
    import requests
    try:
        resp = requests.get(
            "http://export.arxiv.org/api/query",
            params={"search_query": f"all:{query}", "start": 0,
                    "max_results": int(limit), "sortBy": "relevance"},
            headers=UA, timeout=25)
        if resp.status_code == 429:
            return [], "HTTP 429（arXiv 限流：需间隔 3 秒以上重试）"
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except Exception as e:  # noqa: BLE001
        return [], f"异常 {type(e).__name__}: {str(e)[:120]}"
    out = []
    for e in root.findall("a:entry", _ARXIV_NS):
        def _t(tag: str) -> str:
            n = e.find(f"a:{tag}", _ARXIV_NS)
            return (n.text or "").strip() if n is not None else ""
        aid = _t("id")
        m = re.search(r"abs/([\d.]+)", aid)
        arxid = m.group(1) if m else aid.rsplit("/", 1)[-1]
        out.append({
            "source": "arxiv",
            "title": re.sub(r"\s+", " ", _t("title")),
            "authors": ", ".join(
                (a.find("a:name", _ARXIV_NS).text or "").strip()
                for a in e.findall("a:author", _ARXIV_NS)
                if a.find("a:name", _ARXIV_NS) is not None)[:400],
            "journal": "arXiv",
            "year": _t("published")[:4],
            "doi": _t("doi"),
            "arxiv_id": arxid,
            "abstract": re.sub(r"\s+", " ", _t("summary"))[:1800],
            "url": aid,
            "pdf_url": f"https://arxiv.org/pdf/{arxid}",
        })
    return out, ""


def search_papers(query: str, sources: str = "europepmc,crossref,arxiv",
                  limit: int = 8) -> Dict:
    """检索文献（多源 + 自动容错）。

    `sources` 逗号分隔，支持：
      * `europepmc` —— 生物医学，含摘要与全文链接（偶发 503 限流）
      * `crossref`  —— 全学科元数据（覆盖广，最稳）
      * `arxiv`     —— 预印本（有 PDF 直链，但有 429 限流）

    任一源失败**不影响其它源**，且失败原因逐源回报（不把"限流"说成"没有文献"）。
    """
    def _run():
        q = str(query or "").strip()
        if not q:
            return {"success": False, "error": "query 不能为空"}
        lim = max(1, min(int(limit or 8), 40))
        want = [s.strip().lower() for s in str(sources or "").split(",") if s.strip()]
        if not want:
            want = ["europepmc", "crossref", "arxiv"]
        fns = {"europepmc": _search_europepmc, "crossref": _search_crossref,
               "arxiv": _search_arxiv}
        got: List[Dict] = []
        errors: List[str] = []
        per_source: Dict[str, int] = {}
        for name in want:
            fn = fns.get(name)
            if fn is None:
                errors.append(f"{name}: 未知源")
                continue
            items, err = fn(q, lim)
            per_source[name] = len(items)
            got.extend(items)
            if err:
                errors.append(f"{name}: {err}")
        # 去重（按 DOI / 标题）
        seen, uniq = set(), []
        for p in got:
            k = (p.get("doi") or "").strip().lower() or \
                re.sub(r"\W+", "", str(p.get("title") or "").lower())[:80]
            if not k or k in seen:
                continue
            seen.add(k)
            uniq.append(p)
        return {"success": bool(uniq), "query": q, "count": len(uniq),
                "raw_count": len(got), "per_source": per_source,
                "papers": uniq, "source_errors": errors}
    return _safe(_run)


# ================================================================ 下载

def download_paper_pdf(project_id: str, url: str = "", arxiv_id: str = "",
                       pmcid: str = "", out_name: str = "") -> Dict:
    """下载 PDF 到项目存储，并**校验确实是 PDF**。

    支持三种入口：直接 `url` / `arxiv_id` / `pmcid`（走 Europe PMC 全文接口）。
    """
    def _run():
        import requests
        target = str(url or "").strip()
        if not target and arxiv_id:
            target = f"https://arxiv.org/pdf/{str(arxiv_id).strip()}"
        if not target and pmcid:
            pid = str(pmcid).strip()
            target = ("https://www.ebi.ac.uk/europepmc/webservices/rest/"
                      f"{pid}/fullTextXML")
        if not target:
            return {"success": False, "error": "需要 url / arxiv_id / pmcid 之一"}

        try:
            resp = requests.get(target, headers=UA, timeout=60, stream=True)
            ctype = str(resp.headers.get("Content-Type") or "")
            head = next(resp.iter_content(8), b"") or b""
            if resp.status_code >= 400:
                return {"success": False, "error": f"http_{resp.status_code}",
                        "url": target, "content_type": ctype}
            is_pdf = head[:5].startswith(b"%PDF") or "application/pdf" in ctype.lower()
            if head[:5].startswith(b"<?xml") or "xml" in ctype.lower():
                return {"success": False, "url": target,
                        "error": "返回的是 XML 全文（非 PDF）。"
                                 "Europe PMC 的 fullTextXML 需另存为 .xml，或换用其他来源。",
                        "content_type": ctype}
            if not is_pdf:
                return {"success": False, "url": target,
                        "error": f"返回的不是 PDF（Content-Type={ctype[:60]}）；"
                                 "常见于出版商的登录页/错误页",
                        "content_type": ctype}
            out_dir = _out_dir(project_id, "literature") if project_id else \
                os.path.join(os.environ.get("TEMP", "."), "lit_pdf")
            os.makedirs(out_dir, exist_ok=True)
            name = re.sub(r"\W+", "_", out_name or os.path.basename(
                target.split("?")[0]))[:80] or "paper"
            if not name.lower().endswith(".pdf"):
                name += ".pdf"
            path = os.path.join(out_dir, name)
            total = 0
            with open(path, "wb") as fh:
                fh.write(head)
                total += len(head)
                for chunk in resp.iter_content(65536):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_PDF_MB * 1024 * 1024:
                        fh.close()
                        os.remove(path)
                        return {"success": False, "error": f"超过 {MAX_PDF_MB}MB 上限"}
                    fh.write(chunk)
            # 落盘后再校验一次（防止半截文件被当成功）
            with open(path, "rb") as fh:
                if not fh.read(5).startswith(b"%PDF"):
                    os.remove(path)
                    return {"success": False, "error": "落盘文件不是 PDF，已删除"}
            return {"success": True, "path": path, "bytes": total,
                    "url": target, "out_dir": out_dir,
                    "content_type": ctype}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": f"{type(e).__name__}: {e}",
                    "url": target}
    return _safe(_run)


# ================================================================ docxtpl

def _build_builtin_template(kind: str, path: str) -> str:
    """内建模板（python-docx 生成，含 Jinja2 占位符 → 交给 docxtpl 渲染）。

    为什么要内建：docxtpl 必须有 .docx 模板；若用户没提供就完全跑不起来。
    内建一份保证"开箱可出稿"，同时**用户可换成自己的模板**（同一套 context）。

    ⚠️ docxtpl 的标签**位置规则**（实测踩过两次）：
      * `{%p for x in xs %}` / `{%p endfor %}` 必须**独占一个段落**；
        与内容写在同一个段落里 → `TemplateSyntaxError: unknown tag 'endfor'`
      * `{%tr for x in xs %}` / `{%tr endfor %}` 必须**独占表格行的单元格**
        （首个单元格，其余留空）→ 否则 `unknown tag 'tr'`
    """
    from docx import Document
    from docx.shared import Pt
    doc = Document()
    kind = (kind or "manuscript").lower()

    def _para(text: str = ""):
        return doc.add_paragraph(text)

    if kind == "literature-review":
        doc.add_heading("{{ title }}", level=0)
        p = _para()
        p.add_run("检索主题：").bold = True
        p.add_run("{{ topic }}")
        p = _para()
        p.add_run("检索时间：").bold = True
        p.add_run("{{ generated_at }}")
        p = _para()
        p.add_run("纳入文献数：").bold = True
        p.add_run("{{ papers|length }}")

        doc.add_heading("文献清单", level=1)
        # 表格循环：标签行 + 内容行 + 结束行（三段式，标签独占单元格）
        table = doc.add_table(rows=4, cols=4)
        table.style = "Table Grid"
        for i, h in enumerate(("来源", "年份", "标题", "期刊")):
            table.rows[0].cells[i].text = h
        table.rows[1].cells[0].text = "{%tr for p in papers %}"
        body = table.rows[2].cells
        body[0].text = "{{ p.source }}"
        body[1].text = "{{ p.year }}"
        body[2].text = "{{ p.title }}"
        body[3].text = "{{ p.journal }}"
        table.rows[3].cells[0].text = "{%tr endfor %}"

        doc.add_heading("要点归纳", level=1)
        _para("{{ summary or '（待补：可用 llm_chat 或 opencode agent 生成）' }}")

        doc.add_heading("参考文献", level=1)
        _para("{%p for p in papers %}")
        _para("{{ loop.index }}. {{ p.authors }}. {{ p.title }}. "
              "{{ p.journal }} {{ p.year }}. {{ p.doi or p.url }}")
        _para("{%p endfor %}")
    else:
        doc.add_heading("{{ title }}", level=0)
        for sec, key in (("摘要", "abstract"), ("关键词", "keywords"),
                         ("引言", "introduction"), ("方法", "methods"),
                         ("结果", "results"), ("讨论", "discussion"),
                         ("结论", "conclusion")):
            doc.add_heading(sec, level=1)
            _para("{{ %s or '（待补）' }}" % key)
        doc.add_heading("数据可用性", level=1)
        _para("{{ data_availability or '（待补）' }}")
        doc.add_heading("参考文献", level=1)
        _para("{%p for p in papers %}")
        _para("{{ loop.index }}. {{ p.authors }}. {{ p.title }}. "
              "{{ p.journal }} {{ p.year }}. {{ p.doi or p.url }}")
        _para("{%p endfor %}")

    try:
        for s in doc.styles:
            if s.name and s.name.startswith("Normal") and s.font:
                s.font.size = Pt(10.5)
    except Exception:
        pass
    doc.save(path)
    return path


def render_docx_template(project_id: str, context: Any,
                         template: str = "builtin:manuscript",
                         out_name: str = "draft") -> Dict:
    """docxtpl 渲染。

    `template` 支持：
      * `builtin:manuscript` / `builtin:literature-review` —— 内建模板
      * 任意 `.docx` 路径 —— 用户自己的模板（占位符用 `{{ key }}`）
    """
    def _run():
        from docxtpl import DocxTemplate
        ctx = context if isinstance(context, dict) else json.loads(str(context or "{}"))
        if not isinstance(ctx, dict):
            return {"success": False, "error": "context 必须是 JSON 对象"}
        ctx.setdefault("generated_at", time.strftime("%Y-%m-%d %H:%M:%S"))
        ctx.setdefault("papers", [])
        out_dir = _out_dir(project_id, "docx") if project_id else \
            os.path.join(os.environ.get("TEMP", "."), "docx_out")
        os.makedirs(out_dir, exist_ok=True)

        tpl = str(template or "").strip()
        if tpl.startswith("builtin:"):
            kind = tpl.split(":", 1)[1] or "manuscript"
            tpl_path = os.path.join(out_dir, f"_template_{kind}.docx")
            _build_builtin_template(kind, tpl_path)
        else:
            tpl_path = tpl
            if not os.path.isfile(tpl_path):
                return {"success": False, "error": f"模板不存在: {tpl_path}"}

        doc = DocxTemplate(tpl_path)
        # 缺失变量不要让渲染整体失败：用 Undefined 静默为空串
        doc.render(ctx, autoescape=True)
        name = re.sub(r"\W+", "_", out_name or "draft")[:60] or "draft"
        out = os.path.join(out_dir, name + ".docx")
        doc.save(out)
        size = os.path.getsize(out)
        return {"success": True, "path": out, "bytes": size,
                "template": tpl, "template_used": tpl_path,
                "context_keys": sorted(ctx.keys())[:40], "out_dir": out_dir}
    return _safe(_run)


# ================================================================ 组合流程

def literature_to_docx(project_id: str, topic: str, limit: int = 8,
                       template: str = "builtin:literature-review",
                       download: int = 0,
                       sources: str = "europepmc,crossref,arxiv",
                       extra_context: Any = None) -> Dict:
    """**一键**：检索 →（可选）下载 PDF → 组装 context → docxtpl 出稿。

    只是便捷入口；agent 也可以自己串三个原子工具（更灵活）。
    """
    def _run():
        s = search_papers(topic, sources=sources, limit=limit)
        if not s.get("success"):
            return {"success": False, "step": "search",
                    "error": s.get("error") or "检索无结果",
                    "source_errors": s.get("source_errors")}
        papers = s.get("papers") or []
        dl: List[Dict] = []
        for p in papers[:max(0, int(download or 0))]:
            r = download_paper_pdf(project_id, url=p.get("pdf_url") or "",
                                   arxiv_id=p.get("arxiv_id") or "",
                                   pmcid=p.get("pmcid") or "",
                                   out_name=re.sub(r"\W+", "_", p.get("title") or "")[:50])
            dl.append({"title": (p.get("title") or "")[:80],
                       "success": bool(r.get("success")),
                       "path": r.get("path") or "", "error": r.get("error") or ""})
        ctx: Dict[str, Any] = {
            "title": f"{topic}：文献综述",
            "topic": topic,
            "papers": papers,
            "downloaded": dl,
        }
        if isinstance(extra_context, str) and extra_context.strip():
            try:
                ctx.update(json.loads(extra_context))
            except Exception:
                pass
        elif isinstance(extra_context, dict):
            ctx.update(extra_context)
        r = render_docx_template(project_id, ctx, template=template,
                                 out_name=f"lit_review_{re.sub(r'\\W+', '_', topic)[:30]}")
        if not r.get("success"):
            return {"success": False, "step": "render", "error": r.get("error"),
                    "papers": len(papers)}
        return {"success": True, "papers": len(papers), "downloaded": dl,
                "docx": r.get("path"), "bytes": r.get("bytes"),
                "template": template, "source_errors": s.get("source_errors")}
    return _safe(_run)
