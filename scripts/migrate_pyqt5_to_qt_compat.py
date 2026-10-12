#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""migrate_pyqt5_to_qt_compat.py —— 把 `from PyQt5.<mod> import ...` 重定向到 qt_compat。

只改**模块来源**，不动导入符号、不动任何调用点，因此布局与业务代码零改动。
"""

import os
import re
import sys

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SKIP_DIRS = {"__pycache__", ".git", "dist", "build", "node_modules", "qt_compat"}

RULES = [
    (re.compile(r"^(\s*)from PyQt5\.QtWidgets import\b"),
     r"\1from src.core.qt_compat.QtWidgets import"),
    (re.compile(r"^(\s*)from PyQt5\.QtCore import\b"),
     r"\1from src.core.qt_compat.QtCore import"),
    (re.compile(r"^(\s*)from PyQt5\.QtGui import\b"),
     r"\1from src.core.qt_compat.QtGui import"),
    (re.compile(r"^(\s*)from PyQt5\.QtSvg import\b"),
     r"\1from src.core.qt_compat.QtSvg import"),
    (re.compile(r"^(\s*)from PyQt5\.QtPrintSupport import\b"),
     r"\1from src.core.qt_compat.QtWidgets import"),
    (re.compile(r"^(\s*)from PyQt5 import QtWidgets\b"),
     r"\1from src.core.qt_compat import QtWidgets"),
    (re.compile(r"^(\s*)from PyQt5 import QtCore\b"),
     r"\1from src.core.qt_compat import QtCore"),
    (re.compile(r"^(\s*)from PyQt5 import QtGui\b"),
     r"\1from src.core.qt_compat import QtGui"),
    (re.compile(r"^(\s*)import PyQt5\.QtWidgets as (\w+)"),
     r"\1from src.core.qt_compat import QtWidgets as \2"),
    (re.compile(r"^(\s*)import PyQt5\.QtCore as (\w+)"),
     r"\1from src.core.qt_compat import QtCore as \2"),
    (re.compile(r"^(\s*)import PyQt5\.QtGui as (\w+)"),
     r"\1from src.core.qt_compat import QtGui as \2"),
]


def collect():
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(os.path.join(dirpath, fn))
    return out


def main() -> int:
    dry = "--apply" not in sys.argv
    total_files = 0
    total_lines = 0
    leftover = []

    for path in collect():
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            continue
        changed = 0
        for i, line in enumerate(lines):
            for pat, rep in RULES:
                if pat.match(line):
                    new = pat.sub(rep, line, count=1)
                    if new != line:
                        lines[i] = new
                        changed += 1
                    break
        if changed:
            total_files += 1
            total_lines += changed
            rel = os.path.relpath(path, ROOT)
            print(f"  {changed:2d}  {rel}")
            if not dry:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.writelines(lines)

    # 二次扫描：是否还有真正生效的 PyQt5 导入
    for path in collect():
        try:
            with open(path, "r", encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    s = line.strip()
                    if s.startswith("#"):
                        continue
                    if re.match(r"^(from|import)\s+PyQt5\b", s):
                        leftover.append(f"{os.path.relpath(path, ROOT)}:{n}: {s}")
        except Exception:
            continue

    print()
    print(f"{'DRY-RUN' if dry else 'APPLIED'}: files={total_files} lines={total_lines}")
    if leftover:
        print("!! 仍有 PyQt5 导入:")
        for x in leftover:
            print("   " + x)
        return 1
    print("无遗留 PyQt5 导入 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
