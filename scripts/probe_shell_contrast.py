#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""壳层控件对比度取证：标题栏 / 菜单栏 / 状态栏 / 页脚 opencode 面板。

沿用已收敛的设计（与 check_occlusion 的 R9 一致）：
  * **前景用声明色** —— 文字色是确定值（Qt 就按它渲染），小号 CJK 没有纯色核心，
    靠像素猜前景必然失手（面板那次就踩过）。
  * **背景用实测** —— 从"整窗口合成抓图"里裁剪，才是真实渲染结果。
  * 声明色解析顺序：控件自身样式表 → 各级父控件样式表 → **应用级 QSS** → palette。
    应用级 QSS 必须查：`QStatusBar QLabel { color: … }` 这类规则就写在全局皮肤里，
    不查它会误落到 palette，得出错误结论。
  * 禁用态优先取 `:disabled` 规则（否则会拿启用态颜色算出虚高的对比度）。

用法：
    python scripts/probe_shell_contrast.py --theme dark
    python scripts/probe_shell_contrast.py --theme light
"""

import os
import re
import sys
import time
from typing import Dict, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("MIMW_SKIN", "metal")

THEME = ""
for i, a in enumerate(sys.argv):
    if a == "--theme" and i + 1 < len(sys.argv):
        THEME = sys.argv[i + 1]
if THEME:
    os.environ["MIMW_THEME"] = THEME
else:
    os.environ.pop("MIMW_THEME", None)

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.core.qt_compat.QtCore import QPoint  # noqa: E402
from src.core.qt_compat.QtGui import QColor  # noqa: E402
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QLabel, QPushButton, QMenuBar,
)


def wcag_lum(c: QColor) -> float:
    def f(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c.red()) + 0.7152 * f(c.green()) + 0.0722 * f(c.blue())


def ratio(c1: QColor, c2: QColor) -> float:
    a, b = wcag_lum(c1), wcag_lum(c2)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def hexc(c: QColor) -> str:
    return f"#{c.red():02X}{c.green():02X}{c.blue():02X}"


def _grab_rule(qss: str, sel: str) -> str:
    if not qss:
        return ""
    try:
        m = re.search(
            rf"{re.escape(sel)}\s*\{{[^}}]*?(?<![-a-z])color\s*:\s*(#[0-9A-Fa-f]{{6}})",
            qss, re.S)
        return m.group(1) if m else ""
    except Exception:
        return ""


def declared_color(w: QWidget) -> Dict[str, str]:
    """解析控件实际会用的文字色（QSS 链 → 应用级 QSS → palette）。"""
    out = {"value": "", "from": ""}
    try:
        disabled = not w.isEnabled()
    except Exception:
        disabled = False
    on = ""
    try:
        on = w.objectName() or ""
    except Exception:
        on = ""

    sels = []
    if on:
        if disabled:
            sels.append(f"#{on}:disabled")
        sels.append(f"#{on}")
    if isinstance(w, QPushButton):
        if disabled:
            sels.append("QPushButton:disabled")
        sels.append("QPushButton")
    if isinstance(w, QMenuBar):
        sels.insert(0, "QMenuBar::item")
        sels.append("QMenuBar")
    if isinstance(w, QLabel):
        # 状态栏里的标签由全局皮肤的 `QStatusBar QLabel` 规则着色
        sels.append("QStatusBar QLabel")
        sels.append("QLabel")

    # 1) 控件自身 → 各级父控件
    a, hops = w, 0
    while a is not None and hops < 8:
        hops += 1
        try:
            ss = a.styleSheet() or ""
        except Exception:
            ss = ""
        for s in sels:
            v = _grab_rule(ss, s)
            if v:
                return {"value": v, "from": f"widget:{type(a).__name__}/{s}"}
        try:
            a = a.parentWidget()
        except Exception:
            break

    # 2) 应用级 QSS（全局皮肤）
    try:
        app_qss = QApplication.instance().styleSheet() or ""
    except Exception:
        app_qss = ""
    for s in sels:
        v = _grab_rule(app_qss, s)
        if v:
            return {"value": v, "from": f"appQSS/{s}"}

    # 3) palette（最后的兜底，也是"没有 QSS 时 Qt 真正用的颜色"）
    try:
        role = w.palette().ColorRole.WindowText
        return {"value": hexc(w.palette().color(role)), "from": "palette"}
    except Exception:
        return {"value": "", "from": "-"}


def measure(img, w: QWidget, root: QWidget, dpr: float):
    """返回 (bg, 命中簇数) —— 背景取分箱后的最高频**精确色**。"""
    pos = w.mapTo(root, QPoint(0, 0))
    x0, y0 = int(pos.x() * dpr), int(pos.y() * dpr)
    cw, ch = int(w.width() * dpr), int(w.height() * dpr)
    if cw < 6 or ch < 6:
        return None, 0
    crop = img.copy(max(0, x0), max(0, y0), cw, ch)
    if crop.width() < 6 or crop.height() < 6:
        return None, 0
    BIN = 32
    bins: Dict[tuple, dict] = {}
    for yy in range(2, crop.height() - 2):
        for xx in range(2, crop.width() - 2):
            c = crop.pixelColor(xx, yy)
            k = (c.red() // BIN, c.green() // BIN, c.blue() // BIN)
            e = bins.setdefault(k, {"n": 0, "colors": {}})
            e["n"] += 1
            rgb = (c.red(), c.green(), c.blue())
            e["colors"][rgb] = e["colors"].get(rgb, 0) + 1
    if not bins:
        return None, 0
    best = max(bins.values(), key=lambda e: e["n"])
    rgb, _ = max(best["colors"].items(), key=lambda kv: kv[1])
    return QColor(*rgb), len(bins)


app = QApplication.instance() or QApplication([])

from src.utils import skeuomorphic as sk  # noqa: E402
from src.utils import skeuo_style as st  # noqa: E402

try:
    from src.utils.theme_manager import ThemeManager
    ThemeManager._current_theme = (THEME or "dark")
except Exception:
    pass
sk.apply_global(app)
st.install(app)

from ui.widgets.main_window import MainWindow  # noqa: E402

win = MainWindow(remaining_seconds=0, license_exp_ts=0)
try:
    from src.kernel.tools.ui_bridge import UIBridge
    from src.kernel.kernel_boot import KernelBoot
    win.attach_opencode(UIBridge(), KernelBoot())
except Exception as e:  # noqa: BLE001
    print(f"   attach_opencode 失败: {e}")
win.resize(1680, 1000)
win.show()


def pump(n=16, dt=0.03):
    for _ in range(n):
        app.processEvents()
        time.sleep(dt)


pump(28)

TAG = THEME or "dark"
print("=" * 96)
print(f"壳层控件对比度取证    主题={TAG}")
print("=" * 96)

targets = []
tb = getattr(win, "_title_frame", None)
if tb is not None:
    targets.append(("标题栏容器", tb))
for nm in ("mimwTitleText", "mimwProjectText"):
    try:
        lb = win.findChild(QLabel, nm)
    except Exception:
        lb = None
    if lb is not None:
        targets.append((f"标题({nm})", lb))
targets.append(("菜单栏", win.menuBar()))
targets.append(("状态栏", win.statusBar()))
for attr in ("gpu_owner_label", "license_label"):
    lb = getattr(win, attr, None)
    if lb is not None:
        targets.append((f"状态栏({attr})", lb))
panel = getattr(win, "opencode_panel", None)
if panel is not None:
    targets.append(("opencode面板", panel))

dpr = float(win.devicePixelRatioF() or 1.0)
img = win.grab().toImage()

print(f"{'控件':<22} {'实测底色':<9} {'声明色':<9} {'来源':<28} {'对比度':>7}  判定")
print("-" * 96)
rows, worst = [], []
for name, w in targets:
    try:
        if not w.isVisible() or w.width() < 8 or w.height() < 8:
            print(f"{name:<22} （不可见/过小，跳过）")
            continue
    except Exception:
        continue
    cbg, nclu = measure(img, w, win, dpr)
    decl = declared_color(w)
    if cbg is None or not decl["value"]:
        print(f"{name:<22} 测量失败（bg={cbg} declared={decl}）")
        continue
    cfg = QColor(decl["value"])
    rr = ratio(cfg, cbg)
    flag = "OK" if rr >= 4.5 else ("偏低" if rr >= 3.0 else "★ 差")
    print(f"{name:<22} {hexc(cbg):<9} {decl['value']:<9} {decl['from'][:27]:<28} "
          f"{rr:>6.2f}:1  {flag}")
    rows.append((name, hexc(cbg), decl["value"], decl["from"], rr))
    if rr < 4.5:
        worst.append((name, rr))

print("")
print("── 结论 ──")
if worst:
    print(f"   ★ {len(worst)} 个壳层控件 < 4.5:1：")
    for n, rr in worst:
        print(f"      {n}  {rr:.2f}:1")
else:
    print("   全部 >= 4.5:1")

shots = os.path.join("docs", "screenshots")
os.makedirs(shots, exist_ok=True)
with open(os.path.join(shots, f"shell_contrast_{TAG}.txt"), "w", encoding="utf-8") as fh:
    fh.write(f"主题={TAG}\n")
    for n, bg_, fg_, src, rr in rows:
        fh.write(f"{n}\tbg={bg_}\tfg={fg_}\t来源={src}\tratio={rr:.2f}\n")
win.grab().save(os.path.join(shots, f"shell_{TAG}.png"))
print(f"   已存图: shell_{TAG}.png")
win.close()
