#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""关键探针：真实启动流程跑完后，`current_project_id` 到底有没有被设置？

背景：`show_dicom_roi()` 等都是

    if self.current_project_id is None:
        QMessageBox.warning(self, '警告', '请先选择项目！')
        return                     # ← 不切页

所以只要 `current_project_id` 是 None，**所有步骤菜单都只弹警告、不导航**
（用户感受就是"点菜单没响应"）。

我之前的功能排查台直接构造 MainWindow，跳过了 main.py 的启动流程，
所以那次测出来的是 None —— 属测试失真。这里按 main.py 的方式启动并实测。
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("MIMW_SKIN", "metal")

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.core.qt_compat.QtCore import Qt, QTimer  # noqa: E402
from src.core.qt_compat.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication.instance() or QApplication([])
try:
    app.setAttribute(Qt.AA_DontUseNativeDialogs, True)
except Exception:
    pass

from src.utils import skeuomorphic as sk  # noqa: E402
from src.utils import skeuo_style as st  # noqa: E402

sk.apply_global(app)
st.install(app)

OUT = []


def say(s=""):
    OUT.append(str(s))
    print(s)


def pump(sec=1.0, dt=0.03):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents()
        time.sleep(dt)


# 与 main.py:788 相同的构造方式
from ui.widgets.main_window import MainWindow  # noqa: E402

win = MainWindow(remaining_seconds=0, license_exp_ts=0)
win.show()

say("=" * 84)
say("启动后逐秒观察 current_project_id")
say("=" * 84)
for i in range(8):
    pump(1.0)
    cpid = getattr(win, "current_project_id", "<无该属性>")
    pmw = win.project_management_widget
    cur = getattr(getattr(pmw, "current_project", None), "project_id", None)
    say(f"   t={i+1}s   MainWindow.current_project_id = {cpid!r}"
        f"    项目管理组件.current_project = {cur!r}")

say("")
say("=" * 84)
say("结论：菜单导航的前置条件")
say("=" * 84)
cpid = getattr(win, "current_project_id", None)
say(f"   current_project_id = {cpid!r}")
if cpid is None:
    say("   ★ 为 None → show_dicom_roi / show_text_processing / show_ocr_recognition")
    say("     / show_sample_management 等都会弹「请先选择项目！」并 return，**不切页**")
    say("     —— 用户感受就是「点菜单没响应」")
else:
    say("   已设置 → 菜单导航的前置条件满足")

# 真实检查：直接调用 show_* 看是否切页
say("")
say("=" * 84)
say("直接调用各 show_* ，看是否真的切页（用 timer 关掉可能的警告框）")
say("=" * 84)

seen_boxes = []


def close_modal():
    try:
        d = app.activeModalWidget()
        if d is not None:
            txt = ""
            try:
                txt = d.text() if hasattr(d, "text") else ""
            except Exception:
                pass
            seen_boxes.append(f"{type(d).__name__}:{txt[:20]}")
            d.reject()
    except Exception:
        pass


tm = QTimer()
tm.setInterval(100)
tm.timeout.connect(close_modal)
tm.start()

stack = win.stacked_widget
for name in ("show_project_management", "show_dicom_roi", "show_text_processing",
             "show_ocr_recognition", "show_data_cleaning", "show_ai_summary",
             "show_text_preview", "show_feedback_optimization"):
    fn = getattr(win, name, None)
    if fn is None:
        say(f"   {name:<32} 方法不存在")
        continue
    before = stack.currentIndex()
    n0 = len(seen_boxes)
    try:
        fn()
        pump(0.4)
        after = stack.currentIndex()
        extra = f"  弹框={seen_boxes[n0:]}" if len(seen_boxes) > n0 else ""
        say(f"   {name:<32} 页面 {before}→{after}"
            f"  {'✓ 已切页' if before != after else '★ 未切页'}{extra}")
    except Exception as e:  # noqa: BLE001
        say(f"   {name:<32} 异常 {type(e).__name__}: {e}")
tm.stop()

rep = os.path.join("docs", "screenshots", "current_project_probe.txt")
os.makedirs(os.path.dirname(rep), exist_ok=True)
with open(rep, "w", encoding="utf-8") as fh:
    fh.write("\n".join(OUT) + "\n")
print("\n报告 ->", os.path.abspath(rep))
win.close()
