#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""点击可达性排查：真实鼠标点击能不能**到达**控件？

════════════════════════════════════════════════════════════════════════
为什么需要这个（我的排查盲区）
════════════════════════════════════════════════════════════════════════

`scripts/audit_controls_step1_5.py` 用的是 `btn.click()` —— 它**直接发信号，
完全绕过鼠标事件**。因此它只证明了"槽函数能跑"，**没有验证真实鼠标点击能否到达控件**。
一个控件完全可能"能点但点不到"：被透明/不透明控件盖住、被裁到视口外、
父容器吃掉了事件 —— 这些在 `click()` 路径上全部看不出来。

本脚本用两个独立手段查：

1. **命中链**（不需要真鼠标，可覆盖全部控件）
   `page.childAt(控件中心)` → 沿父链往上找。若控件不在链上，说明该点上的点击
   会落到**别的控件**手里 → 真实点击必然"没响应"。
2. **真实鼠标点击**（端到端，抽代表性控件）
   `SetCursorPos` + `mouse_event(LEFTDOWN/UP)`，再用 `WindowFromPoint` 校验
   光标确实落在本窗口，最后检查是否产生了可观测效果（弹窗/日志）。

用法：
    python scripts/test_click_reachability.py            # 全部步骤
    python scripts/test_click_reachability.py --step 3
    python scripts/test_click_reachability.py --real     # 追加真实鼠标点击
"""

import argparse
import ctypes
import ctypes.wintypes as wt
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

from src.core.qt_compat.QtCore import Qt, QPoint, QTimer  # noqa: E402
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QScrollArea, QAbstractButton, QComboBox, QLineEdit,
    QAbstractSlider, QAbstractSpinBox, QTabWidget, QGroupBox, QLabel, QMenuBar,
)

user32 = ctypes.windll.user32
GA_ROOT = 2
HWND_TOPMOST = -1
SWP_NOMOVE, SWP_NOSIZE, SWP_SHOWWINDOW = 0x0002, 0x0001, 0x0040
LEFTDOWN, LEFTUP = 0x0002, 0x0004

STEP_PAGES = {1: [0, 1, 2, 3, 4], 2: [5], 3: [6], 4: [7], 5: [8]}
STEP_TITLE = {1: "第一步 数据整理", 2: "第二步 数据清洗及结构化",
              3: "第三步 数据科学总结", 4: "第四步 科学文本预览",
              5: "第五步 反馈迭代优化"}

INTERACTIVE = (QAbstractButton, QComboBox, QLineEdit, QAbstractSlider,
               QAbstractSpinBox, QTabWidget)


def hwnd_at(x, y):
    p = wt.POINT(int(x), int(y))
    h = user32.WindowFromPoint(p)
    return (user32.GetAncestor(h, GA_ROOT) or h) if h else 0


def text_of(w):
    try:
        if isinstance(w, QLabel):
            import re as _re
            return _re.sub(r"<[^>]+>", "", str(w.text() or ""))[:34]
        if isinstance(w, QAbstractButton):
            return str(w.text() or "").replace("&", "").strip()[:34]
        if isinstance(w, QComboBox):
            return f"[combo] {w.currentText()}"[:34]
        if isinstance(w, QLineEdit):
            return f"[input] {w.placeholderText()[:20]}"
        return type(w).__name__
    except Exception:
        return type(w).__name__


def alive(w):
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
        return True
    except Exception:
        return False


def hit_owner(page, pos):
    """page 坐标系下 pos 处的点击会落到哪个控件（沿父链返回整条链）。"""
    chain = []
    try:
        w = page.childAt(pos)
    except Exception:
        return chain
    guard = 0
    while w is not None and guard < 40:
        guard += 1
        chain.append(w)
        if w is page:
            break
        try:
            w = w.parentWidget()
        except Exception:
            break
    return chain


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=int, default=0)
    ap.add_argument("--real", action="store_true", help="追加真实鼠标点击验证")
    args = ap.parse_args()

    app = QApplication.instance() or QApplication([])
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
    win.raise_()

    def pump(n=12, dt=0.03):
        for _ in range(n):
            app.processEvents()
            time.sleep(dt)

    pump(26)

    stack = win.stacked_widget
    fails = []
    lines = []
    total = 0
    okc = 0

    steps = [args.step] if args.step else [1, 2, 3, 4, 5]
    for s in steps:
        lines.append("")
        lines.append("=" * 94)
        lines.append(f"{STEP_TITLE[s]}   （页面 {STEP_PAGES.get(s)}）")
        lines.append("=" * 94)
        for idx in STEP_PAGES.get(s, []):
            stack.setCurrentIndex(idx)
            pump(14)
            holder = stack.widget(idx)
            page = holder.widget() if isinstance(holder, QScrollArea) else holder
            pname = f"p{idx} {type(page).__name__}"
            lines.append("")
            lines.append(f"── {pname} ──")
            lines.append(f"   {'控件':<30} {'中心点':<14} {'命中者':<26} 结论")
            lines.append("   " + "-" * 88)

            for w in page.findChildren(QWidget):
                if not alive(w):
                    continue
                try:
                    if not (isinstance(w, INTERACTIVE) and w.isVisible()
                            and not w.isWindow()):
                        continue
                except Exception:
                    continue
                total += 1
                g = w.geometry()
                c = QPoint(max(0, g.width() // 2), max(0, g.height() // 2))
                try:
                    pos = w.mapTo(page, c)
                except Exception:
                    continue
                chain = hit_owner(page, pos)
                if not chain:
                    hit = "<无>"
                else:
                    hit = type(chain[0]).__name__

                reachable = any(x is w for x in chain)
                # 命中的是本控件的子控件（如按钮里的 QLabel）也算可达：
                # QLabel 不处理鼠标事件，会向上冒泡给父控件。
                if not reachable:
                    for x in chain:
                        p = x
                        g2 = 0
                        while p is not None and g2 < 12:
                            g2 += 1
                            if p is w:
                                reachable = True
                                break
                            try:
                                p = p.parentWidget()
                            except Exception:
                                break
                        if reachable:
                            break

                if reachable:
                    okc += 1
                    verdict = "可达"
                else:
                    verdict = "★ 被挡（点击不会到达）"
                    fails.append(f"{pname} | {text_of(w)[:28]} | 命中={hit} "
                                 f"| 位置=({pos.x()},{pos.y()})")
                if not reachable:
                    lines.append(f"   {text_of(w)[:28]:<30} "
                                 f"({pos.x():>4},{pos.y():>4}) {hit:<26} {verdict}")

    lines.append("")
    lines.append("=" * 94)
    lines.append("汇总")
    lines.append("=" * 94)
    lines.append(f"   交互控件总数 : {total}")
    lines.append(f"   点击可达     : {okc}")
    lines.append(f"   被遮挡不可达 : {len(fails)}")
    for f in fails:
        lines.append("      !! " + f)
    lines.append("")
    lines.append("RESULT: " + ("PASS" if not fails else "ISSUES"))

    text = "\n".join(lines)
    print(text)
    out = os.path.join("docs", "screenshots", "click_reachability.txt")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print("\n报告 ->", os.path.abspath(out))

    # ---------------- 真实鼠标点击（端到端） ----------------
    if args.real:
        print("")
        print("=" * 94)
        print("真实鼠标点击验证（SetCursorPos + mouse_event）")
        print("=" * 94)
        win.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        win.show()
        win.raise_()
        win.activateWindow()
        pump(20)
        hwnd = int(win.winId())
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        pump(14)
        dpr = float(win.devicePixelRatioF() or 1.0)

        opened = []
        closer = QTimer()
        closer.setInterval(120)

        def _close():
            try:
                d = app.activeModalWidget()
                if d is not None:
                    opened.append(type(d).__name__)
                    d.reject()
            except Exception:
                pass
        closer.timeout.connect(_close)
        closer.start()

        # 抽代表性控件：每一步挑一个动作按钮
        targets = []
        for s, idx in ((3, 6), (4, 7), (1, 0), (1, 2), (1, 3)):
            stack.setCurrentIndex(idx)
            pump(12)
            holder = stack.widget(idx)
            page = holder.widget() if isinstance(holder, QScrollArea) else holder
            for w in page.findChildren(QAbstractButton):
                if not alive(w) or not w.isEnabled():
                    continue
                t = text_of(w)
                if not t:
                    continue
                if any(k in t for k in ("删除", "清空", "清除", "重置", "覆盖",
                                        "开始", "同步", "重建")):
                    continue
                if isinstance(w, QAbstractButton) and w.isCheckable():
                    continue
                targets.append((f"p{idx}", t, w))
                break

        for pname, t, w in targets:
            before = len(opened)
            try:
                pos = w.mapToGlobal(w.rect().center())
                sx, sy = int(pos.x() * dpr), int(pos.y() * dpr)
                user32.SetCursorPos(sx, sy)
                time.sleep(0.25)
                pump(8)
                over = (hwnd_at(sx, sy) == hwnd)
                user32.mouse_event(LEFTDOWN, 0, 0, 0, 0)
                time.sleep(0.12)
                user32.mouse_event(LEFTUP, 0, 0, 0, 0)
                time.sleep(0.9)
                pump(30)
                got = opened[before:]
                verdict = ("PASS 弹出 " + ",".join(got)) if got else \
                          ("PASS" if over else "FAIL 光标不在本窗口")
                print(f"   {pname:<6} {t[:26]:<28} {verdict}")
            except Exception as e:  # noqa: BLE001
                print(f"   {pname:<6} {t[:26]:<28} FAIL {type(e).__name__}: {e}")
        closer.stop()

    win.close()
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
