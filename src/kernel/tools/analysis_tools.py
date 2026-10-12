#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""step2 / step3 的分析与文献工具（宿主侧 MCP 工具面）。

════════════════════════════════════════════════════════════════════════
设计分工（playbook 的架构）
════════════════════════════════════════════════════════════════════════

* **宿主机（本模块）提供"能力"** —— DuckDB 查询、统计检验、Nature 级绘图、
  关键词提取、文献检索/下载、docxtpl 模板渲染。都是可单独调用、可验证的原子工具。
* **opencode 内核提供"大脑"** —— 由它按用户要求决定调用顺序与参数
  （对应 `kernel_assets/skill/data-analysis` 与 `literature-to-docx` 两份 SKILL.md）。
* 所以这里**不写死流程**：`literature_to_docx()` 之类的组合工具只是"一键便捷入口"，
  agent 完全可以自己串原子工具。

════════════════════════════════════════════════════════════════════════
绘图为什么单独强调"nature figure"
════════════════════════════════════════════════════════════════════════

投稿级图表和"随手画的图"差距不在数据，而在**一堆必须遵守的硬规范**：
双栏宽度 183mm / 单栏 89mm、字号 7pt 起、300+ dpi 或矢量、
色盲友好调色板、去掉多余轴线与网格、面板标签加粗斜体。
本模块用统一的 `_nature_style()` 把这些一次设好，避免每个图各写一遍。
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Sequence

try:
    from src.utils.logger import get_logger
    logger = get_logger(__name__)
except Exception:  # pragma: no cover
    import logging
    logger = logging.getLogger(__name__)

MAX_JSON_CHARS = 24000

# 投稿常用尺寸（mm → inch）
MM = 1.0 / 25.4
COL1 = 89 * MM      # 单栏
COL15 = 120 * MM
COL2 = 183 * MM     # 双栏

# 色盲友好调色板（Okabe–Ito 为主，投稿常用）
PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#F0E442",
           "#56B4E9", "#E69F00", "#000000", "#999999", "#8C564B"]


# ================================================================ 通用

def _safe(fn, **kw):
    try:
        return fn(**kw)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"{getattr(fn, '__name__', fn)} 失败: {type(e).__name__}: {e}")
        return {"success": False, "error": f"{type(e).__name__}: {e}"}


def _storage(project_id: str) -> str:
    """复用项目管理里既有的存储路径解析。"""
    from src.kernel.tools.domain_tools import _storage_path
    return _storage_path(project_id) or ""


def _out_dir(project_id: str, kind: str) -> str:
    base = _storage(project_id)
    if not base:
        raise FileNotFoundError(f"项目存储不存在: {project_id}")
    d = os.path.join(base, "exports", f"{kind}_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(d, exist_ok=True)
    return d


def _trunc(s: Any, n: int = MAX_JSON_CHARS) -> str:
    t = str(s or "")
    return t if len(t) <= n else t[:n] + f"\n…(截断，共 {len(t)} 字符)"


def _jsonable(v: Any) -> Any:
    try:
        import numpy as np
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            f = float(v)
            return None if (f != f) else f          # NaN → None（JSON 合法）
        if isinstance(v, (np.bool_,)):
            return bool(v)
        if isinstance(v, np.ndarray):
            return v.tolist()
    except Exception:
        pass
    if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
        return None
    return v


# ================================================================ DuckDB

def _duck_con(project_id: str):
    """建立 DuckDB 连接并挂载项目数据。

    可挂载：项目 SQLite 主库（`database/*.db`）+ 存储目录下的
    csv / parquet / xlsx。全部以视图形式暴露，便于直接写 SQL。

    返回 `(con, attached, failed)` —— **failed 必须一并返回**：
    挂载失败若只写日志，上层就只看到"视图列表是空的"却不知为何
    （实测踩过：CSV 因参数名错误挂不上，结果表现为 views=0 且无任何提示）。
    """
    import duckdb
    con = duckdb.connect(database=":memory:")
    attached: List[Dict[str, Any]] = []
    failed: List[Dict[str, str]] = []

    def _lit(p: str) -> str:
        """把路径内联成 SQL 字面量（单引号转义）。

        ⚠️ 不能用预处理参数 `?`：DuckDB 的 `CREATE VIEW ... AS SELECT *
        FROM read_csv_auto(?)` 会报
        `BinderException: Unexpected prepared parameter. This type of
        statement can't be prepared!`
        —— 视图定义不接受参数化表函数。实测踩过：CSV 因此**一张视图都没挂上**，
        且因异常被吞而只表现为"视图列表为空"。
        """
        return "'" + str(p).replace("'", "''") + "'"

    # 1) 项目存储里的表格文件
    base = _storage(project_id)
    if base and os.path.isdir(base):
        for root, _dirs, files in os.walk(base):
            if os.sep + "exports" in root:
                continue
            for fn in files:
                p = os.path.join(root, fn)
                low = fn.lower()
                try:
                    if low.endswith(".csv") or low.endswith(".tsv"):
                        name = _view_name(con, fn)
                        # 路径内联（见 _lit 的说明：视图定义不能用预处理参数）
                        con.execute(
                            f'CREATE OR REPLACE VIEW "{name}" AS '
                            f"SELECT * FROM read_csv_auto({_lit(p)})")
                        attached.append({"view": name, "type": "csv", "path": p})
                    elif low.endswith(".parquet"):
                        name = _view_name(con, fn)
                        con.execute(
                            f'CREATE OR REPLACE VIEW "{name}" AS '
                            f"SELECT * FROM read_parquet({_lit(p)})")
                        attached.append({"view": name, "type": "parquet", "path": p})
                    elif low.endswith((".xlsx", ".xls")):
                        name = _view_name(con, fn)
                        con.execute("INSTALL excel; LOAD excel;")
                        con.execute(
                            f'CREATE OR REPLACE VIEW "{name}" AS '
                            f"SELECT * FROM read_xlsx({_lit(p)})")
                        attached.append({"view": name, "type": "excel", "path": p})
                except Exception as e:  # noqa: BLE001
                    failed.append({"file": p, "error": f"{type(e).__name__}: {e}"})
                    logger.warning(f"DuckDB 挂载失败 {fn}: {type(e).__name__}: {e}")

    # 2) 主 SQLite 库（把每张表映射成视图）
    try:
        import glob
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        dbs = glob.glob(os.path.join(root, "database", "*.db"))
        if dbs:
            con.execute("INSTALL sqlite; LOAD sqlite;")
            for db in dbs[:2]:
                alias = _view_name(con, "sqlite_" + os.path.basename(db))
                con.execute(f"ATTACH ? AS \"{alias}\" (TYPE SQLITE, READ_ONLY)",
                            [db])
                tabs = [r[0] for r in con.execute(
                    f"SELECT name FROM \"{alias}\".sqlite_master "
                    f"WHERE type='table'").fetchall()]
                for t in tabs:
                    if t.startswith("sqlite_"):
                        continue
                    vname = alias + "__" + re.sub(r"\W+", "_", t)
                    try:
                        con.execute(
                            f'CREATE OR REPLACE VIEW "{vname}" AS '
                            f'SELECT * FROM "{alias}"."{t}"')
                        attached.append({"view": vname, "type": "sqlite",
                                         "path": f"{db}:{t}"})
                    except Exception:
                        pass
    except Exception as e:  # noqa: BLE001
        failed.append({"file": "database/*.db", "error": f"{type(e).__name__}: {e}"})
        logger.info(f"DuckDB 挂载 SQLite 失败: {type(e).__name__}: {e}")

    return con, attached, failed


_NAME_SEEN: Dict[int, set] = {}


def _view_name(con, filename: str) -> str:
    base = re.sub(r"\W+", "_", os.path.splitext(os.path.basename(filename))[0])
    base = re.sub(r"^(\d)", r"t\1", base) or "t"
    key = id(con)
    seen = _NAME_SEEN.setdefault(key, set())
    name, i = base, 1
    while name in seen:
        i += 1
        name = f"{base}_{i}"
    seen.add(name)
    return name


def duckdb_tables(project_id: str) -> Dict:
    """列出项目里可被 DuckDB 查询的表/视图（含行数）。"""
    def _run():
        con, attached, attach_failed = _duck_con(project_id)
        rows = []
        for a in attached:
            try:
                n = con.execute(
                    f'SELECT count(*) FROM "{a["view"]}"').fetchone()[0]
            except Exception:
                n = -1
            cols = []
            try:
                cols = [r[0] for r in con.execute(
                    f'DESCRIBE "{a["view"]}"').fetchall()]
            except Exception:
                pass
            rows.append({**a, "rows": int(n), "columns": cols[:40]})
        con.close()
        out = {"success": True, "count": len(rows), "tables": rows}
        if attach_failed:
            # 挂载失败必须显式回报，否则上层只看到"空列表"而不知原因
            out["attach_failed"] = attach_failed[:12]
        return out
    return _safe(_run)


def duckdb_query(project_id: str, sql: str, limit: int = 500) -> Dict:
    """在项目数据上执行 DuckDB SQL（**只读**）。

    典型用法（投稿数据分析）：
        SELECT group, count(*) n, avg(value) mean FROM t GROUP BY group ORDER BY n DESC;
        SELECT * FROM t ORDER BY value DESC LIMIT 20;
    """
    def _run():
        s = str(sql or "").strip().rstrip(";")
        low = s.lower()
        for bad in ("insert", "update", "delete", "drop", "create", "alter",
                    "attach", "copy", "install", "load", "pragma"):
            if re.search(rf"\b{bad}\b", low):
                return {"success": False,
                        "error": f"仅允许只读查询，检测到禁止关键字: {bad}"}
        con, attached, attach_failed = _duck_con(project_id)
        cur = con.execute(s)
        cols = [d[0] for d in (cur.description or [])]
        rows = cur.fetchmany(int(max(1, min(limit, 5000))))
        data = [[_jsonable(v) for v in r] for r in rows]
        con.close()
        out = {"success": True, "columns": cols, "row_count": len(data),
               "rows": data, "tables": [a["view"] for a in attached]}
        if attach_failed:
            out["attach_failed"] = attach_failed[:12]
        return out
    return _safe(_run)


# ================================================================ 统计

def compute_statistics(project_id: str, table: str, value_column: str,
                       group_column: str = "", test: str = "auto",
                       second_column: str = "") -> Dict:
    """描述统计 + 前提检验 + 组间差异/相关性检验（SciPy）。

    自动流程：
      * 描述统计（n / 均值 / 标准差 / 中位数 / IQR / 峰度偏度）
      * 正态性（Shapiro，n<=5000；否则 D'Agostino）
      * 两组：先 Levene 方差齐性 → 学生 t / Welch t；非正态 → Mann-Whitney U
      * 多组：Levene → 单因素 ANOVA；非正态 → Kruskal-Wallis
      * 给第二列 + 无分组：Pearson（正态）/ Spearman
    """
    def _run():
        import numpy as np
        from scipy import stats as sps

        con, _attached, _failed = _duck_con(project_id)
        # ⚠️ 按需拼列：无分组列时**不能**拼出 `SELECT "", "value"` —— 空列名不是合法 SQL，
        #    实测表现为"相关性检验静默返回空"。顺带改成按**列名**取值，
        #    不再依赖 r[0]/r[1]/r[2] 的位置假设（列组合一变就会错位）。
        cols: List[str] = []
        if group_column:
            cols.append(str(group_column))
        cols.append(str(value_column))
        if second_column:
            cols.append(str(second_column))
        try:
            q = "SELECT " + ", ".join(f'"{c}"' for c in cols) + f' FROM "{table}"'
            rows = con.execute(q).fetchall()
        finally:
            con.close()
        recs = [dict(zip(cols, r)) for r in rows]
        out: Dict[str, Any] = {"success": True, "table": table,
                               "value_column": value_column,
                               "group_column": group_column, "n_raw": len(recs)}
        vals = np.array([r[value_column] for r in recs
                         if r[value_column] is not None], dtype=float)
        if vals.size == 0:
            return {"success": False, "error": "value_column 无有效数值"}
        out["describe"] = {
            "n": int(vals.size), "mean": float(np.mean(vals)),
            "std": float(np.std(vals, ddof=1)) if vals.size > 1 else 0.0,
            "min": float(np.min(vals)), "q1": float(np.percentile(vals, 25)),
            "median": float(np.median(vals)),
            "q3": float(np.percentile(vals, 75)), "max": float(np.max(vals)),
        }
        # 正态性
        try:
            if vals.size >= 3:
                if vals.size <= 5000:
                    st, p = sps.shapiro(vals)
                    out["normality"] = {"test": "shapiro", "stat": float(st),
                                        "p": float(p)}
                else:
                    st, p = sps.normaltest(vals)
                    out["normality"] = {"test": "dagostino", "stat": float(st),
                                        "p": float(p)}
                out["normal"] = bool(out["normality"]["p"] > 0.05)
        except Exception as e:  # noqa: BLE001
            out["normality"] = {"error": str(e)}

        # 分组比较
        if group_column:
            groups: Dict[str, List[float]] = {}
            for r in recs:
                v = r.get(value_column)
                if v is None:
                    continue
                groups.setdefault(str(r.get(group_column)), []).append(float(v))
            arrs = [np.array(v, dtype=float) for v in groups.values() if len(v) >= 2]
            out["groups"] = {k: {"n": len(v),
                                 "mean": float(np.mean(v)),
                                 "median": float(np.median(v)),
                                 "std": float(np.std(v, ddof=1)) if len(v) > 1 else 0.0}
                             for k, v in groups.items()}
            try:
                if len(arrs) == 2:
                    lev_p = float(sps.levene(*arrs).pvalue)
                    out["levene_p"] = lev_p
                    normal_ok = all(
                        sps.shapiro(a).pvalue > 0.05 for a in arrs if a.size >= 3)
                    if normal_ok and lev_p > 0.05:
                        st, p = sps.ttest_ind(*arrs, equal_var=True)
                        used = "student_t"
                    elif normal_ok:
                        st, p = sps.ttest_ind(*arrs, equal_var=False)
                        used = "welch_t"
                    else:
                        st, p = sps.mannwhitneyu(*arrs)
                        used = "mannwhitney_u"
                    out["test"] = {"name": used, "stat": float(st), "p": float(p)}
                elif len(arrs) > 2:
                    lev_p = float(sps.levene(*arrs).pvalue)
                    out["levene_p"] = lev_p
                    normal_ok = all(
                        sps.shapiro(a).pvalue > 0.05 for a in arrs if a.size >= 3)
                    if normal_ok:
                        st, p = sps.f_oneway(*arrs)
                        used = "oneway_anova"
                    else:
                        st, p = sps.kruskal(*arrs)
                        used = "kruskal_wallis"
                    out["test"] = {"name": used, "stat": float(st), "p": float(p)}
            except Exception as e:  # noqa: BLE001
                out["test"] = {"error": f"{type(e).__name__}: {e}"}

        # 相关性
        if second_column and not group_column:
            xs, ys = [], []
            for r in recs:
                a_, b_ = r.get(value_column), r.get(second_column)
                if a_ is None or b_ is None:
                    continue
                xs.append(float(a_))
                ys.append(float(b_))
            if len(xs) >= 3:
                a, b = np.array(xs), np.array(ys)
                normal_ok = (out.get("normal") is True
                             and sps.shapiro(b).pvalue > 0.05)
                if normal_ok:
                    r_, p = sps.pearsonr(a, b)
                    used = "pearson"
                else:
                    r_, p = sps.spearmanr(a, b)
                    used = "spearman"
                out["correlation"] = {"name": used, "r": float(r_), "p": float(p),
                                      "n": len(xs)}
        out["alpha"] = 0.05
        out["significant"] = bool(
            (out.get("test") or {}).get("p", 1.0) < 0.05
            or (out.get("correlation") or {}).get("p", 1.0) < 0.05)
        return json.loads(json.dumps(out, default=_jsonable))
    return _safe(_run)


# ================================================================ Nature 级绘图

def _nature_style(cfg: Dict[str, Any]):
    """把 matplotlib 摆成投稿级默认（一次设好，避免每个图各写一遍）。"""
    import matplotlib
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    cjk = "Source Han Sans CN"
    try:
        from matplotlib import font_manager
        names = {f.name for f in font_manager.fontManager.ttflist}
        if cjk not in names:
            cjk = "DejaVu Sans"
    except Exception:
        cjk = "DejaVu Sans"
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": [cjk, "Arial", "Helvetica", "DejaVu Sans"],
        "font.size": float(cfg.get("font_size", 7)),      # 投稿常用 7pt
        "axes.labelsize": float(cfg.get("font_size", 7)),
        "axes.titlesize": float(cfg.get("font_size", 7)) + 1,
        "xtick.labelsize": float(cfg.get("font_size", 7)) - 1,
        "ytick.labelsize": float(cfg.get("font_size", 7)) - 1,
        "legend.fontsize": float(cfg.get("font_size", 7)) - 1,
        "axes.linewidth": 0.6,          # 细轴线
        "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "xtick.major.size": 2.2, "ytick.major.size": 2.2,
        "axes.spines.top": False,       # 去上/右轴线（chartjunk）
        "axes.spines.right": False,
        "axes.grid": False,             # 默认不画网格
        "axes.axisbelow": True,
        "figure.dpi": 150,
        "savefig.dpi": 600,             # 位图 600dpi
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
        "pdf.fonttype": 42,             # TrueType 嵌入（期刊要求，勿用 3）
        "ps.fonttype": 42,
        "svg.fonttype": "none",         # SVG 保留可编辑文字
        "axes.prop_cycle": __import__("matplotlib").cycler(
            color=PALETTE),
        "errorbar.capsize": 1.8,
        "legend.frameon": False,
        "lines.linewidth": 1.0,
        "lines.markersize": 3.0,
    })
    return plt


def plot_nature_figure(project_id: str, spec: Any, out_name: str = "figure") -> Dict:
    """按投稿规范出图，**同时导出 PDF(矢量) + SVG + PNG(600dpi)**。

    `spec` 可以是 JSON 字符串或 dict：
      {
        "kind": "bar|line|scatter|box|violin|hist|heatmap",
        "table": "视图名",            # 走 DuckDB 取数
        "x": "列名", "y": "列名", "group": "列名",   # heatmap 用 x/y/value
        "title": "...", "xlabel": "...", "ylabel": "...",
        "width": "col1|col15|col2", "height_mm": 60,
        "palette": ["#.."], "log_y": false, "sort": true
      }
    """
    def _run():
        import numpy as np
        cfg = spec if isinstance(spec, dict) else json.loads(str(spec or "{}"))
        plt = _nature_style(cfg)

        table = str(cfg.get("table") or "").strip()
        if not table:
            return {"success": False, "error": "spec.table 必填（先用 duckdb_tables 看可用视图）"}
        con, _attached, _failed = _duck_con(project_id)
        try:
            cols = {c[0] for c in con.execute(f'DESCRIBE "{table}"').fetchall()}
            need = [c for c in (cfg.get("x"), cfg.get("y"), cfg.get("group"),
                                cfg.get("value")) if c]
            missing = [c for c in need if c not in cols]
            if missing:
                return {"success": False,
                        "error": f"表 {table} 缺少列 {missing}；可用列={sorted(cols)[:30]}"}
            sel = ", ".join(f'"{c}"' for c in dict.fromkeys(need))
            rows = con.execute(f'SELECT {sel} FROM "{table}"').fetchall()
            names = list(dict.fromkeys(need))
        finally:
            con.close()

        recs = [dict(zip(names, r)) for r in rows]
        kind = str(cfg.get("kind") or "bar").lower()
        w = {"col1": COL1, "col15": COL15, "col2": COL2}.get(
            str(cfg.get("width") or "col1").lower(), COL1)
        h = float(cfg.get("height_mm", 60)) * MM
        fig, ax = plt.subplots(figsize=(w, h))

        gcol = cfg.get("group")
        ycol = cfg.get("y")
        xcol = cfg.get("x")
        color = cfg.get("color") or PALETTE[0]

        if kind in ("bar", "box", "violin"):
            groups: Dict[str, List[float]] = {}
            for r in recs:
                if r.get(ycol) is None:
                    continue
                groups.setdefault(str(r.get(gcol) or ""), []).append(float(r[ycol]))
            labels = list(groups.keys())
            data = [np.array(groups[k], dtype=float) for k in labels]
            if cfg.get("sort", True) and kind == "bar":
                order = np.argsort([-float(np.mean(d)) for d in data])
                labels = [labels[i] for i in order]
                data = [data[i] for i in order]
            xs = np.arange(len(labels))
            if kind == "bar":
                means = [float(np.mean(d)) for d in data]
                errs = [float(np.std(d, ddof=1) / max(1, np.sqrt(len(d))))
                        if len(d) > 1 else 0.0 for d in data]
                ax.bar(xs, means, yerr=errs, color=color, edgecolor="black",
                       linewidth=0.4, error_kw={"elinewidth": 0.6})
                ax.set_xticks(xs)
                ax.set_xticklabels(labels, rotation=45 if len(labels) > 5 else 0,
                                   ha="right" if len(labels) > 5 else "center")
            elif kind == "box":
                bp = ax.boxplot(data, patch_artist=True, widths=0.6,
                                medianprops={"color": "black", "linewidth": 0.8},
                                boxprops={"linewidth": 0.5, "edgecolor": "black"},
                                whiskerprops={"linewidth": 0.5},
                                capprops={"linewidth": 0.5},
                                flierprops={"markersize": 1.8,
                                            "markerfacecolor": "none",
                                            "markeredgecolor": "#777777"})
                for p in bp.get("boxes") or []:
                    p.set_facecolor(color)
                    p.set_alpha(0.55)
                ax.set_xticklabels(labels, rotation=45 if len(labels) > 5 else 0,
                                   ha="right" if len(labels) > 5 else "center")
            else:
                vp = ax.violinplot(data, showextrema=False, widths=0.7)
                for b in vp.get("bodies") or []:
                    b.set_facecolor(color)
                    b.set_alpha(0.5)
                    b.set_edgecolor("black")
                    b.set_linewidth(0.4)
                ax.set_xticks(xs + 1)
                ax.set_xticklabels(labels, rotation=45 if len(labels) > 5 else 0,
                                   ha="right" if len(labels) > 5 else "center")
        elif kind == "line":
            order = sorted(recs, key=lambda r: (r.get(xcol) is None, r.get(xcol)))
            xs = [r.get(xcol) for r in order if r.get(ycol) is not None]
            ys = [float(r[ycol]) for r in order if r.get(ycol) is not None]
            ax.plot(xs, ys, color=color, marker="o", markeredgewidth=0.3)
        elif kind == "scatter":
            xs = [float(r[xcol]) for r in recs
                  if r.get(xcol) is not None and r.get(ycol) is not None]
            ys = [float(r[ycol]) for r in recs
                  if r.get(xcol) is not None and r.get(ycol) is not None]
            ax.scatter(xs, ys, s=9, facecolor=color, edgecolor="none", alpha=0.85)
        elif kind == "hist":
            vals = [float(r[ycol]) for r in recs if r.get(ycol) is not None]
            ax.hist(vals, bins=int(cfg.get("bins", 24)), color=color,
                    edgecolor="black", linewidth=0.4)
        elif kind == "heatmap":
            vcol = cfg.get("value")
            xs_u = sorted({str(r.get(xcol)) for r in recs})
            ys_u = sorted({str(r.get(ycol)) for r in recs})
            m = np.full((len(ys_u), len(xs_u)), np.nan)
            for r in recs:
                if r.get(vcol) is None:
                    continue
                m[ys_u.index(str(r.get(ycol))), xs_u.index(str(r.get(xcol)))] = float(r[vcol])
            im = ax.imshow(m, aspect="auto", cmap=cfg.get("cmap", "RdYlBu_r"))
            ax.set_xticks(range(len(xs_u)))
            ax.set_xticklabels(xs_u, rotation=45, ha="right")
            ax.set_yticks(range(len(ys_u)))
            ax.set_yticklabels(ys_u)
            cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
            cb.outline.set_linewidth(0.4)
            cb.ax.tick_params(width=0.4, length=1.8)
        else:
            return {"success": False, "error": f"不支持的 kind={kind}"}

        if cfg.get("title"):
            ax.set_title(str(cfg["title"]), fontweight="bold")
        ax.set_xlabel(str(cfg.get("xlabel") or xcol or ""))
        ax.set_ylabel(str(cfg.get("ylabel") or ("" if kind == "bar" else ycol or "")))
        if cfg.get("log_y"):
            ax.set_yscale("log")

        out_dir = _out_dir(project_id, "figures")
        base = os.path.join(out_dir, re.sub(r"\W+", "_", str(out_name)) or "figure")
        paths = {}
        for ext in ("pdf", "svg", "png"):
            p = f"{base}.{ext}"
            fig.savefig(p, format=ext)
            paths[ext] = p
        plt.close(fig)
        return {"success": True, "kind": kind, "rows": len(recs),
                "files": paths, "out_dir": out_dir,
                "width_in": round(w, 3), "height_in": round(h, 3),
                "note": "PDF/SVG 为矢量（投稿首选），PNG 为 600dpi 预览"}
    return _safe(_run)


# ================================================================ 关键词

_STOP = set("""的 了 和 与 及 在 是 为 对 从 到 由 有 无 不 也 就 都 而 之 其 或 一个 一种
this that with from into over under the and for are was were has have had not but you your
我们 他们 它们 可以 通过 进行 使用 采用 结果 方法 研究 分析 数据 显示 表明 以及 相关
基于 分别 具有 不同 相同 显著 增加 降低 提高 减少 该 此 这 那 其中 如图 如表""".split())

_EN_STOP = set("""the a an and or of to in for on with by as at is are was were be been
this that these those it its from not no than then there here we you they he she
can could should would may might must do does did have has had will shall
study studies result results method methods data analysis showed show shown
using used use based significant significantly increase decrease higher lower""".split())


def extract_keywords(project_id: str = "", text: str = "", top_k: int = 30,
                     table: str = "", column: str = "") -> Dict:
    """关键词提取（中英混排，无需额外分词依赖）。

    取词策略：英文按词（≥3 字符，去停用词）+ 中文按 2~4 字 n-gram，
    再用「词频 × 文档覆盖率」做显著性打分。
    """
    def _run():
        from collections import Counter
        corpus: List[str] = []
        if text:
            corpus = [str(text)]
        elif table and column:
            con, _attached, _failed = _duck_con(project_id)
            try:
                rows = con.execute(
                    f'SELECT "{column}" FROM "{table}"').fetchall()
            finally:
                con.close()
            corpus = [str(r[0]) for r in rows if r[0] is not None]
        else:
            return {"success": False,
                    "error": "需要 text，或 table+column（先用 duckdb_tables 看可用视图）"}
        if not corpus:
            return {"success": False, "error": "语料为空"}

        freq: Counter = Counter()
        doc_hits: Counter = Counter()
        zh_re = re.compile(r"[\u4e00-\u9fff]+")
        en_re = re.compile(r"[A-Za-z][A-Za-z\-]{2,}")
        for doc in corpus:
            seen = set()
            for w in en_re.findall(doc):
                wl = w.lower()
                if wl in _EN_STOP or wl in _STOP or len(wl) < 3:
                    continue
                freq[wl] += 1
                seen.add(wl)
            for seg in zh_re.findall(doc):
                for n in (2, 3, 4):
                    for i in range(0, max(0, len(seg) - n + 1)):
                        g = seg[i:i + n]
                        if g in _STOP:
                            continue
                        freq[g] += 1
                        seen.add(g)
            for w in seen:
                doc_hits[w] += 1
        total = max(1, len(corpus))
        scored = []
        for w, c in freq.items():
            if c < 2:
                continue
            coverage = doc_hits[w] / total
            score = (c ** 0.5) * (0.35 + 0.65 * coverage)
            scored.append({"term": w, "freq": int(c),
                           "doc_coverage": round(coverage, 4),
                           "score": round(float(score), 4)})
        scored.sort(key=lambda d: -d["score"])
        top = scored[:int(max(1, min(top_k, 300)))]
        return {"success": True, "documents": len(corpus),
                "vocab": len(freq), "keywords": top}
    return _safe(_run)
