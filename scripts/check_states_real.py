#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真机四态点验 —— **用真实鼠标**。

为什么必须用真鼠标：实测 `setAttribute(WA_UnderMouse, True)` 能让
`widget.underMouse()` 返回 True，但 Qt **不会**把 `State_MouseOver` 放进
`QStyleOption`（打印绘制时刻的 state 位可复现）→ 伪造悬停测不出任何东西。

所以这里用 Windows `SetCursorPos` 移动**真实光标**，让操作系统派发
`WM_MOUSEMOVE`，走 Qt 真正的 enter/leave 机制。按下态用真实的
`mouse_event(LEFTDOWN/LEFTUP)`。

测试结束会**还原光标原位**。

用法：
    python scripts/check_states_real.py --theme dark
    python scripts/check_states_real.py --theme light
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

from src.core.qt_compat.QtCore import Qt, QPoint  # noqa: E402
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QCheckBox, QRadioButton, QSlider,
    QScrollBar, QTabWidget, QTableWidget, QTableWidgetItem, QGroupBox,
    QHeaderView,
)

user32 = ctypes.windll.user32

LEFTDOWN = 0x0002
LEFTUP = 0x0004
GA_ROOT = 2
HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_SHOWWINDOW = 0x0040


def hwnd_at(x, y):
    """光标位置处的最顶层窗口句柄（用于校验光标是否真的落在我们窗口上）。"""
    p = wt.POINT(int(x), int(y))
    h = user32.WindowFromPoint(p)
    if not h:
        return 0
    return user32.GetAncestor(h, GA_ROOT) or h


def window_title(h):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(h, buf, 256)
    return buf.value


def screen_size():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def cursor_pos():
    p = wt.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def set_cursor(x, y):
    user32.SetCursorPos(int(x), int(y))


def left_down():
    user32.mouse_event(LEFTDOWN, 0, 0, 0, 0)


def left_up():
    user32.mouse_event(LEFTUP, 0, 0, 0, 0)


class Probe:
    def __init__(self, app):
        self.app = app
        self.win = QWidget()
        self.win.setWindowTitle("状态点验台 · 真实鼠标")
        self.win.resize(560, 560)
        self.win.move(20, 20)
        root = QVBoxLayout(self.win)
        root.setSpacing(8)

        self.controls = {}

        g1 = QGroupBox("按钮")
        l1 = QHBoxLayout(g1)
        b1 = QPushButton("主要操作")
        b1.setDefault(True)
        b2 = QPushButton("次要操作")
        b3 = QPushButton("禁用按钮")
        b3.setEnabled(False)
        for b in (b1, b2, b3):
            l1.addWidget(b)
        l1.addStretch()
        root.addWidget(g1)
        self.controls["button"] = b1
        self.controls["button2"] = b2

        g2 = QGroupBox("输入 / 下拉")
        l2 = QHBoxLayout(g2)
        le = QLineEdit("文本输入")
        cb = QComboBox()
        cb.addItems(["选项 A", "选项 B"])
        l2.addWidget(le)
        l2.addWidget(cb)
        root.addWidget(g2)
        self.controls["line"] = le
        self.controls["combo"] = cb

        g3 = QGroupBox("勾选 / 单选")
        l3 = QHBoxLayout(g3)
        ck = QCheckBox("勾选框")
        rd = QRadioButton("单选钮")
        ck3 = QCheckBox("禁用勾选")
        ck3.setEnabled(False)
        for w in (ck, rd, ck3):
            l3.addWidget(w)
        l3.addStretch()
        root.addWidget(g3)
        self.controls["check"] = ck
        self.controls["radio"] = rd

        g4 = QGroupBox("滑杆 / 滚动条")
        l4 = QHBoxLayout(g4)
        sl = QSlider(Qt.Horizontal)
        sl.setRange(0, 100)
        sl.setValue(45)
        sc = QScrollBar(Qt.Horizontal)
        sc.setRange(0, 100)
        sc.setValue(40)
        l4.addWidget(sl, 1)
        l4.addWidget(sc, 1)
        root.addWidget(g4)
        self.controls["slider"] = sl
        self.controls["scroll"] = sc

        tabs = QTabWidget()
        tabs.setMaximumHeight(112)
        for nm in ("标签一", "标签二", "标签三"):
            p = QWidget()
            QVBoxLayout(p).addWidget(QLabel(nm + " 内容"))
            tabs.addTab(p, nm)
        root.addWidget(tabs)
        self.controls["tabs"] = tabs

        tbl = QTableWidget(3, 3)
        tbl.setHorizontalHeaderLabels(["列A", "列B", "列C"])
        for r in range(3):
            for c in range(3):
                tbl.setItem(r, c, QTableWidgetItem(f"{r}{c}"))
        tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        tbl.setFixedHeight(104)
        root.addWidget(tbl)
        self.controls["header"] = tbl.horizontalHeader()

        # 停靠位：把光标停在这个空白标签上（"无悬停"基准）
        self.park = QLabel("  ← 光标停靠区")
        self.park.setMinimumHeight(28)
        root.addWidget(self.park)
        root.addStretch()

        self.win.show()
        # 强制置顶 + 激活：否则真实光标落在别的窗口上，本窗口收不到 WM_MOUSEMOVE
        self.win.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.win.show()
        self.win.raise_()
        self.win.activateWindow()
        pump(20)
        self.hwnd = int(self.win.winId())
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        pump(14)
        # 计算物理坐标比例（Qt 逻辑 → Windows 物理）
        self.dpr = float(self.win.devicePixelRatioF() or 1.0)
        self.origin = self.win.mapToGlobal(QPoint(0, 0))
        self.sw, self.sh = screen_size()
        self.wref = cursor_pos()
        self.valid = self._validate()

    def _validate(self):
        """自校验：移动真实光标到停靠区，确认光标确实落在本窗口且 underMouse 生效。"""
        x, y = self.phys(self.park)
        set_cursor(x, y)
        time.sleep(0.30)
        pump(10)
        h = hwnd_at(x, y)
        inside = (0 <= x < self.sw and 0 <= y < self.sh)
        print(f"  [自校验] 目标像素=({x},{y})  屏幕={self.sw}x{self.sh}  "
              f"在屏内={inside}  dpr={self.dpr}")
        print(f"  [自校验] hwnd_at={h}  本窗口 hwnd={self.hwnd}  "
              f"一致={h == self.hwnd}")
        if h != self.hwnd:
            print(f"  [自校验] 光标下的窗口标题 = {window_title(h)!r}")
            print(f"  [自校验] 本窗口标题       = {window_title(self.hwnd)!r}")
        print(f"  [自校验] 停靠区 underMouse = {self.park.underMouse()}")
        return self.park.underMouse()

    def physical_ok(self, w):
        x, y = self.phys(w)
        return 0 <= x < self.sw and 0 <= y < self.sh

    def phys(self, w):
        """控件中心 → Windows 物理屏幕坐标。"""
        pos = w.mapToGlobal(w.rect().center())
        return (int(pos.x() * self.dpr), int(pos.y() * self.dpr))

    def ensure_active(self, tries=4):
        """确保本窗口是**活动窗口**，并校验。

        为什么必须做：`setFocus()` 的 FocusIn、以及真实左键点击，
        都要求窗口是活动窗口。而 Windows 会阻止"前台窗口被别的进程抢走"
        （`activateWindow()` 底层是 `SetForegroundWindow`，可能被静默忽略）
        → 焦点事件根本不派发，`_sk_focus` 停在 0、测量全变 0（假阴性）。

        关键点：窗口属于**本进程**，所以 `SetActiveWindow` 是允许的
        —— 这也是它比 `activateWindow()` 可靠的原因。
        """
        for _ in range(max(1, tries)):
            try:
                user32.ShowWindow(self.hwnd, 9)          # SW_RESTORE
                user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                    SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
                user32.SetForegroundWindow(self.hwnd)
                user32.SetActiveWindow(self.hwnd)        # 本进程窗口 → 允许
            except Exception:
                pass
            try:
                self.win.raise_()
                self.win.activateWindow()
            except Exception:
                pass
            pump(8)
            try:
                if self.win.isActiveWindow():
                    self.last_active = True
                    return True
            except Exception:
                pass
            time.sleep(0.12)
        self.last_active = False
        return False

    def park_cursor(self, tries=3):
        """把光标停到停靠区，并**校验真的停上去了**。

        实测：光标位置未变化时 Windows 不派发新的 WM_MOUSEMOVE，
        于是 Enter 永远不来、目标控件的 underMouse 一直是 False
        —— 后面所有测量都会变成静默假阴性。所以这里要抖动 + 校验。
        """
        for i in range(max(1, tries)):
            x, y = self.phys(self.park)
            x += (i * 3 - 3)
            set_cursor(x, y)
            time.sleep(0.24)
            pump(8)
            if self.park.underMouse():
                self.last_park_ok = True
                return True
        self.last_park_ok = False
        return False

    def settle(self, w, prop, target, timeout=1.6, tol=0.02):
        """等待过渡动画稳定到目标值。

        为什么必须等：动画时长 160ms，而 grab 是同步渲染 —— 若在动画途中抓图，
        基线与被测帧可能都落在中间态，算出"差 0"的**假阴性**
        （实测踩过：line/hover 报 0，其实只是基线还在归零途中）。
        返回 (是否已稳定, 当前值)。返回 None 值表示没有动画层。
        """
        t0 = time.time()
        v = None
        while time.time() - t0 < timeout:
            pump(4)
            try:
                v = w.property(prop)
            except Exception:
                v = None
            if v is None:
                return True, None
            try:
                fv = float(v)
            except Exception:
                return True, None
            if abs(fv - target) <= tol:
                return True, fv
        try:
            fv = float(v)
        except Exception:
            fv = None
        return False, fv

    def hover(self, w, tries=3):
        """把真实光标移到控件上（低层 WM_MOUSEMOVE）。

        实测会抖动：窗口丢失置顶/激活时光标不落在我窗口上，
        或光标位置未变化时 Windows 不派发新的 WM_MOUSEMOVE。
        → 重试 + 1px 抖动 + 重新置顶。
        """
        ok = False
        over = False
        for i in range(max(1, tries)):
            if i:
                # 重新置顶并抖动 1px，强制产生新的鼠标移动事件
                user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                    SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
                self.win.raise_()
                self.win.activateWindow()
                pump(6)
            x, y = self.phys(w)
            x += (i * 3 - 3)   # 抖动，避免"位置未变 → Windows 不派发事件"
            set_cursor(x, y)
            time.sleep(0.32)
            pump(12)
            over = (hwnd_at(x, y) == self.hwnd)
            ok = w.underMouse()
            if ok and over:
                break
        self.last_over_self = over
        return ok

    def restore_cursor(self):
        set_cursor(*self.wref)

    def grab(self, w):
        return w.grab().toImage()


def pump(n=8):
    for _ in range(n):
        QApplication.instance().processEvents()
        time.sleep(0.035)


def diff(a, b):
    if a.size() != b.size() or a.width() < 2:
        return -1, 0, 0
    mx = n4 = n10 = 0
    for y in range(a.height()):
        for x in range(a.width()):
            ca, cb = a.pixelColor(x, y), b.pixelColor(x, y)
            d = max(abs(ca.red() - cb.red()), abs(ca.green() - cb.green()),
                    abs(ca.blue() - cb.blue()))
            if d > mx:
                mx = d
            if d > 4:
                n4 += 1
            if d > 10:
                n10 += 1
    return mx, n4, n10


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default="dark", choices=["dark", "light"])
    args = ap.parse_args()

    if args.theme == "light":
        os.environ["MIMW_THEME"] = "light"
    else:
        os.environ.pop("MIMW_THEME", None)

    from src.core.qt_compat.QtWidgets import QApplication as QA
    app = QA.instance() or QA([])

    from src.utils import skeuo_style as st
    from src.utils import skeuomorphic as sk
    try:
        from src.utils.theme_manager import ThemeManager
        ThemeManager._current_theme = args.theme
    except Exception:
        pass

    sk.apply_global(app)
    st.install(app)

    pr = Probe(app)
    if not pr.valid:
        print("!! 自校验失败：真实光标悬停机制不可用，测试结果不可信")
        pr.restore_cursor()
        return 2

    outdir = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots")
    os.makedirs(outdir, exist_ok=True)

    ROWS = []

    def record(name, state, a, b, note=""):
        if a is None:
            ROWS.append((name, state, -2, 0, 0, note))
            return
        mx, n4, n10 = diff(a, b)
        tot = a.width() * a.height()
        ROWS.append((name, state, mx, n4, tot, note))

    def _hover_once(name, w, extra, tag):
        """一次悬停测量。返回 (a, b, notes) 或 None（跳过）。"""
        # 基线：光标停靠 + **确认悬停已归零**（否则会算出假阴性"差 0"）
        parked = pr.park_cursor()
        settled, kv = pr.settle(w, "_sk_hover", 0.0)
        pr.win.update()
        pump(6)
        a = pr.grab(w)
        ok = pr.hover(w)
        over = getattr(pr, "last_over_self", None)
        # 被测帧：**确认悬停已到满**（动画 160ms，不等就可能抓到中间帧）
        settled2, kv2 = pr.settle(w, "_sk_hover", 1.0)
        pr.win.update()
        pump(6)
        b = pr.grab(w)
        pr.park_cursor()
        a.save(os.path.join(outdir, f"real_{args.theme}_{name}_normal{tag}.png"))
        b.save(os.path.join(outdir, f"real_{args.theme}_{name}_hover{tag}.png"))
        note = []
        if not parked:
            note.append("停靠失败!")
        if not ok:
            note.append("underMouse=False!")
        if over is False:
            note.append("光标不在本窗口!")
        if not settled:
            note.append(f"基线未归零(k={kv})")
        if not settled2:
            note.append(f"悬停未到满(k={kv2})")
        if extra:
            note.append(extra)
        return a, b, note

    def test_hover(name, w, extra=""):
        """悬停测量；若"状态已确认到满但像素差为 0"，自动重测。

        为什么要重测：真实光标偶发不触发 Enter（窗口抢焦点等），
        或基线恰好在归零途中 —— 单次抖动不该被报成"悬停没实现"。
        """
        if not pr.physical_ok(w):
            record(name, "hover", None, None, "控件中心不在屏内，跳过")
            return
        last = None
        for att in range(3):
            res = _hover_once(name, w, extra, "" if att == 0 else f"_r{att}")
            if res is None:
                return
            a, b, note = res
            if diff(a, b)[0] > 0:
                if att:
                    note.append(f"第{att + 1}次测量才成功（前几次抖动）")
                record(name, "hover", a, b, " ".join(note))
                return
            note.append(f"重测#{att + 1}")
            last = (a, b, note)
        a, b, note = last
        note.append("重测仍为 0")
        record(name, "hover", a, b, " ".join(note))

    # ---------------- 悬停（真实鼠标） ----------------
    test_hover("button", pr.controls["button"])
    test_hover("button2", pr.controls["button2"])
    test_hover("line", pr.controls["line"])
    test_hover("combo", pr.controls["combo"])
    test_hover("check", pr.controls["check"])
    test_hover("radio", pr.controls["radio"])
    test_hover("slider", pr.controls["slider"])
    test_hover("scroll", pr.controls["scroll"])
    test_hover("header", pr.controls["header"])

    # ---------------- 按下（真实左键） ----------------
    for name in ("button", "button2", "scroll"):
        w = pr.controls[name]
        pr.park_cursor()
        pump(6)
        a = pr.grab(w)
        # 置顶 + 激活 + 校验光标确实落在本窗口，避免"点空"甚至误点到别的窗口
        act = pr.ensure_active()
        pump(8)
        x, y = pr.phys(w)
        set_cursor(x, y)
        time.sleep(0.35)
        pump(10)
        if hwnd_at(x, y) != pr.hwnd:
            record(name, "pressed", None, None, "光标不在本窗口，跳过（避免误点）")
            pr.park_cursor()
            continue
        if not act:
            record(name, "pressed", None, None, "窗口未激活，跳过（点击不会生效）")
            pr.park_cursor()
            continue
        left_down()
        time.sleep(0.30)
        pump(10)
        b = pr.grab(w)
        b.save(os.path.join(outdir, f"real_{args.theme}_{name}_pressed.png"))
        left_up()
        time.sleep(0.15)
        pump(8)
        pr.park_cursor()
        record(name, "pressed", a, b)

    # ---------------- 禁用（程序设置） ----------------
    for name in ("button", "line", "combo", "check", "slider", "scroll"):
        w = pr.controls[name]
        pr.park_cursor()
        pump(6)
        a = pr.grab(w)
        w.setEnabled(False)
        pr.win.update()
        pump(10)
        b = pr.grab(w)
        b.save(os.path.join(outdir, f"real_{args.theme}_{name}_disabled.png"))
        record(name, "disabled", a, b)
        w.setEnabled(True)
        pr.win.update()
        pump(8)

    # ---------------- 键盘焦点环 ----------------
    # 焦点环由引擎统一绘制（paint_focus_ring）；这里用程序 setFocus 触发。
    # 注意 pump 要 > 动画时长(160ms)，否则会抓到中间帧。
    for name in ("button", "line", "combo", "check", "radio", "slider", "tabs"):
        w = pr.controls.get(name)
        if w is None:
            continue
        # 标签页的焦点实际落在 TabBar 上
        target = w
        if name == "tabs":
            try:
                target = w.tabBar()
            except Exception:
                target = w
        pr.park_cursor()
        try:
            target.clearFocus()
        except Exception:
            pass
        act = pr.ensure_active()
        pr.settle(w, "_sk_focus", 0.0)
        pump(10)
        a = pr.grab(w)
        try:
            target.setFocus()
        except Exception:
            pass
        s_ok, fv = pr.settle(w, "_sk_focus", 1.0)
        b = pr.grab(w)
        b.save(os.path.join(outdir, f"real_{args.theme}_{name}_focus.png"))
        notes = ["" if s_ok else f"焦点未到满(k={fv})"]
        if not act:
            notes.append("窗口未激活!（焦点事件不会派发）")
        record(name, "focus", a, b, " ".join(x for x in notes if x))
        try:
            target.clearFocus()
        except Exception:
            pass
        pr.settle(w, "_sk_focus", 0.0)

    # ---------------- 选中 ----------------
    for name, setter in (
        ("check", lambda: pr.controls["check"].setChecked(True)),
        ("radio", lambda: pr.controls["radio"].setChecked(True)),
        ("tabs", lambda: pr.controls["tabs"].setCurrentIndex(1)),
        ("combo", lambda: pr.controls["combo"].setCurrentIndex(1)),
    ):
        w = pr.controls[name]
        pr.park_cursor()
        pump(6)
        a = pr.grab(w)
        setter()
        pr.win.update()
        pump(10)
        b = pr.grab(w)
        b.save(os.path.join(outdir, f"real_{args.theme}_{name}_checked.png"))
        record(name, "selected", a, b)

    # ---------------- 报告 ----------------
    lines = []
    lines.append("=" * 84)
    lines.append(f"真机四态点验（真实鼠标）  主题={args.theme}")
    lines.append("=" * 84)
    lines.append(f"{'控件':<10} {'状态':<10} {'最大差':>7} {'>4像素':>9} {'总像素':>9}  判定")
    lines.append("-" * 84)
    bad = []
    for name, state, mx, n4, tot, note in ROWS:
        if mx == -2:
            v = "SKIP"
        elif mx <= 0:
            v = "X 没画"
        elif mx <= 4:
            v = "△ 极轻微"
        elif n4 < 20:
            v = "△ 轻微"
        else:
            v = "OK 可见"
        if v.startswith("X") or v.startswith("△"):
            bad.append((name, state, mx, n4, note))
        lines.append(f"{name:<10} {state:<10} {mx:>7} {n4:>9} {tot:>9}  {v}  {note}")
    lines.append("-" * 84)
    lines.append(f"合计 {len(ROWS)} 项，异常 {len(bad)} 项")
    for name, state, mx, n4, note in bad:
        lines.append(f"   !! {name} / {state}  最大差={mx} >4像素={n4}  {note}")
    lines.append("RESULT: " + ("PASS" if not bad else "ISSUES"))
    report = "\n".join(lines)
    print(report)
    with open(os.path.join(outdir, f"states_real_{args.theme}.txt"),
              "w", encoding="utf-8") as fh:
        fh.write(report + "\n")

    pr.restore_cursor()
    pr.win.grab().save(os.path.join(outdir, f"real_{args.theme}_probe.png"))
    pr.win.close()
    return 0 if not bad else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        pass
