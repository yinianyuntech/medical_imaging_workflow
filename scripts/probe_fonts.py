#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""字体可用性探测：列出候选字体是否安装，并给出渲染对比样张。"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.core.qt_compat.QtGui import QFont, QFontDatabase  # noqa: E402
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QVBoxLayout, QLabel, QHBoxLayout,
)

app = QApplication.instance() or QApplication([])
fams = set(QFontDatabase.families())
print("字体总数:", len(fams))

CANDIDATES = [
    # 中文
    "Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑", "SimHei", "SimSun",
    "Source Han Sans SC", "Noto Sans CJK SC", "HarmonyOS Sans SC",
    "Alibaba PuHuiTi 3", "MiSans", "OPPO Sans", "思源黑体",
    # 西文/科技感
    "Segoe UI Variable Text", "Segoe UI Variable Display", "Segoe UI",
    "Bahnschrift", "Bahnschrift SemiBold", "Bahnschrift SemiCondensed",
    "Cascadia Mono", "Cascadia Code", "Consolas", "Arial", "Roboto",
    "DIN Alternate", "Oswald", "Rajdhani", "Orbitron",
]
print("\n=== 候选字体可用性 ===")
avail = []
for name in CANDIDATES:
    ok = name in fams
    if ok:
        avail.append(name)
    print(f"  {'✅' if ok else '❌'}  {name}")

print("\n=== 含 'Cascadia'/'Bahnschrift'/'YaHei' 的实际族名 ===")
for f in sorted(fams):
    if any(k in f for k in ("Cascadia", "Bahnschrift", "YaHei", "Yahei", "Sarasa", "JetBrains")):
        print("   ", f)


def measure(family: str, size: int, weight, bold: bool):
    f = QFont(family)
    f.setPointSize(size)
    if bold:
        f.setBold(True)
    try:
        f.setWeight(weight)
    except Exception:
        pass
    from src.core.qt_compat.QtGui import QFontMetrics
    fm = QFontMetrics(f)
    t = "医疗数据 1234.5678 ABCdef"
    return f"{fm.horizontalAdvance(t):4d}px  h={fm.height():2d}  asc={fm.ascent()}"


print("\n=== 字号/字重对宽度的影响（正文 12pt）===")
for fam in (["Microsoft YaHei"] + [a for a in avail if a != "Microsoft YaHei"][:6]):
    for bold in (False, True):
        try:
            print(f"  {fam:26} bold={str(bold):5} {measure(fam, 12, None, bold)}")
        except Exception as e:
            print(f"  {fam:26} 失败: {e}")

# 渲染一张对照样张
w = QWidget()
w.resize(980, 420)
w.setStyleSheet("background:#0B1524; color:#F0F6FF;")
lay = QVBoxLayout(w)
SAMPLES = [
    ("Microsoft YaHei", 12, False, "正文 · Microsoft YaHei 12pt · 医疗数据科学 0123456789"),
    ("Microsoft YaHei", 13, True,  "强调 · YaHei 13pt Bold · 医疗数据科学 0123456789"),
    ("Microsoft YaHei UI", 13, True, "候选 · YaHei UI 13pt Bold · 医疗数据科学 0123456789"),
    ("Bahnschrift", 14, True, "候选 · Bahnschrift 14pt · 医疗数据科学 ABC 0123456789"),
    ("Cascadia Mono", 13, False, "候选 · Cascadia Mono 13pt · 医疗数据 0123456789"),
    ("Consolas", 13, False, "候选 · Consolas 13pt · 医疗数据 0123456789"),
]
for fam, sz, bd, txt in SAMPLES:
    lb = QLabel(txt)
    f = QFont(fam)
    f.setPointSize(sz)
    f.setBold(bd)
    lb.setFont(f)
    lay.addWidget(lb)
w.show()
for _ in range(10):
    app.processEvents()
    time.sleep(0.04)
out = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots", "font_probe2.png")
w.grab().save(out)
print("\nsaved:", os.path.abspath(out))
