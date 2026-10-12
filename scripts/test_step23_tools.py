#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""step2 / step3 新工具的端到端验证（合成数据，真跑，跑完清理）。

覆盖：
  step2  duckdb_tables / duckdb_query（含只读守卫）/ compute_statistics /
         plot_nature_figure（6 种图型）/ extract_keywords
  step3  search_papers（真实网络）/ download_paper_pdf（真 PDF + 假 PDF 拒绝）/
         render_docx_template（内建模板 ×2）/ literature_to_docx

安全：自建一个临时项目（`step23-selftest-<ts>`）放合成数据，
     结束时**清掉**该项目，不触碰用户既有数据。

用法：
    python scripts/test_step23_tools.py
    python scripts/test_step23_tools.py --keep      # 保留测试项目以便人工查看
"""

import argparse
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("MIMW_SKIN", "metal")

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

OUT = []
RESULTS = []


def say(s=""):
    OUT.append(str(s))
    print(s)


def chk(label, ok, detail=""):
    RESULTS.append((label, bool(ok), detail))
    say(f"   [{'PASS' if ok else 'FAIL'}] {label}: {detail}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    from src.kernel.tools import analysis_tools as A
    from src.kernel.tools import literature_tools as L
    import src.kernel.tools.domain_tools as D

    say("=" * 90)
    say("step2 / step3 工具端到端验证")
    say("=" * 90)

    # ---------------- 用临时目录当"项目存储"，**不建项目、零 DB 残留** ----------------
    # 为什么不建真项目：`ProjectService.create_project` 需要 Project 对象，
    # 而且会在用户数据库里留下行；验证工具没必要污染业务数据。
    # 两个工具模块都是在**函数内部**导入 `_storage_path` 的，
    # 所以这里 monkeypatch 模块属性即可整体改道。
    pid = "step23-selftest"
    TMP = os.path.join(os.environ.get("TEMP", "."), f"step23_selftest_{int(time.time())}")
    os.makedirs(TMP, exist_ok=True)
    D._storage_path = lambda project_id: TMP       # noqa: ARG005
    say(f"   临时存储: {TMP}（monkeypatch _storage_path，不写用户数据库）")

    storage = TMP
    csv_path = os.path.join(storage, "measurements.csv")
    import csv
    import random
    random.seed(7)
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sample_id", "group", "value", "age", "note"])
        for i in range(120):
            g = ["Control", "Treatment", "Placebo"][i % 3]
            base = {"Control": 10.0, "Treatment": 14.5, "Placebo": 10.6}[g]
            w.writerow([f"S{i:03d}", g, round(base + random.gauss(0, 1.5), 3),
                        random.randint(30, 70),
                        f"患者 {i} 号，影像组学特征稳定，随访正常，未见复发征象"])
    say(f"   合成数据: {csv_path}  (120 行)")

    try:
        # ================================================ step2
        say("")
        say("=" * 90)
        say("step2 — DuckDB")
        say("=" * 90)
        t = A.duckdb_tables(pid)
        chk("duckdb_tables 成功", t.get("success") is True,
            f"views={t.get('count')}")
        views = [x["view"] for x in (t.get("tables") or [])]
        say(f"   可用视图: {views[:8]}")
        chk("能看见 measurements.csv", any("measurements" in v for v in views),
            str(views[:5]))
        mv = next((v for v in views if "measurements" in v), "")
        if mv:
            g = A.duckdb_query(pid, f'SELECT "group", count(*) n, '
                                    f'round(avg("value"),3) mean FROM "{mv}" '
                                    f'GROUP BY "group" ORDER BY mean DESC')
            chk("GROUP BY 查询成功", g.get("success") is True, str(g.get("error") or "")[:60])
            chk("返回 3 组", g.get("row_count") == 3, f"row_count={g.get('row_count')}")
            say(f"   结果: {g.get('columns')} {g.get('rows')}")
            wbad = A.duckdb_query(pid, f'DROP TABLE "{mv}"')
            chk("只读守卫拦住 DROP", wbad.get("success") is False,
                str(wbad.get("error"))[:60])
            wbad2 = A.duckdb_query(pid, f'DELETE FROM "{mv}"')
            chk("只读守卫拦住 DELETE", wbad2.get("success") is False,
                str(wbad2.get("error"))[:60])

        say("")
        say("=" * 90)
        say("step2 — 统计检验")
        say("=" * 90)
        if mv:
            st = A.compute_statistics(pid, mv, "value", group_column="group")
            chk("compute_statistics 成功", st.get("success") is True,
                str(st.get("error") or "")[:70])
            chk("有描述统计", bool(st.get("describe")),
                json.dumps(st.get("describe") or {}, ensure_ascii=False)[:110])
            chk("有正态性检验", bool(st.get("normality")),
                json.dumps(st.get("normality") or {}, ensure_ascii=False)[:90])
            chk("多组走 ANOVA/Kruskal",
                (st.get("test") or {}).get("name") in ("oneway_anova", "kruskal_wallis"),
                str((st.get("test") or {}).get("name")))
            p = float((st.get("test") or {}).get("p", 1.0))
            chk("检出显著差异（p<0.05，构造数据故意有差异）", p < 0.05, f"p={p:.3e}")
            st2 = A.compute_statistics(pid, mv, "value", second_column="age")
            chk("相关性检验可用", bool(st2.get("correlation")),
                json.dumps(st2.get("correlation") or {}, ensure_ascii=False)[:110])

        say("")
        say("=" * 90)
        say("step2 — Nature 级绘图")
        say("=" * 90)
        if mv:
            specs = [
                ("bar", {"kind": "bar", "table": mv, "y": "value", "group": "group",
                         "ylabel": "Measurement (a.u.)", "width": "col1"}),
                ("box", {"kind": "box", "table": mv, "y": "value", "group": "group"}),
                ("violin", {"kind": "violin", "table": mv, "y": "value", "group": "group"}),
                ("scatter", {"kind": "scatter", "table": mv, "x": "age", "y": "value"}),
                ("hist", {"kind": "hist", "table": mv, "y": "value", "bins": 20}),
                ("heatmap", {"kind": "heatmap", "table": mv, "x": "group",
                             "y": "age", "value": "value"}),
            ]
            for name, spec in specs:
                r = A.plot_nature_figure(pid, spec, out_name=f"fig_{name}")
                ok = bool(r.get("success"))
                files = r.get("files") or {}
                sizes = {k: (os.path.getsize(v) if os.path.exists(v) else 0)
                         for k, v in files.items()}
                chk(f"plot {name}", ok and all(v > 900 for v in sizes.values()),
                    f"files={ {k: v for k, v in sizes.items()} } "
                    f"{'' if ok else str(r.get('error'))[:70]}")
                if name == "bar" and ok:
                    chk("bar 宽度=单栏 89mm", abs(float(r.get("width_in", 0)) - 89/25.4) < 0.01,
                        f"width_in={r.get('width_in')}")
                    with open(files["pdf"], "rb") as fh:
                        chk("PDF 魔数正确", fh.read(5).startswith(b"%PDF"),
                            "→ %PDF")
                    with open(files["svg"], "rb") as fh:
                        head = fh.read(400)
                        chk("SVG 是矢量文本", b"<svg" in head, "→ <svg")

        say("")
        say("=" * 90)
        say("step2 — 关键词提取")
        say("=" * 90)
        if mv:
            kw = A.extract_keywords(pid, table=mv, column="note", top_k=15)
            chk("extract_keywords 成功", kw.get("success") is True,
                str(kw.get("error") or "")[:70])
            terms = [k["term"] for k in (kw.get("keywords") or [])]
            say(f"   Top 词: {terms[:12]}")
            chk("提出现实词（含中文）",
                any(len(t) >= 2 and not t.isdigit() for t in terms[:8]),
                str(terms[:6]))
        kw2 = A.extract_keywords(text="影像组学 radiomics 特征提取 影像组学 深度学习 "
                                      "deep learning 影像组学 segmentation",
                                 top_k=10)
        t2 = [k["term"] for k in (kw2.get("keywords") or [])]
        chk("纯文本模式可用", kw2.get("success") is True, str(t2[:8]))

        # ================================================ step3
        say("")
        say("=" * 90)
        say("step3 — docxtpl 出稿（内建模板）")
        say("=" * 90)
        ctx = {
            "title": "影像组学特征与预后的关联：自动化验证稿",
            "abstract": "本稿由自动化验证生成，用于确认 docxtpl 通道可用。",
            "keywords": "影像组学；预后；深度学习",
            "introduction": "引言占位。",
            "methods": "方法占位。",
            "results": "结果占位。",
            "discussion": "讨论占位。",
            "conclusion": "结论占位。",
            "data_availability": "数据可向通讯作者索取。",
            "papers": [
                {"source": "europepmc", "year": "2024", "journal": "Nat Med",
                 "title": "Radiomics for outcome prediction", "authors": "Zhang Y, et al.",
                 "doi": "10.1000/xyz1", "url": "https://example.org/1"},
                {"source": "arxiv", "year": "2023", "journal": "arXiv",
                 "title": "Deep learning in imaging", "authors": "Li X, et al.",
                 "doi": "", "url": "https://arxiv.org/abs/2301.00001"},
            ],
        }
        r = L.render_docx_template(pid, ctx, template="builtin:manuscript",
                                   out_name="selftest_manuscript")
        chk("manuscript 渲染成功", r.get("success") is True,
            f"{r.get('path')} {r.get('bytes')}B" if r.get("success")
            else str(r.get("error"))[:80])
        if r.get("success"):
            import zipfile
            with zipfile.ZipFile(r["path"]) as z:
                names = z.namelist()
                body = z.read("word/document.xml").decode("utf-8", "replace")
            chk("是合法 docx（zip 结构）", "word/document.xml" in names,
                f"entries={len(names)}")
            chk("标题已渲染（无未替换占位符）",
                "自动化验证稿" in body and "{{" not in body,
                f"含标题={'自动化验证稿' in body} 残留占位符={'{{' in body}")
            chk("参考文献已渲染",
                "Radiomics for outcome prediction" in body, "→ 找到第 1 条")
        r2 = L.render_docx_template(pid, {"title": "文献综述稿",
                                          "topic": "radiomics",
                                          "papers": ctx["papers"],
                                          "summary": "要点占位"},
                                    template="builtin:literature-review",
                                    out_name="selftest_review")
        chk("literature-review 渲染成功", r2.get("success") is True,
            f"{r2.get('bytes')}B" if r2.get("success") else str(r2.get("error"))[:80])

        say("")
        say("=" * 90)
        say("step3 — 文献检索 / 下载（真实网络）")
        say("=" * 90)
        sp = L.search_papers("radiomics prognosis",
                             sources="europepmc,crossref,arxiv", limit=5)
        say(f"   search_papers: success={sp.get('success')} count={sp.get('count')} "
            f"per_source={sp.get('per_source')}")
        say(f"   source_errors={sp.get('source_errors')}")
        for p in (sp.get("papers") or [])[:3]:
            say(f"     [{p.get('source')}] {p.get('year')} {str(p.get('title'))[:66]}")
        chk("外部检索通道可用（网络）", sp.get("success") is True,
            f"count={sp.get('count')}；若为 False 多为网络/限流，非代码问题")

        # 真 PDF（arXiv）—— 只对找到 arxiv_id 的条目试
        ax = next((p for p in (sp.get("papers") or [])
                   if p.get("source") == "arxiv" and p.get("arxiv_id")), None)
        if ax:
            dl = L.download_paper_pdf(pid, arxiv_id=ax["arxiv_id"],
                                      out_name="selftest_arxiv")
            chk("下载真实 PDF（arXiv）", dl.get("success") is True,
                f"{dl.get('bytes')}B → {dl.get('path')}" if dl.get("success")
                else str(dl.get("error"))[:90])
        else:
            say("   （本次检索未含 arxiv 条目，跳过真实 PDF 下载）")

        # 假 PDF → 必须被拒（这是最容易骗人的一步）
        bad = L.download_paper_pdf(pid, url="https://arxiv.org/abs/2301.00001",
                                   out_name="should_not_save")
        chk("非 PDF 响应被拒绝（不落盘假 PDF）", bad.get("success") is False,
            str(bad.get("error"))[:100])

        # 一键组合
        combo = L.literature_to_docx(pid, "radiomics prognosis", limit=3,
                                     template="builtin:literature-review",
                                     download=0)
        chk("literature_to_docx 一键流程", combo.get("success") is True,
            f"papers={combo.get('papers')} docx={combo.get('docx')}"
            if combo.get("success") else str(combo.get("error"))[:90])

    finally:
        if not args.keep:
            try:
                shutil.rmtree(TMP, ignore_errors=True)
                say("")
                say(f"   已清理临时目录 {TMP}")
            except Exception as e:  # noqa: BLE001
                say(f"   清理失败: {e}")
        else:
            say("")
            say(f"   --keep：产物保留在 {TMP}\\exports")

    failed = [r for r in RESULTS if not r[1]]
    say("")
    say("=" * 90)
    say(f"total={len(RESULTS)} passed={len(RESULTS) - len(failed)} failed={len(failed)}")
    for l, ok, d in RESULTS:
        if not ok:
            say(f"   !! {l}: {d}")
    say("RESULT: " + ("PASS" if not failed else "ISSUES"))

    rep = os.path.join("docs", "screenshots", "step23_tools.txt")
    os.makedirs(os.path.dirname(rep), exist_ok=True)
    with open(rep, "w", encoding="utf-8") as fh:
        fh.write("\n".join(OUT) + "\n")
    print("\n报告 ->", os.path.abspath(rep))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
