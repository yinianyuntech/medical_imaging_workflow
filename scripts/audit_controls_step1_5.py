#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""step1~5 全控件功能排查（两阶段 + 逐条日志续跑）。

════════════════════════════════════════════════════════════════════════
为什么是这个架构（踩坑记录）
════════════════════════════════════════════════════════════════════════

第一版把"枚举控件 → 逐个点击"写在同一个循环里，结果**进程硬崩溃（段错误）**：
有些按钮（刷新列表之类）会**重建 UI、销毁旧控件**，而循环还持有列表里后续的
旧 Python 包装器 → 访问已释放的 C++ 对象 → 段错误（没有 Python 异常、没有提示）。

因此改为：

1. **每次点击前重新枚举**该页控件，并校验 `sip.isdeleted()` / 存活。
2. **逐条写日志**（JSONL，append + flush）。硬崩溃只会丢当前这一条，
   用 `--resume` 续跑即可，报告从日志重建（跨进程完整）。
3. **两阶段**：`--inventory` 只清点（绝不点击，零风险）先摸清全貌，
   再分组执行点击。

════════════════════════════════════════════════════════════════════════
安全设计（第一原则：绝不改动用户数据）
════════════════════════════════════════════════════════════════════════

* **破坏性控件绝不自动点击**（删除/清空/重置/覆盖…），只报告可用性与连接情况。
* **重任务控件不自动点击**（开始/执行/批量/训练/加载/同步/重建…）。
* 弹出的模态框一律 **reject** —— 即使某个"安全"按钮背后藏着破坏性确认框也不会执行。
* 运行前后核对项目数/样本数/数据库文件，用证据证明没有改动数据。
* 记录并**还原初始项目**（点"切换项目"这类控件会改工作上下文）。
* 捕获三类失败：slot 内异常（sys.excepthook）、logger ERROR、对话框打不开/卡死。

用法：
    python scripts/audit_controls_step1_5.py --inventory        # 只清点（安全）
    python scripts/audit_controls_step1_5.py --step 1           # 测第一步
    python scripts/audit_controls_step1_5.py --resume --step 2  # 崩溃后续跑
    python scripts/audit_controls_step1_5.py --report           # 只看已有日志的报告
"""

import argparse
import json
import logging
import os
import re
import sys
import time
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("MIMW_SKIN", "metal")

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.core.qt_compat.QtCore import Qt, QTimer  # noqa: E402
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QScrollArea, QAbstractButton, QComboBox, QLineEdit,
    QAbstractSlider, QAbstractSpinBox, QTextEdit, QPlainTextEdit, QTabWidget,
    QGroupBox, QLabel, QSlider, QCheckBox, QPushButton, QToolButton,
)

JOURNAL = os.path.join("docs", "screenshots", "controls_audit.jsonl")
REPORT = os.path.join("docs", "screenshots", "controls_audit.txt")

# ================================================================ 分类

DESTRUCTIVE = ("删除", "清空", "清除", "重置", "覆盖", "替换", "卸载", "移除",
               "废弃", "delete", "remove", "clear", "reset", "purge", "drop", "wipe")
# 纯图标按钮：文字里没有可判别的词，靠 emoji 兜底（否则会被当"未知"点击）
DESTRUCTIVE_MARK = ("🗑", "❌", "✖", "⛔", "🚫", "×")
HEAVY = ("开始", "执行", "运行", "批量", "一键", "全部", "训练", "加载", "载入",
         "下载", "安装", "同步", "重建", "生成", "提交", "保存", "写入", "导出",
         "上传", "挖掘", "run", "start", "batch", "build", "sync", "submit", "save",
         "export", "load", "train", "install", "download", "wizard")
SAFE = ("刷新", "查看", "详情", "预览", "选择", "浏览", "统计", "检查", "测试",
        "关于", "帮助", "展开", "折叠", "上一页", "下一页", "首页", "末页",
        "打开", "显示", "切换", "排序", "筛", "过滤", "搜索", "查询",
        "refresh", "view", "detail", "preview", "test", "check", "about", "help")


def classify(text: str) -> str:
    """把控件分成 safe / destructive / heavy / unknown。

    ⚠️ **判定顺序至关重要**：破坏性必须**最先**判定。
       否则 `清空选择` 会先命中 SAFE 里的 `选择`，被误判成"安全控件"而遭自动点击
       —— 这是一个真实的分类漏洞（第一版就踩到了）。
       另外 `覆盖层`(overlay) 是名词，不是"覆盖"，需要排除，否则会误伤。
    """
    t = (text or "").strip()
    low = t.lower()

    def has(words, skip=()):
        for w in words:
            if w in t or w in low:
                if any(s in t for s in skip):
                    continue
                return True
        return False

    if has(DESTRUCTIVE, skip=("覆盖层",)):
        return "destructive"
    if any(m in t for m in DESTRUCTIVE_MARK):
        return "destructive"
    if has(SAFE):
        return "safe"
    if has(HEAVY):
        return "heavy"
    return "unknown"


INTERACTIVE = (QAbstractButton, QComboBox, QLineEdit, QAbstractSlider,
               QAbstractSpinBox, QTextEdit, QPlainTextEdit, QTabWidget,
               QGroupBox, QSlider)

SIGNAL_CANDIDATES = {
    "QAbstractButton": ("clicked", "toggled", "stateChanged", "pressed"),
    "QComboBox": ("currentIndexChanged", "currentTextChanged", "activated"),
    "QLineEdit": ("textChanged", "textEdited", "editingFinished", "returnPressed"),
    "QAbstractSlider": ("valueChanged", "sliderMoved"),
    "QTabWidget": ("currentChanged", "tabBarClicked"),
    "QAbstractSpinBox": ("valueChanged", "editingFinished"),
}


def ctrl_text(w) -> str:
    try:
        if isinstance(w, QLabel):
            return re.sub(r"<[^>]+>", "", str(w.text() or ""))[:44]
        if isinstance(w, QAbstractButton):
            return str(w.text() or "").replace("&", "").strip()
        if isinstance(w, QComboBox):
            return f"[combo] {w.currentText()}"
        if isinstance(w, QLineEdit):
            return f"[input] {w.placeholderText() or w.text()[:14]}"
        if isinstance(w, (QTextEdit, QPlainTextEdit)):
            return f"[multi] {w.placeholderText()[:18] or '(无占位)'}"
        if isinstance(w, QTabWidget):
            return f"[tabs] {w.count()} 页"
        if isinstance(w, QGroupBox):
            return f"[group] {w.title()}"
        if isinstance(w, QAbstractSlider):
            return f"[slider] {w.value()}"
        return type(w).__name__
    except Exception:
        return type(w).__name__


def n_receivers(obj, sig: str) -> int:
    try:
        return int(obj.receivers(getattr(obj, sig)))
    except Exception:
        pass
    try:
        return int(obj.receivers(f"2{sig}()"))
    except Exception:
        return -1


def probe_signals(w) -> tuple:
    from src.core.qt_compat import QtWidgets as _W
    for cls_name in ("QAbstractButton", "QComboBox", "QLineEdit",
                     "QAbstractSlider", "QTabWidget", "QAbstractSpinBox"):
        cls = getattr(_W, cls_name, None)
        if cls is not None and isinstance(w, cls):
            best, hit = -1, []
            for nm in SIGNAL_CANDIDATES[cls_name]:
                if not hasattr(w, nm):
                    continue
                v = n_receivers(w, nm)
                if v > 0:
                    hit.append(nm)
                best = max(best, v)
            return best, tuple(hit)
    return -1, ()


def alive(w) -> bool:
    if w is None:
        return False
    try:
        import PyQt6.sip as _sip
        if _sip.isdeleted(w):
            return False
    except Exception:
        pass
    try:
        w.objectName()
        w.isEnabled()
        return True
    except Exception:
        return False


def collect(page):
    out = []
    try:
        kids = page.findChildren(QWidget)
    except Exception:
        return out
    for c in kids:
        if not alive(c):
            continue
        try:
            if isinstance(c, INTERACTIVE) and c.isVisible() and not c.isWindow():
                out.append(c)
        except Exception:
            continue
    return out


def ckey(w) -> str:
    try:
        g = w.geometry()
        return f"{type(w).__name__}|{ctrl_text(w)[:22]}|{g.x()},{g.y()}"
    except Exception:
        return f"{type(w).__name__}|?|?"


def snapshot(win):
    snap = {}
    try:
        pm = win.project_management_widget
        snap["projects"] = str(len(getattr(pm, "project_items", []) or []))
        for attr in ("stats_label", "count_label", "stats_text"):
            lb = getattr(pm, attr, None)
            if lb is not None:
                snap[attr] = ctrl_text(lb)
    except Exception as e:  # noqa: BLE001
        snap["err"] = str(e)
    try:
        for root in ("data", "."):
            if not os.path.isdir(root):
                continue
            for fn in os.listdir(root):
                if fn.endswith(".db"):
                    p = os.path.join(root, fn)
                    st = os.stat(p)
                    snap[f"db:{fn}"] = f"{st.st_size}B"
    except Exception:
        pass
    return snap


# ================================================================ 采集器

class Collector:
    def __init__(self, app):
        self.app = app
        self.exceptions = []
        self.log_errors = []
        self.dialogs = []
        self._prev = sys.excepthook
        self._timer = None

    def start(self):
        sys.excepthook = self._hook

        class _H(logging.Handler):
            def emit(inner, rec):
                try:
                    if rec.levelno >= logging.ERROR:
                        self.log_errors.append(f"{rec.name}: {rec.getMessage()[:260]}")
                except Exception:
                    pass

        self._h = _H(level=logging.ERROR)
        logging.getLogger().addHandler(self._h)
        self._timer = QTimer()
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._close_modal)
        self._timer.start()

    def _hook(self, etype, value, tb):
        self.exceptions.append(
            "".join(traceback.format_exception(etype, value, tb))[-900:])

    def _close_modal(self):
        try:
            d = self.app.activeModalWidget()
        except Exception:
            return
        if d is None:
            return
        try:
            self.dialogs.append(f"{type(d).__name__}:{(d.windowTitle() or '')[:24]}")
            d.reject()
        except Exception:
            try:
                d.close()
            except Exception:
                pass

    def mark(self):
        return (len(self.exceptions), len(self.log_errors), len(self.dialogs))

    def delta(self, m):
        return (len(self.exceptions) - m[0], len(self.log_errors) - m[1],
                len(self.dialogs) - m[2])

    def stop(self):
        sys.excepthook = self._prev
        try:
            logging.getLogger().removeHandler(self._h)
        except Exception:
            pass
        if self._timer:
            self._timer.stop()


STEP_PAGES = {1: [0, 1, 2, 3, 4], 2: [5], 3: [6], 4: [7], 5: [8]}
STEP_TITLE = {1: "第一步 数据整理", 2: "第二步 数据清洗及结构化",
              3: "第三步 本地大模型数据科学总结", 4: "第四步 科学文本预览生成",
              5: "第五步 研究者真实反馈及迭代优化"}


def load_journal():
    rows = []
    if os.path.exists(JOURNAL):
        with open(JOURNAL, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows


def coverage_section(rows):
    """覆盖情况 + 未自动验证清单。

    必须逐条讲清楚"哪些控件没有被验证"，不能含糊。
    放在这里（而不是 main 里）是为了 `--report` 模式也能产出。
    """
    out = []
    # 按**类型**判定"非交互容器"更准确：分组框/文本区本就不需要点击，
    # 它们出现在清单里只是因为 findChildren 会把容器也找出来。
    CONTAINER_TYPES = ("QGroupBox", "QTextEdit", "QPlainTextEdit")
    unsupported = [r for r in rows if r["type"] in CONTAINER_TYPES
                   or (r["res"] == "SKIP" and "类型不支持" in r.get("note", ""))]
    _uns_key = {(r["step"], r["page"], r["key"]) for r in unsupported}
    blocked = [r for r in rows if r["res"] == "SKIP"
               and (r["step"], r["page"], r["key"]) not in _uns_key]
    disabled = [r for r in rows if r["res"] == "DISABLED"]
    ok = [r for r in rows if r["res"] == "OK"]
    out.append("")
    out.append("=" * 92)
    out.append("覆盖情况与未自动验证清单（本次排查的边界）")
    out.append("=" * 92)
    out.append(f"   已实际点击验证   : {len(ok)}")
    out.append(f"   未验证合计       : {len(blocked) + len(disabled) + len(unsupported)}"
               f"   = 破坏性/重任务 {len(blocked)} + 当前不可用 {len(disabled)}"
               f" + 非交互容器 {len(unsupported)}")
    out.append("")
    out.append(f"   【破坏性 / 重任务：按安全策略未触发，需人工确认】{len(blocked)} 个")
    for r in blocked:
        out.append(f"      · {r['page']:<24} {r['label'][:28]:<30} "
                   f"{r['kind']:<12} {r['note'][:22]}")
    out.append("")
    out.append(f"   【当前不可用（多为「未选样本」时的正常禁用）】{len(disabled)} 个")
    for r in disabled:
        out.append(f"      · {r['page']:<24} {r['label'][:28]:<30} {r['kind']}")
    if unsupported:
        out.append("")
        out.append(f"   【非交互容器（分组框/文本区），无需点击】{len(unsupported)} 个")
        byp = {}
        for r in unsupported:
            byp.setdefault(r["page"], []).append(r["label"][:16])
        for pg, labs in byp.items():
            out.append(f"      · {pg:<24} {len(labs)} 个：{', '.join(labs[:6])}")
    return out


def build_report(rows, extra_lines):
    lines = []
    lines.append("=" * 96)
    lines.append("step1~5 全控件功能排查报告")
    lines.append("=" * 96)
    lines.append(f"   记录条数: {len(rows)}   （来自日志 {JOURNAL}，可跨进程累计）")
    lines.append("")
    for s in (1, 2, 3, 4, 5):
        sel = [r for r in rows if r["step"] == s]
        if not sel:
            continue
        lines.append("")
        lines.append("=" * 96)
        lines.append(f"{STEP_TITLE[s]}    控件 {len(sel)} 个")
        lines.append("=" * 96)
        cur = None
        for r in sorted(sel, key=lambda x: (x["page"], x.get("idx", 0))):
            if r["page"] != cur:
                cur = r["page"]
                lines.append("")
                lines.append(f"── {cur} ──")
                lines.append(f"   {'控件':<28} {'类型':<16} {'可用':<4} {'接收':<5} "
                             f"{'类别':<12} {'结果':<8} 备注")
                lines.append("   " + "-" * 92)
            lines.append(
                f"   {r['label'][:26]:<28} {r['type']:<16} "
                f"{('是' if r['enabled'] else '否'):<4} {r['recv']:<5} "
                f"{r['kind']:<12} {r['res']:<8} {r.get('note', '')[:38]}")
    lines.extend(extra_lines)
    lines.extend(coverage_section(rows))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=int, default=0)
    ap.add_argument("--inventory", action="store_true", help="只清点，绝不点击")
    ap.add_argument("--resume", action="store_true", help="跳过日志里已测过的控件")
    ap.add_argument("--report", action="store_true", help="只重建报告，不启动界面")
    ap.add_argument("--reset", action="store_true", help="清空日志重新开始")
    args = ap.parse_args()

    if args.reset and os.path.exists(JOURNAL):
        os.remove(JOURNAL)

    if args.report:
        rows = load_journal()
        text = build_report(rows, ["", "（--report 模式：未执行测试）"])
        print(text)
        with open(REPORT, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        return 0

    app = QApplication.instance() or QApplication([])

    # ⚠️ 关掉**原生对话框**：Windows 原生文件对话框不是 Qt 控件，
    #    `activeModalWidget()` 拿不到它 → 自动关闭器失效 → 排查会**卡死**在
    #    "选择文件"这类按钮上（阻塞在原生模态循环里，超时也救不回来）。
    #    改用 Qt 自带对话框后，自动关闭器才能生效。
    try:
        app.setAttribute(Qt.AA_DontUseNativeDialogs, True)
    except Exception:
        pass

    from src.utils import skeuomorphic as sk
    from src.utils import skeuo_style as st
    sk.apply_global(app)
    st.install(app)

    from ui.widgets.main_window import MainWindow
    win = MainWindow(remaining_seconds=0, license_exp_ts=0)
    win.resize(1680, 1000)
    win.show()

    def pump(n=10, dt=0.03):
        for _ in range(n):
            app.processEvents()
            time.sleep(dt)

    pump(26)

    col = Collector(app)
    col.start()

    try:
        _cp = win.project_management_widget.current_project
        initial_project = getattr(_cp, "project_id", None)
    except Exception:
        initial_project = None

    before = snapshot(win)

    rows = load_journal()
    # 清点记录（INV）不应阻止后续真实测试 —— 实测开始时把它们清掉
    if not args.inventory and rows:
        rows = [r for r in rows if r.get("res") != "INV"]
        with open(JOURNAL, "w", encoding="utf-8", newline="\n") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    seen = {(r["step"], r["page"], r["key"]) for r in rows}
    jfh = open(JOURNAL, "a", encoding="utf-8", newline="\n")

    def jrec(rec):
        rows.append(rec)
        jfh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        jfh.flush()

    def invoke(w):
        m = col.mark()
        done = {"v": False}
        t0 = time.time()

        if isinstance(w, QAbstractButton):
            was = None
            try:
                was = bool(w.isChecked()) if w.isCheckable() else None
            except Exception:
                was = None

            def _act():
                try:
                    w.click()
                    if was is not None:
                        app.processEvents()
                        w.setChecked(was)
                finally:
                    done["v"] = True
        elif isinstance(w, QComboBox):
            idx = w.currentIndex()
            nxt = 0 if idx != 0 else min(1, w.count() - 1)

            def _act():
                try:
                    if w.count() > 1:
                        w.setCurrentIndex(nxt)
                        app.processEvents()
                        w.setCurrentIndex(idx)
                finally:
                    done["v"] = True
        elif isinstance(w, QLineEdit):
            old = w.text()

            def _act():
                try:
                    w.setText(old + "x")
                    app.processEvents()
                    w.setText(old)
                finally:
                    done["v"] = True
        elif isinstance(w, QAbstractSlider):
            old = w.value()

            def _act():
                try:
                    w.setValue(min(w.maximum(), old + 1))
                    app.processEvents()
                    w.setValue(old)
                finally:
                    done["v"] = True

        elif isinstance(w, QAbstractSpinBox):
            old = w.value()

            def _act():
                try:
                    if isinstance(old, float):
                        w.setValue(min(float(w.maximum()), old + 0.1))
                    else:
                        w.setValue(min(int(w.maximum()), int(old) + 1))
                    app.processEvents()
                    w.setValue(old)
                finally:
                    done["v"] = True
        elif isinstance(w, QTabWidget):
            old = w.currentIndex()

            def _act():
                try:
                    if w.count() > 1:
                        w.setCurrentIndex(0 if old else 1)
                        app.processEvents()
                        w.setCurrentIndex(old)
                finally:
                    done["v"] = True
        else:
            return "SKIP", "类型不支持自动触发（仅清点）"

        QTimer.singleShot(0, _act)
        while not done["v"] and time.time() - t0 < 6.0:
            app.processEvents()
            time.sleep(0.01)
        if not done["v"]:
            return "TIMEOUT", "6s 未返回（疑似卡在事件循环）"
        dx, dl, dd = col.delta(m)
        bits = []
        if dd:
            bits.append(f"弹框×{dd}")
        if dx:
            bits.append(f"异常×{dx}")
        if dl:
            bits.append(f"日志ERROR×{dl}")
        return ("ISSUE" if (dx or dl) else "OK"), "，".join(bits)

    steps = [args.step] if args.step else [1, 2, 3, 4, 5]
    tested = 0
    for s in steps:
        for idx in STEP_PAGES.get(s, []):
            stack = win.stacked_widget
            stack.setCurrentIndex(idx)
            pump(12)
            holder = stack.widget(idx)
            page = holder.widget() if isinstance(holder, QScrollArea) else holder
            pname = f"p{idx} {type(page).__name__}"

            refs = collect(page)
            total = len(refs)
            for i0 in range(total):
                # ★ 每次点击前重新枚举：上一跳可能重建了整块 UI
                ctrls = collect(page)
                if i0 >= len(ctrls):
                    break
                w = ctrls[i0]
                if not alive(w):
                    continue
                label = ctrl_text(w)[:40]
                key = ckey(w)
                if (s, pname, key) in seen:
                    continue
                kind = classify(label + " " + (w.objectName() or "")
                                + " " + (w.toolTip() or ""))
                enabled = w.isEnabled()
                nr, hit = probe_signals(w)

                if not enabled:
                    res, note = "DISABLED", "控件当前不可用"
                elif args.inventory:
                    res, note = "INV", "仅清点"
                elif kind == "destructive":
                    res, note = "SKIP", "破坏性：交人工确认"
                elif kind == "heavy":
                    res, note = "SKIP", "重任务：不自动触发"
                else:
                    res, note = invoke(w)
                    tested += 1

                jrec({"step": s, "page": pname, "idx": i0, "key": key,
                      "label": label, "type": type(w).__name__,
                      "enabled": enabled, "recv": nr,
                      "signals": list(hit), "kind": kind,
                      "res": res, "note": note})
                seen.add((s, pname, key))
                print(f"   [{s}/{pname}] {label[:26]:<28} {kind:<11} {res:<8} {note[:34]}")

    jfh.close()

    # 还原初始项目（排查不应改变工作上下文）
    restored = "n/a"
    try:
        if initial_project:
            pm = win.project_management_widget
            for meth in ("switch_project", "select_project", "on_project_selected",
                         "load_project"):
                fn = getattr(pm, meth, None)
                if callable(fn):
                    try:
                        fn(initial_project)
                        break
                    except Exception:
                        continue
            pump(10)
            cur = getattr(pm.current_project, "project_id", None)
            restored = "是" if cur == initial_project else f"否（当前={cur}）"
    except Exception as e:  # noqa: BLE001
        restored = f"失败:{e}"

    after = snapshot(win)
    col.stop()

    extra = ["", "=" * 96, "汇总", "=" * 96]
    from collections import Counter
    cnt = Counter(r["res"] for r in rows)
    kind_cnt = Counter(r["kind"] for r in rows if r["res"] not in ("DISABLED", "INV"))
    extra.append(f"   本次执行点击: {tested}    日志累计记录: {len(rows)}")
    extra.append(f"   结果分布: {dict(cnt)}")
    extra.append(f"   已点击控件的类别: {dict(kind_cnt)}")
    extra.append("")
    extra.append(f"   初始项目还原: {restored}（{initial_project}）")
    extra.append("")
    extra.append("   数据规模快照（证明未改动数据）")
    for k in sorted(set(before) | set(after)):
        b, a = before.get(k, "-"), after.get(k, "-")
        extra.append(f"      {k:22} 前={b:<16} 后={a:<16}"
                     f"{'  ← 变化!' if b != a else ''}")
    extra.append("")
    extra.append(f"   捕获 slot 异常: {len(col.exceptions)}")
    for e in col.exceptions[:6]:
        extra.append("      " + e.replace("\n", " | ")[:190])
    extra.append(f"   捕获 logger ERROR: {len(col.log_errors)}")
    for e in col.log_errors[:10]:
        extra.append("      " + e[:190])
    extra.append(f"   自动关闭的对话框: {len(col.dialogs)}")
    for e in col.dialogs[:10]:
        extra.append("      " + e[:190])
    extra.append("")
    bad = [r for r in rows if r["res"] in ("ISSUE", "TIMEOUT")]
    extra.append(f"   异常控件: {len(bad)}")
    for r in bad[:20]:
        extra.append(f"      !! {r['page']} | {r['label'][:34]} | {r['res']} | {r['note'][:60]}")
    nc = [r for r in rows if r["res"] == "OK" and r["recv"] == 0
          and r["type"] in ("QPushButton", "QToolButton", "QAbstractButton")]
    extra.append(f"   已点击但无信号连接的动作按钮（疑似空按钮）: {len(nc)}")
    for r in nc[:20]:
        extra.append(f"      ?? {r['page']} | {r['label'][:34]} | recv={r['recv']}")
    # 输入类控件"无信号"是**正常的**：它们的状态在使用时才被读取，不靠信号驱动
    ni = [r for r in rows if r["recv"] == 0 and r["type"] not in
          ("QPushButton", "QToolButton", "QAbstractButton")]
    extra.append(f"   输入类控件无信号（正常：状态在使用时读取）: {len(ni)}")
    extra.append("")
    extra.append("RESULT: " + ("PASS" if not bad and not col.exceptions
                               and not col.log_errors else "ISSUES"))

    text = build_report(rows, extra)
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print("\n" + "\n".join(extra))
    print("\n报告 ->", os.path.abspath(REPORT))
    win.close()
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
