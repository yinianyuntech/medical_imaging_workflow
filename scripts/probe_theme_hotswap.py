#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实测：主题能否热切换（不重启进程），以及有哪些残留。

流程：以深色启动 → 抓图 → 运行时切浅色 → 抓图 → 对比 → 排查残留。
"""

import inspect
import os
import re
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("MIMW_SKIN", "metal")

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

RE_HEX = re.compile(r"#[0-9A-Fa-f]{3,8}")

from src.core.qt_compat.QtWidgets import QApplication, QWidget  # noqa: E402

app = QApplication.instance() or QApplication([])

from src.utils import skeuo_style as st  # noqa: E402
from src.utils import skeuomorphic as sk  # noqa: E402
from src.utils.theme_manager import ThemeManager  # noqa: E402

sk.apply_global(app)
st.install(app)

from ui.widgets.main_window import MainWindow  # noqa: E402

win = MainWindow(remaining_seconds=0, license_exp_ts=0)
win.resize(1400, 900)
win.show()


def pump(n=14):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.05)


def snapshot():
    img = win.grab().toImage()
    hist = Counter()
    for y in range(0, img.height(), 7):
        for x in range(0, img.width(), 7):
            c = img.pixelColor(x, y)
            hist[(c.red() // 24, c.green() // 24, c.blue() // 24)] += 1
    total = sum(hist.values()) or 1
    avg = 0.0
    for (r, g, b), n in hist.items():
        avg += (r * 24 + g * 24 + b * 24) / 3.0 * n
    avg /= total
    top = [(f"#{r*24:02X}{g*24:02X}{b*24:02X}", n) for (r, g, b), n in hist.most_common(3)]
    return avg, top


print("=" * 72)
print("步骤 1：深色启动")
pump(12)
avg, top = snapshot()
print(f"  平均亮度 = {avg:6.1f}")
print(f"  主色     = {top}")

print("=" * 72)
print("步骤 2：运行时切浅色（调用真实的 apply_theme_live）")
ok = win.apply_theme_live("light")
print(f"  apply_theme_live 返回: {ok}")
pump(14)
avg2, top2 = snapshot()
print(f"  平均亮度 = {avg2:6.1f}   （变化 {avg2 - avg:+.1f}）")
print(f"  主色     = {top2}")
verdict = "热更新【生效】" if avg2 > avg + 45 else "热更新【不完整】"
print(f"  → {verdict}")

print("=" * 72)
print("步骤 3：残留排查")

cache = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "MedicalImagingWorkflow", "cache", "skin")
try:
    mats = sorted(os.listdir(cache))
    print("  材质缓存（按主题分名）:", mats[-6:])
except Exception as e:
    print("  材质缓存读取失败:", e)

inline = [w for w in app.allWidgets() if (w.styleSheet() or "").strip()]
print(f"  仍有内联样式表的控件: {len(inline)}")
for w in inline[:6]:
    ss = (w.styleSheet() or "").replace("\n", " ")[:66]
    print(f"     {type(w).__name__:18} {ss}")

hard = set()
for k, mod in list(sys.modules.items()):
    if not k.startswith("ui."):
        continue
    for name, obj in vars(mod).items():
        if not inspect.isclass(obj) or not issubclass(obj, QWidget):
            continue
        fn = obj.__dict__.get("paintEvent")
        if fn is None:
            continue
        try:
            src = inspect.getsource(fn)
        except Exception:
            continue
        if RE_HEX.search(src):
            hard.add(f"{k}.{name}")
print(f"  自绘(paintEvent) 且写死颜色的类: {len(hard)}")
for h in sorted(hard)[:8]:
    print("     ", h)

print("=" * 72)
out = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots",
                   "theme_hot_light.png")
win.grab().save(out)
print("浅色抓图:", os.path.abspath(out))
win.close()
