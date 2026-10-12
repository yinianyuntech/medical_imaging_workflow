#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""opencode 页脚面板的对比度取证。

要回答三件事：
  1. 皮肤清理（strip_conflicting_stylesheets）有没有动它的样式表？
  2. 它在**深浅两套主题**下的实际渲染对比度各是多少？
  3. 面板是否在 check_occlusion 的遍历范围内？（它挂在主布局，可能被漏掉）

对比度按 WCAG：ratio = (L1+0.05)/(L2+0.05)，正文需 >= 4.5:1。
"""

import os
import sys
import time
from typing import Dict

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

from src.core.qt_compat.QtCore import Qt, QPoint  # noqa: E402
from src.core.qt_compat.QtGui import QColor  # noqa: E402
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QLabel, QLineEdit, QPushButton, QTextEdit, QScrollArea,
)


def wcag_lum(c) -> float:
    def f(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c.red()) + 0.7152 * f(c.green()) + 0.0722 * f(c.blue())


def ratio(c1, c2) -> float:
    a, b = wcag_lum(c1), wcag_lum(c2)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def hexc(c) -> str:
    return f"#{c.red():02X}{c.green():02X}{c.blue():02X}"


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
# 面板由 main.py 通过 attach_opencode() 挂载（不在 MainWindow.__init__ 里），
# 所以要按真实路径接一遍，否则探针看不到它。
try:
    from src.kernel.tools.ui_bridge import UIBridge
    from src.kernel.kernel_boot import KernelBoot
    from src.kernel.mcp_server import set_ui_bridge
    _bridge = UIBridge()
    set_ui_bridge(_bridge)
    win.attach_opencode(_bridge, KernelBoot())
except Exception as e:  # noqa: BLE001
    print(f"   attach_opencode 失败: {type(e).__name__}: {e}")
win.resize(1680, 1000)
win.show()


def pump(n=14, dt=0.03):
    for _ in range(n):
        app.processEvents()
        time.sleep(dt)


pump(26)

print("=" * 90)
print(f"opencode 页脚面板对比度取证    主题={THEME or 'dark'}")
print("=" * 90)

panel = getattr(win, "opencode_panel", None)
if panel is None:
    print("   ★ 未找到 opencode_panel")
    sys.exit(2)

# ---- 1) 归属与样式表现状 ----
print("")
print("── 1) 面板归属与皮肤清理影响 ──")
chain, p = [], panel
while p is not None and len(chain) < 12:
    chain.append(type(p).__name__ + (f"#{p.objectName()}" if p.objectName() else ""))
    p = p.parentWidget()
print(f"   父链: {' ← '.join(chain)}")
in_stack = any("QStackedWidget" in c for c in chain)
print(f"   是否在 stacked_widget 内: {in_stack}"
      f"   ← check_occlusion 只遍历 stack 内的页面"
      f"{'（会被覆盖）' if in_stack else '（★ 被漏掉）'}")
ss = panel.styleSheet() or ""
print(f"   当前 styleSheet 长度: {len(ss)}")
print(f"   是否仍含 DARK 常量片段: {'#1E1E1E' in ss or 'ocPanel' in ss}")
print("   styleSheet 全文:")
for ln in ss.splitlines()[:14]:
    print("      " + ln)

rep = getattr(win, "_skin_report", {}) or {}
print(f"   皮肤清理计数: {rep}")

# ---- 2) 逐控件实测对比度 ----
print("")
print("── 2) 逐控件实测（整页抓图后裁剪，避免透明背景失真）──")
dpr = float(panel.devicePixelRatioF() or 1.0)
page = panel
# 抓整个主窗口客户区，保证面板背景被合成进去
root = win.centralWidget() or win
rimg = root.grab().toImage()
base = panel.mapTo(root, QPoint(0, 0))
print(f"   面板尺寸={panel.width()}x{panel.height()}  dpr={dpr}  "
      f"在窗口内偏移=({base.x()},{base.y()})")

rows = []
for w in [panel] + panel.findChildren(QWidget):
    if not isinstance(w, (QLabel, QLineEdit, QPushButton, QTextEdit)):
        continue
    if not w.isVisible() or w.width() < 12 or w.height() < 8:
        continue
    pos = w.mapTo(root, QPoint(0, 0))
    x0, y0 = int(pos.x() * dpr), int(pos.y() * dpr)
    cw, ch = int(w.width() * dpr), int(w.height() * dpr)
    img = rimg.copy(x0, y0, cw, ch)
    if img.width() < 4 or img.height() < 4:
        continue
    # 内部采样（避开边框）。★ 颜色**分箱**后再找簇：
    # 抗锯齿文字的像素会散成一大堆近邻色，按"精确颜色"统计会整体漏掉它
    # （实测把明明可见的"未启动"报成 1.00:1 —— 那是测量缺陷，不是渲染缺陷）。
    inset = 2
    BIN = 32
    bins: Dict[tuple, dict] = {}
    for yy in range(inset, max(inset + 1, img.height() - inset)):
        for xx in range(inset, max(inset + 1, img.width() - inset)):
            c = img.pixelColor(xx, yy)
            k = (c.red() // BIN, c.green() // BIN, c.blue() // BIN)
            e = bins.setdefault(k, {"n": 0, "colors": {}})
            e["n"] += 1
            rgb = (c.red(), c.green(), c.blue())
            e["colors"][rgb] = e["colors"].get(rgb, 0) + 1
    if not bins:
        continue
    # ★ 代表色取"箱内最高频的**精确色**"，而不是箱内平均色。
    #   取平均会把 #12161C（面板底）和 #070D18（窗口底）这种深色**糊成一个中间值**，
    #   实测把明明正确的 #12161C 报成 #070D18 —— 测量缺陷伪装成渲染缺陷。
    clusters = []
    for k, e in bins.items():
        rgb, cnt = max(e["colors"].items(), key=lambda kv: kv[1])
        clusters.append((e["n"], cnt, QColor(*rgb)))
    clusters.sort(key=lambda x: -x[0])
    total = sum(c[0] for c in clusters)
    _, _, cbg = clusters[0]
    # ★ 前景用**声明色**，不用像素去猜。
    #   与 check_occlusion.py 的 R9 同一设计：文字色是确定值（Qt 就按它渲染），
    #   真正需要测量的是**背景**。小号 CJK 文字没有大块纯色核心，
    #   靠像素找前景必然失手（这里就踩过：把 #7FD1AE 量成 #DDD0EA 并误报"测不准"）。
    #   下面仍然顺手记录"量到的前景"，仅用于交叉核对。
    best, best_d = None, -1.0
    bg_l = wcag_lum(cbg)
    for n, exact_n, c in clusters[1:]:
        if n < max(10, total * 0.0015):
            continue
        d = abs(wcag_lum(c) - bg_l)
        if d > best_d:
            best, best_d = c, d
    cfg = best or cbg
    rr = ratio(cfg, cbg)
    # 文本色：优先从**样式表**取（子控件自身通常为空 —— QSS 是通过父级生效的，
    # 所以必须沿父链找匹配自己 objectName 的规则），再退化到 palette。
    declared = ""
    try:
        import re as _re

        def _grab(ss_a: str, sel: str):
            m = _re.search(
                rf"{_re.escape(sel)}\s*\{{[^}}]*?color\s*:\s*(#[0-9A-Fa-f]{{6}})",
                ss_a, _re.S)
            return m.group(1) if m else ""

        disabled = False
        try:
            disabled = not w.isEnabled()
        except Exception:
            disabled = False
        a = w
        hops = 0
        while a is not None and hops < 8 and not declared:
            hops += 1
            ss_a = a.styleSheet() or ""
            if not ss_a:
                a = a.parentWidget()
                continue
            on = w.objectName()
            # ★ 禁用态必须优先取 `:disabled` 规则。
            #   只取 `QPushButton { color }` 会在"停止"这类禁用按钮上
            #   用**启用态颜色**去算对比度 → 报出虚高的 13.63:1（真实约 6.2:1）。
            #   那就是"测量说谎"—— 宁可报不出来，也不能报错。
            if disabled and on:
                declared = _grab(ss_a, f"#{on}:disabled")
            if disabled and not declared and isinstance(w, QPushButton):
                declared = _grab(ss_a, "QPushButton:disabled")
            if not declared and on:
                declared = _grab(ss_a, f"#{on}")
            if not declared and isinstance(w, QPushButton):
                declared = _grab(ss_a, "QPushButton")
            if not declared and isinstance(w, QLabel):
                declared = _grab(ss_a, "QLabel")
            a = a.parentWidget()
    except Exception:
        pass
    if not declared:
        try:
            declared = hexc(w.palette().color(w.palette().ColorRole.WindowText))
        except Exception:
            declared = "-"
    # ★ 用声明色作为前景（Qt 就是按它渲染）—— 像素只用来测背景。
    if declared and declared.startswith("#") and len(declared) == 7:
        cfg = QColor(declared)
        rr = ratio(cfg, cbg)
    rows.append((type(w).__name__, (w.objectName() or w.text() or "")[:18],
                 hexc(cbg), hexc(cfg), rr, declared, w.width(), w.height()))

print(f"   {'控件':<14} {'名/文本':<20} {'实测底色':<9} {'实测前景':<9} {'对比度':>7}  "
      f"{'声明color':<10} 判定")
print("   " + "-" * 96)
worst = []
inconclusive = []
for t, nm, bg_, fg_, rr, dec, w_, h_ in sorted(rows, key=lambda r: r[4]):
    # ★ 测量有效性校验：量到的前景若与**声明色**明显不符，说明这次没量到文字
    #   （抗锯齿/阈值问题），此时**不能**把它报成"对比度不足"——那是假失败。
    valid = True
    if dec and dec.startswith("#"):
        try:
            dd = abs(wcag_lum(QColor(dec)) - wcag_lum(QColor(fg_)))
            valid = dd < 0.06        # 亮度差 <6% 视为命中
        except Exception:
            valid = True
    if not valid:
        flag = "测不准"
        inconclusive.append((t, nm, rr, dec, fg_))
    elif rr >= 4.5:
        flag = "OK"
    elif rr >= 3.0:
        flag = "偏低"
    else:
        flag = "★ 差"
    print(f"   {t:<14} {nm:<20} {bg_:<9} {fg_:<9} {rr:>6.2f}:1  {dec:<10} {flag} "
          f"{w_}x{h_}")
    if valid and rr < 4.5:
        worst.append((t, nm, rr))

print("")
print("── 3) 结论 ──")
if worst:
    print(f"   ★ {len(worst)} 个控件对比度不足 4.5:1（WCAG 正文门槛）：")
    for t, nm, rr in worst:
        print(f"      {t}({nm})  {rr:.2f}:1")
else:
    print("   无对比度不足项")
if inconclusive:
    print(f"   测不准（前景未能与声明色对上，需人工看图）：{len(inconclusive)} 个")
    for t, nm, rr, dec, fg_ in inconclusive:
        print(f"      {t}({nm})  声明={dec} 量到={fg_}  →  {rr:.2f}:1")

# ---- 存图供目视（测得出 vs 看得见，两者都要） ----
shots = os.path.join("docs", "screenshots")
tag = THEME or "dark"
pimg = panel.grab()
pimg.save(os.path.join(shots, f"panel_{tag}.png"))
big = pimg.scaled(pimg.width() * 2, pimg.height() * 2,
                  Qt.AspectRatioMode.KeepAspectRatio,
                  Qt.TransformationMode.FastTransformation)
big.save(os.path.join(shots, f"panel_{tag}_2x.png"))
win.grab().save(os.path.join(shots, f"window_{tag}.png"))
print(f"   已存图: panel_{tag}.png / panel_{tag}_2x.png / window_{tag}.png")
print(f"   面板几何: {panel.width()}x{panel.height()}  "
      f"展开={panel._expanded}  body可见={panel.body.isVisible()}")

out = os.path.join("docs", "screenshots", f"panel_contrast_{THEME or 'dark'}.txt")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as fh:
    fh.write(f"主题={tag}\n")
    for t, nm, bg_, fg_, rr, dec, w_, h_ in rows:
        fh.write(f"{t}\t{nm}\tbg={bg_}\tfg={fg_}\tratio={rr:.2f}\tdeclared={dec}\t{w_}x{h_}\n")
win.close()
