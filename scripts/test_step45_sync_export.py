#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_step45_sync_export.py —— 正文同步（set）+ 批注存活 + 一稿一 docx 批量导出 自检。"""

import io
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s, None).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.services import step4_word_service as wsvc  # noqa: E402

OUT = r"C:\Users\chris\AppData\Local\Temp\opencode\step45_sync_test"
IMG = r"F:\RSNA\medical_imaging_workflow_release\docs\screenshots\page_2_TextProcessingWidget.png"

RESULTS = []


def chk(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    print(f"   [{'PASS' if ok else 'FAIL'}] {label}: {detail}")


def para_texts(docx):
    return [p["text"] for p in wsvc._query_paragraphs(docx)]


def main() -> int:
    print("=" * 86)
    print("正文同步 + 批注存活 + 批量导出 自检")
    print("=" * 86)
    chk("officecli 可用", wsvc.available(), "")

    result_dict = {
        "outline": {"title": "同步自检"},
        "units": {
            "intro": {"content": "引言：原始引言。"},
            "methods": {"content": "研究方法：纳入 120 例患者，采用回顾性队列。"},
            "results": {"content": "结果：A 组优于 B 组（p<0.05）。"},
            "discussion": {"content": "讨论：原始讨论。"},
        },
        "references": [{"citation": "Smith J. Lancet. 2024."}],
    }
    docx = wsvc.build_step4_docx("proj-sync-test", result_dict, out_dir=OUT,
                                 image_paths=[IMG] if os.path.isfile(IMG) else None)
    chk("图文 docx 就绪", bool(docx) and os.path.isfile(docx), str(docx)[-60:])
    if not docx:
        return 1

    # 先加一条批注（锚定 Methods 段）
    ok_c = wsvc.add_feedback_comment(docx, "请把样本量改到 150。", anchor_text="研究方法")
    n0 = len(wsvc.list_comments(docx))
    chk("批注初始", ok_c and n0 >= 1, f"comments={n0}")

    # 1) 章节同步：Methods 替换为 150 例
    new_methods = "研究方法：纳入 150 例患者；采用前瞻性设计。\n\n数据来源为电子病历。"
    ok1 = wsvc.sync_section_text(docx, "Methods", new_methods)
    texts = para_texts(docx)
    has_new = any("150 例" in t for t in texts)
    has_old = any("120 例" in t for t in texts)
    n1 = len(wsvc.list_comments(docx))
    chk("正文同步（Methods→150 例）", ok1 and has_new and not has_old,
        f"ok={ok1} new={has_new} old_gone={not has_old}")
    chk("同步后批注存活", n1 == n0, f"comments {n0}->{n1}")

    # 2) 片段级替换：150 例患者 → 160 例患者
    ok2 = wsvc.sync_fragment_text(docx, "150 例患者", "160 例患者")
    texts2 = para_texts(docx)
    chk("片段替换（150→160）", ok2 and any("160 例" in t for t in texts2),
        f"ok={ok2} hit={any('160 例' in t for t in texts2)}")
    n2 = len(wsvc.list_comments(docx))
    chk("片段替换后批注仍存活", n2 == n0, f"comments {n0}->{n2}")

    # 3) 整篇同步（Rethink 场景）
    full = ("# 同步自检\n\n## Introduction\n引言：更新后的引言。\n\n"
            "## Methods\n研究方法：更新后的方法。\n\n## Discussion\n讨论：更新后的讨论。")
    ok3 = wsvc.sync_full_text(docx, full)
    texts3 = para_texts(docx)
    chk("整篇同步（Rethink）",
        ok3 and any("更新后的引言" in t for t in texts3)
        and any("更新后的方法" in t for t in texts3),
        f"ok={ok3}")
    n3 = len(wsvc.list_comments(docx))
    chk("整篇同步后批注仍存活", n3 == n0, f"comments {n0}->{n3}")
    v = wsvc._run("validate", docx, timeout=120)
    chk("同步后 OpenXML 校验", v.get("ok"), str(v.get("stdout") or v.get("stderr"))[:70])

    # 4) 一稿一 docx 批量导出
    drafts = [
        {"id": "draft_a1b2", "title": "初稿 v1", "content": "# 初稿\n\n## Introduction\n第一版引言。"},
        {"id": "draft_c3d4", "title": "精修 v2", "content": "# 精修\n\n## Methods\n第二版方法。"},
        {"id": "draft_empty", "title": "空稿", "content": ""},
    ]
    dest = os.path.join(OUT, "drafts")
    paths = wsvc.export_drafts_batch("proj-sync-test", drafts=drafts, dest_dir=dest)
    ok4 = len(paths) == 2 and all(os.path.isfile(p) and os.path.getsize(p) > 1000 for p in paths)
    chk("批量一稿一 docx（空稿跳过）", ok4,
        f"files={[os.path.basename(p) for p in paths]}")
    if paths:
        v2 = wsvc._run("validate", paths[0], timeout=120)
        chk("批量产物 OpenXML 校验", v2.get("ok"), str(v2.get("stdout") or v2.get("stderr"))[:70])

    failed = [r for r in RESULTS if not r[1]]
    print("-" * 86)
    print(f"total={len(RESULTS)} passed={len(RESULTS) - len(failed)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
