#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_step4_word.py —— Step4 图文 Word + 批注链路自检（真实 officeCLI）。"""

import io
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.services import step4_word_service as wsvc  # noqa: E402

OUT = r"C:\Users\chris\AppData\Local\Temp\opencode\step4_word_test"
IMG = r"F:\RSNA\medical_imaging_workflow_release\docs\screenshots\page_2_TextProcessingWidget.png"

RESULTS = []


def chk(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    print(f"   [{'PASS' if ok else 'FAIL'}] {label}: {detail}")


def main() -> int:
    print("=" * 84)
    print("Step4 图文 Word + 批注 自检（officeCLI）")
    print("=" * 84)
    print(f"   officecli available: {wsvc.available()}")
    chk("officecli 可用", wsvc.available(), wsvc._officecli_js())

    result_dict = {
        "outline": {"title": "图文 Word 集成自检"},
        "units": {
            "abstract": {"content": "摘要：本文验证 Step4 图文 Word 与批注链路。"},
            "intro": {"content": "引言段落一。\n\n引言段落二。"},
            "methods": {"content": "研究方法：纳入 120 例患者，采用回顾性队列。"},
            "results": {"content": "结果：A 组优于 B 组（p<0.05）。"},
            "discussion": {"content": "讨论段落。"},
            "conclusion": {"content": "结论段落。"},
        },
        "references": [
            {"citation": "Smith J, et al. Lancet. 2024;1:1-10."},
            {"citation": "Wang L, et al. Nature. 2025;2:20-30."},
        ],
    }
    imgs = [IMG] if os.path.isfile(IMG) else None

    docx = wsvc.build_step4_docx("proj-word-test", result_dict, out_dir=OUT, image_paths=imgs)
    ok_build = bool(docx) and os.path.isfile(docx) and os.path.getsize(docx) > 30000
    chk("生成图文 docx", ok_build,
        f"{docx} ({os.path.getsize(docx) if docx and os.path.isfile(docx) else 0} bytes)")

    if ok_build:
        v = wsvc._run("validate", docx, timeout=120)
        chk("OpenXML 校验", v.get("ok"), str(v.get("stdout") or v.get("stderr"))[:80])

        ok1 = wsvc.add_feedback_comment(docx, "第一轮反馈：请补充样本量的统计细节。",
                                        author="研究者", anchor_text="研究方法")
        chk("批注 1（锚定 方法段）", ok1, "")
        comments = wsvc.list_comments(docx)
        chk("批注已记录", len(comments) >= 1,
            f"count={len(comments)} anchor={(comments[0].get('format') or {}).get('anchoredTo') if comments else ''}")
        pid = None
        try:
            pid = int(str(((comments[0].get("format") or {}).get("id")) or 1))
        except Exception:
            pid = 1
        ok2 = wsvc.add_feedback_comment(docx, "补充说明：请标注单位与变量类型。",
                                        author="研究者", anchor_text="研究方法", parent_id=pid)
        comments2 = wsvc.list_comments(docx)
        chk("批注 2（线程回复）", ok2 and len(comments2) >= 2, f"count={len(comments2)}")

        dest = os.path.join(OUT, "exported_copy.docx")
        try:
            wsvc.export_docx(docx, dest)
            chk("导出副本", os.path.isfile(dest) and os.path.getsize(dest) > 30000, dest)
        except Exception as e:  # noqa: BLE001
            chk("导出副本", False, f"{type(e).__name__}: {e}")

        latest = wsvc.find_latest_step4_docx("proj-word-test", out_dir=OUT)
        chk("sidecar 定位", latest == docx, f"latest={str(latest)[:80]}")

    failed = [r for r in RESULTS if not r[1]]
    print("-" * 84)
    print(f"total={len(RESULTS)} passed={len(RESULTS) - len(failed)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
