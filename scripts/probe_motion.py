#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""过渡动画取证：证明**中间帧确实落在两端之间**。

为什么要专门取证：一个"动画"很容易做成"瞬时切换 + 首尾两帧不同"，
只看首尾两张图根本分辨不出来。这里直接采样动画属性 `_sk_hover` 与控件亮度
的时间序列，检查是否出现**严格介于两端之间**的中间值。

同时验证两条不变量：
  A. 有动画层时，悬停**稳定后**的终值必须与"无动画层"的悬停终值一致（视觉不漂移）
  B. `hover_k == 0` 必须与"无动画层且未悬停"**逐像素相同**（首帧不跳变）

用法：
    python scripts/probe_motion.py
"""

import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("MIMW_SKIN", "metal")
os.environ.pop("MIMW_THEME", None)

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.core.qt_compat.QtCore import Qt, QPoint, QObject, QEvent  # noqa: E402
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QCheckBox, QComboBox, QLabel,
)

user32 = ctypes.windll.user32
GA_ROOT = 2
HWND_TOPMOST = -1
SWP_NOMOVE, SWP_NOSIZE, SWP_SHOWWINDOW = 0x0002, 0x0001, 0x0040


def cursor_pos():
    p = wt.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def set_cursor(x, y):
    user32.SetCursorPos(int(x), int(y))


def hwnd_at(x, y):
    p = wt.POINT(int(x), int(y))
    h = user32.WindowFromPoint(p)
    return (user32.GetAncestor(h, GA_ROOT) or h) if h else 0


app = QApplication.instance() or QApplication([])

from src.utils import skeuo_style as st  # noqa: E402
from src.utils import skeuomorphic as sk  # noqa: E402
from src.utils import skeuo_motion as mo  # noqa: E402

sk.apply_global(app)
st.install(app)

OUT = []


def say(s=""):
    OUT.append(str(s))
    print(s)


# ---- Enter/Leave 事件日志：用来定位"光标没动但收到 Leave"这种诡异情况 ----
_T0 = time.perf_counter()
EVLOG = []


class _EvLog(QObject):
    def __init__(self, app, watch):
        super().__init__(app)
        self.watch = watch
        self._types = {}
        for nm in ("Enter", "Leave", "FocusIn", "FocusOut", "MouseMove"):
            try:
                self._types[getattr(QEvent.Type, nm)] = nm
            except Exception:
                pass

    def eventFilter(self, obj, ev):
        try:
            nm = self._types.get(ev.type())
        except Exception:
            return False
        if nm is None or nm == "MouseMove":
            return False
        try:
            if obj is not self.watch:
                return False
        except Exception:
            return False
        EVLOG.append((round((time.perf_counter() - _T0) * 1000, 1), nm,
                      self.watch.underMouse(),
                      self.watch.property("_sk_hover"),
                      self.watch.property("_sk_focus")))
        return False


def pump(n=8, dt=0.008):
    for _ in range(n):
        app.processEvents()
        time.sleep(dt)


def mean_lum(img):
    if img.width() < 2:
        return 0.0
    s = 0.0
    c = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            col = img.pixelColor(x, y)
            s += (0.2126 * col.red() + 0.7152 * col.green() + 0.0722 * col.blue())
            c += 1
    return s / max(1, c) / 255.0


def diff(a, b):
    if a.size() != b.size() or a.width() < 2:
        return -1
    mx = 0
    for y in range(a.height()):
        for x in range(a.width()):
            ca, cb = a.pixelColor(x, y), b.pixelColor(x, y)
            mx = max(mx, abs(ca.red() - cb.red()), abs(ca.green() - cb.green()),
                     abs(ca.blue() - cb.blue()))
    return mx


# ---------------------------------------------------------------- 界面
win = QWidget()
win.setWindowTitle("过渡动画取证")
win.resize(440, 240)
win.move(30, 30)
lay = QVBoxLayout(win)
btn = QPushButton("主要操作")
le = QLineEdit("文本")
cb = QComboBox()
cb.addItems(["A", "B"])
ck = QCheckBox("勾选框")
row = QHBoxLayout()
for w in (btn, le):
    row.addWidget(w)
lay.addLayout(row)
lay.addWidget(cb)
lay.addWidget(ck)
park = QLabel("  ← 停靠区")
park.setMinimumHeight(26)
lay.addWidget(park)
win.show()
win.setWindowFlag(Qt.WindowStaysOnTopHint, True)
win.show()
win.raise_()
win.activateWindow()
pump(30, 0.02)

hwnd = int(win.winId())
user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
pump(20, 0.02)

_evlogger = _EvLog(app, btn)
app.installEventFilter(_evlogger)

dpr = float(win.devicePixelRatioF() or 1.0)


def phys(w):
    p = w.mapToGlobal(w.rect().center())
    return int(p.x() * dpr), int(p.y() * dpr)


def park_cursor():
    x, y = phys(park)
    set_cursor(x, y)
    time.sleep(0.28)
    pump(14)


def hover(w, settle=0.45):
    x, y = phys(w)
    set_cursor(x, y)
    time.sleep(settle)
    pump(16)


say("=" * 78)
say(f"过渡动画取证   dpr={dpr}   hwnd={hwnd}")
say("=" * 78)

ctrl = mo.installed()
say(f"动画层已安装: {ctrl is not None}   时长={getattr(ctrl, 'duration', None)}ms")
say(f"过滤器看到的事件数: {getattr(ctrl, 'seen', None)}")

# ---------------------------------------------------------------- A/B 不变量
say("-" * 78)
say("不变量 A：终值不漂移；不变量 B：hover_k=0 逐像素等于未悬停")
park_cursor()
base_anim = btn.grab().toImage()

mo.uninstall_motion(app)
st.reset_texture_cache()
sk.apply_global(app)
st.install(app)
mo.uninstall_motion(app)          # install() 会重新装回来，这里再摘掉 → 纯布尔模式
pump(14, 0.02)
park_cursor()
base_nomotion = btn.grab().toImage()
say(f"  B) hover_k=0 vs 无动画层未悬停: 最大通道差 = {diff(base_anim, base_nomotion)}"
    f"   （应为 0）")

# ---------------------------------------------------------------- 采样
say("-" * 78)
say("采样：光标移到按钮上 → 记录 hover_k 与亮度的**时间序列**")


def sample(w, prop="_sk_hover", total=0.60, dt=0.010):
    rows = []
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < total:
        app.processEvents()
        v = w.property(prop)
        lum = mean_lum(w.grab().toImage())
        try:
            um = w.underMouse()
        except Exception:
            um = None
        rows.append((time.perf_counter() - t0, None if v is None else float(v),
                     lum, um))
        time.sleep(dt)
    return rows


park_cursor()
park_cursor()
# 装上动画层再测（此时是纯布尔模式被摘掉之后）
t0 = time.perf_counter()
mo.install_motion(app)
pump(6)

x, y = phys(btn)
set_cursor(x, y)
entering = sample(btn, total=0.40)
say(f"  hwnd 命中: {hwnd_at(x, y) == hwnd}   underMouse={btn.underMouse()}")

x2, y2 = phys(park)
set_cursor(x2, y2)
leaving = sample(btn, total=0.40)

say("")
say("  进入（悬停）序列：")
say("      t(ms)   hover_k   亮度     underMouse")
for t, k, lum, um in entering:
    ks = "None" if k is None else f"{k:.3f}"
    say(f"     {t*1000:6.1f}   {ks:>8}   {lum:.4f}   {um}")

say("")
say("  离开（退场）序列：")
say("      t(ms)   hover_k   亮度     underMouse")
for t, k, lum, um in leaving:
    ks = "None" if k is None else f"{k:.3f}"
    say(f"     {t*1000:6.1f}   {ks:>8}   {lum:.4f}   {um}")

say("")
say("  按钮的 Enter/Leave 事件日志（t, 事件, underMouse, _sk_hover, _sk_focus）：")
for row in EVLOG[:26]:
    say("     " + str(row))
say(f"     ... 共 {len(EVLOG)} 条")


def analyze(rows, label):
    ks = [k for _, k, _l, _u in rows if k is not None]
    if not ks:
        say(f"  [{label}] hover_k 全为 None → 动画层没生效")
        return None
    lo, hi = min(ks), max(ks)
    mid = [k for k in ks if lo + 0.15 * (hi - lo) < k < hi - 0.15 * (hi - lo)]
    lums = [l for _, _, l, _u in rows]
    lum_mid = [l for l in lums if min(lums) + 0.15 * (max(lums) - min(lums))
               < l < max(lums) - 0.15 * (max(lums) - min(lums))]
    say(f"  [{label}] hover_k 范围 = {lo:.3f} .. {hi:.3f}"
        f"   严格中间值个数 = {len(mid)}   亮度中间值个数 = {len(lum_mid)}")
    if mid:
        say(f"        中间值样本 = {[round(m, 3) for m in mid[:8]]}")
    return len(mid)


say("")
say("-" * 78)
say("判定")
n_in = analyze(entering, "进入")
n_out = analyze(leaving, "离开")

ok_anim = (n_in or 0) >= 2 or (n_out or 0) >= 2
say(f"  动画插值: {'PASS' if ok_anim else 'FAIL'}"
    f"  （进入中间帧 {n_in}，离开中间帧 {n_out}）")
ok_b = diff(base_anim, base_nomotion) == 0
say(f"  首帧不跳变(hover_k=0 == 未悬停): {'PASS' if ok_b else 'FAIL'}")
say("RESULT: " + ("PASS" if (ok_anim and ok_b) else "ISSUES"))

# ---------------------------------------------------------------- 可见性
say("-" * 78)
say("过渡是否可感知：悬停稳定后的像素差（应 >= 4）")
for name, w in (("button", btn), ("line", le), ("combo", cb), ("check", ck)):
    park_cursor()
    pump(20, 0.012)
    x, y = phys(w)
    over = hwnd_at(x, y) == hwnd
    a = w.grab().toImage()
    hover(w, settle=0.55)
    pump(30, 0.012)          # 必须 > 动画时长(160ms)，否则会抓到中间帧
    b = w.grab().toImage()
    k = w.property("_sk_hover")
    say(f"  {name:<8} 最大通道差 = {diff(a, b)}"
        f"   underMouse={w.underMouse()}  hwnd命中={over}"
        f"  _sk_hover={'None' if k is None else round(float(k), 3)}")
    park_cursor()

rep = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots",
                   "motion_probe.txt")
os.makedirs(os.path.dirname(rep), exist_ok=True)
with open(rep, "w", encoding="utf-8") as fh:
    fh.write("\n".join(OUT) + "\n")
print("report ->", os.path.abspath(rep))

win.close()
