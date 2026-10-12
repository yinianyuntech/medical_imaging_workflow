#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证主题刷新协议：refresh_theme() 是否真的让构造期写死的配色跟随主题。"""

import os
import re
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("MIMW_SKIN", "metal")

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ.pop("MIMW_THEME", None)   # 走 ThemeManager，不强制

from src.core.qt_compat.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from src.utils import skeuo_style as st  # noqa: E402
from src.utils import skeuomorphic as sk  # noqa: E402
from src.utils.theme_manager import ThemeManager  # noqa: E402

ThemeManager._current_theme = "dark"
sk.apply_global(app)
st.install(app)

from ui.widgets.feedback_optimization_widget import (  # noqa: E402
    DraftCard, FeedbackOptimizationWidget,
)

CARD = DraftCard({
    "title": "T", "timestamp": "now", "abstract_preview": "abs", "model": "m",
    "user_score": 5, "requires_manual_completion": True,
    "manual_completion_reason": "r",
})
FBO = FeedbackOptimizationWidget()


def head(s):
    m = re.search(r"background(?:-color)?:\s*(#[0-9A-Fa-f]{6})", s or "")
    return m.group(1) if m else "-"


def col(s):
    m = re.search(r"(?<![-a-z])color:\s*(#[0-9A-Fa-f]{6})", s or "")
    return m.group(1) if m else "-"


def dump(tag):
    print(f"  [{tag}] DraftCard.bg={head(CARD.styleSheet())} "
          f"time={col(CARD.time_lbl.styleSheet())} "
          f"model_bg={head(CARD.model_lbl.styleSheet())} "
          f"manual_bg={head(CARD.manual_lbl.styleSheet())}")
    print(f"         stats_frame={head(FBO.stats_frame.styleSheet())} "
          f"stat_total={col(FBO.stat_total.styleSheet())}")


print("=" * 68)
print("协议存在性")
print("  DraftCard.refresh_theme            :", callable(getattr(DraftCard, "refresh_theme", None)))
print("  FeedbackOptimizationWidget.refresh_theme:",
      callable(getattr(FeedbackOptimizationWidget, "refresh_theme", None)))

print("=" * 68)
print("步骤 1：深色构造")
dump("dark")

print("=" * 68)
print("步骤 2：热切浅色 + 调 refresh_theme()")
ThemeManager._current_theme = "light"
st.reset_texture_cache()
sk.apply_global(app)
st.install(app)
CARD.refresh_theme()
FBO.refresh_theme()
app.processEvents()
time.sleep(0.1)
dump("light")

print("=" * 68)
print("步骤 3：切回深色")
ThemeManager._current_theme = "dark"
st.reset_texture_cache()
sk.apply_global(app)
st.install(app)
CARD.refresh_theme()
FBO.refresh_theme()
app.processEvents()
time.sleep(0.1)
dump("dark2")

print("=" * 68)
# 扫描全工程实现了 refresh_theme 的类
n = 0
for k, mod in list(sys.modules.items()):
    if not k.startswith("ui."):
        continue
    for nm, obj in vars(mod).items():
        if isinstance(obj, type) and callable(getattr(obj, "refresh_theme", None)):
            print("  实现 refresh_theme:", f"{k}.{nm}")
            n += 1
print(f"  共 {n} 个类实现了主题刷新协议")
