#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""菜单响应 + 子页面皮肤覆盖 排查。

回答两个具体问题：
  A. **点菜单真的没响应吗？** —— 用真实鼠标点菜单栏，检查弹窗是否出现、是否可见；
     再触发每个动作，检查页面是否真的切换。
     （之前的排查台用 `click()`/`trigger()`，都绕过了鼠标，也没测过菜单栏。）
  B. **子页面到底有没有套上皮肤？** —— 逐页截图 + 统计引擎接管计数，
     用证据回答"是不是只有主界面重新设计了"。

用法：
    python scripts/check_menus_and_pages.py
"""

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
    QApplication, QWidget, QScrollArea, QMenuBar, QMenu, QAbstractButton,
)

user32 = ctypes.windll.user32
GA_ROOT = 2
HWND_TOPMOST = -1
SWP_NOMOVE, SWP_NOSIZE, SWP_SHOWWINDOW = 0x0002, 0x0001, 0x0040
LEFTDOWN, LEFTUP = 0x0002, 0x0004


def hwnd_at(x, y):
    p = wt.POINT(int(x), int(y))
    h = user32.WindowFromPoint(p)
    return (user32.GetAncestor(h, GA_ROOT) or h) if h else 0


app = QApplication.instance() or QApplication([])

from src.utils import skeuomorphic as sk  # noqa: E402
from src.utils import skeuo_style as st  # noqa: E402

sk.apply_global(app)
st.install(app)

from ui.widgets.main_window import MainWindow  # noqa: E402

win = MainWindow(remaining_seconds=0, license_exp_ts=0)
win.resize(1680, 1000)
win.show()

OUT = []


def say(s=""):
    OUT.append(str(s))
    print(s)


def pump(n=12, dt=0.03):
    for _ in range(n):
        app.processEvents()
        time.sleep(dt)


pump(26)

stack = win.stacked_widget
mb = win.menuBar()

say("=" * 92)
say("A. 菜单结构（动作 → 是否已连接 → 触发后页面是否切换）")
say("=" * 92)

# ⚠️ 必须跳过系统级动作：「系统 → 退出」触发后会**直接关闭应用**
#    （第一次跑这个脚本就踩到了 —— a.trigger() 把整个程序关掉了）。
SKIP_ACTIONS = ("退出", "关闭", "exit", "quit", "退出系统")
_opened = []
_closer = QTimer()
_closer.setInterval(120)


def _close_modal():
    try:
        d = app.activeModalWidget()
        if d is not None:
            _opened.append(type(d).__name__)
            d.reject()
    except Exception:
        pass


_closer.timeout.connect(_close_modal)
_closer.start()

act_rows = []
for top in mb.actions():
    menu = top.menu()
    if menu is None:
        continue
    say("")
    say(f"▸ 菜单 [{top.text().replace('&', '')}]  {len(menu.actions())} 项")
    for a in menu.actions():
        if a.isSeparator():
            continue
        txt = a.text().replace("&", "")
        if any(k in txt.lower() or k in txt for k in SKIP_ACTIONS):
            say(f"    {txt:<28} 接收=-    ★ 系统级动作，**不触发**（会关闭应用）")
            act_rows.append((top.text().replace("&", ""), txt, -1, "跳过（系统级）",
                             stack.currentIndex(), stack.currentIndex()))
            continue
        recv = -1
        try:
            recv = int(a.receivers(a.triggered))
        except Exception:
            try:
                recv = int(a.receivers("2triggered()"))
            except Exception:
                recv = -1
        before = stack.currentIndex()
        n0 = len(_opened)
        try:
            a.trigger()
            pump(14)
            after = stack.currentIndex()
            moved = "→ 页面 %d→%d" % (before, after) if before != after else "页面未变"
            if len(_opened) > n0:
                moved += f"（弹出 {','.join(_opened[n0:])}）"
        except Exception as e:  # noqa: BLE001
            moved = f"触发异常 {type(e).__name__}: {e}"
        act_rows.append((top.text().replace("&", ""), txt, recv, moved, before, after))
        say(f"    {txt:<28} 接收={recv:<4} {moved}")

say("")
say("=" * 92)
say("B. 真实鼠标点菜单栏（检验弹窗是否出现 / 可见）")
say("=" * 92)

win.setWindowFlag(Qt.WindowStaysOnTopHint, True)
win.show()
win.raise_()
win.activateWindow()
try:
    user32.ShowWindow(int(win.winId()), 9)
    user32.SetForegroundWindow(int(win.winId()))
    user32.SetActiveWindow(int(win.winId()))
except Exception:
    pass
pump(20)
hwnd = int(win.winId())
user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
pump(14)
dpr = float(win.devicePixelRatioF() or 1.0)

# 找出菜单栏每一项的屏幕位置
items = []
for top in mb.actions():
    if top.menu() is None:
        continue
    try:
        rect = mb.actionGeometry(top)      # 菜单栏坐标
    except Exception:
        continue
    c = rect.center()
    items.append((top.text().replace("&", ""), c, rect))

say(f"   菜单栏可见={mb.isVisible()}  高度={mb.height()}  项数={len(items)}")
ok_popup = 0
for name, c, rect in items:
    try:
        g = mb.mapToGlobal(c)
        sx, sy = int(g.x() * dpr), int(g.y() * dpr)
        user32.SetCursorPos(sx, sy)
        time.sleep(0.30)
        pump(10)
        over = (hwnd_at(sx, sy) == hwnd)
        user32.mouse_event(LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.10)
        user32.mouse_event(LEFTUP, 0, 0, 0, 0)
        time.sleep(0.45)
        pump(20)
        pop = QApplication.activePopupWidget()
        if pop is None:
            say(f"   {name:<26} 光标在窗口={over}  ★ 弹窗未出现")
        else:
            img = pop.grab().toImage()
            # 判断"看得见"：像素不能全同 / 不能全透明
            w_, h_ = img.width(), img.height()
            colors = set()
            opaque = 0
            step = max(1, min(w_, h_) // 20)
            for y in range(0, h_, step):
                for x in range(0, w_, step):
                    col = img.pixelColor(x, y)
                    colors.add((col.red() // 24, col.green() // 24, col.blue() // 24))
                    if col.alpha() > 200:
                        opaque += 1
            visible = len(colors) >= 2 and opaque > 0
            ok_popup += 1 if visible else 0
            say(f"   {name:<26} 光标在窗口={over}  弹窗={type(pop).__name__} "
                f"{w_}x{h_}  颜色簇={len(colors)}  不透明采样={opaque}  "
                f"{'可见 ✓' if visible else '★ 不可见'}")
            pop.close()
            pump(10)
    except Exception as e:  # noqa: BLE001
        say(f"   {name:<26} 异常 {type(e).__name__}: {e}")

say(f"   小结：{ok_popup}/{len(items)} 个菜单弹窗点击后可见")

say("")
say("=" * 92)
say("C. 子页面皮肤覆盖（逐页截图 + 引擎接管计数）")
say("=" * 92)

shots = os.path.join("docs", "screenshots")
os.makedirs(shots, exist_ok=True)
for i in range(stack.count()):
    stack.setCurrentIndex(i)
    pump(12)
    holder = stack.widget(i)
    page = holder.widget() if isinstance(holder, QScrollArea) else holder
    name = type(page).__name__
    pimg = page.grab()
    path = os.path.join(shots, f"page_{i}_{name}.png")
    pimg.save(path)
    # 皮肤痕迹：统计用了引擎画的面板/玻璃的数量（用调色板文本色判断被套过皮）
    n_group = len(page.findChildren(QWidget, options=Qt.FindChildOption.FindChildrenRecursively)) if False else 0
    from src.core.qt_compat.QtWidgets import QGroupBox
    gbs = page.findChildren(QGroupBox)
    try:
        from src.utils.skeuomorphic import current_palette
        pal = current_palette().name
    except Exception:
        pal = "?"
    say(f"   p{i} {name:<26} 尺寸={pimg.width()}x{pimg.height()}  "
        f"分组框={len(gbs)}  主题={pal}  → {os.path.basename(path)}")

say("")
say("   引擎接管计数（全局，按控件类型）:")
try:
    say("     " + str(dict(st.SkeuomorphicStyle.hits)))
except Exception as e:  # noqa: BLE001
    say("     读取失败: %s" % e)

say("")
say("=" * 92)
say("D. 真实鼠标端到端：点菜单栏 → 点弹窗项 → 页面是否真的切换")
say("=" * 92)


def click_global(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.28)
    pump(8)
    user32.mouse_event(LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.10)
    user32.mouse_event(LEFTUP, 0, 0, 0, 0)
    time.sleep(0.55)
    pump(24)


nav_ok = 0
nav_tot = 0
for name, c, rect in items:
    menu = None
    for top in mb.actions():
        if top.text().replace("&", "") == name:
            menu = top.menu()
            break
    if menu is None:
        continue
    # 找该菜单里第一个可导航（且非系统级）的动作
    target = None
    for a in menu.actions():
        if a.isSeparator():
            continue
        txt = a.text().replace("&", "")
        if any(k in txt.lower() or k in txt for k in SKIP_ACTIONS):
            continue
        target = a
        break
    if target is None:
        continue
    nav_tot += 1
    before = stack.currentIndex()
    g = mb.mapToGlobal(c)
    click_global(int(g.x() * dpr), int(g.y() * dpr))
    pop = QApplication.activePopupWidget()
    if pop is None:
        say(f"   {name:<22} → {target.text().replace('&',''):<22} ★ 弹窗未出现")
        continue
    try:
        ar = pop.actionGeometry(target)
        ag = pop.mapToGlobal(ar.center())
        click_global(int(ag.x() * dpr), int(ag.y() * dpr))
    except Exception as e:  # noqa: BLE001
        say(f"   {name:<22} 点击弹窗项异常 {type(e).__name__}: {e}")
        continue
    after = stack.currentIndex()
    ok = before != after
    nav_ok += 1 if ok else 0
    say(f"   {name:<22} → {target.text().replace('&',''):<22} "
        f"页面 {before}→{after}  {'✓ 已切页' if ok else '★ 未切页'}")

say(f"   小结：真实鼠标点菜单导航 {nav_ok}/{nav_tot} 成功切页")

rep = os.path.join(shots, "menus_pages.txt")
with open(rep, "w", encoding="utf-8") as fh:
    fh.write("\n".join(OUT) + "\n")
print("\n报告 ->", os.path.abspath(rep))
win.close()
