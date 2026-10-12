#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_qt_migration.py —— 迁移后静态校验。

检查：
  1. 是否还有生效的 `from/import PyQt5`；
  2. 所有 .py 是否可编译；
  3. 关键模块能否在 PyQt6 下成功导入（可选用 --import）。
"""

import os
import py_compile
import re
import sys

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SKIP_DIRS = {"__pycache__", ".git", "dist", "build", "node_modules"}
PAT = re.compile(r"^\s*(from|import)\s+PyQt5\b")

# 与本次迁移无关的既存损坏文件（git 未改动；属于可选 Flask API，main.py 已禁用该通道）
KNOWN_BROKEN = {
    os.path.join("src", "api", "routes", "ocr_routes.py"),
}


def walk():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def main() -> int:
    fails = 0

    print("== 1) 遗留 PyQt5 导入 ==")
    left = []
    for p in walk():
        rel = os.path.relpath(p, ROOT)
        if rel.startswith(os.path.join("src", "core", "qt_compat")):
            continue  # 兼容层自身的文档示例
        try:
            with open(p, "r", encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    if PAT.match(line):
                        left.append(f"{rel}:{n}: {line.strip()}")
        except Exception:
            continue
    if left:
        fails += 1
        for x in left:
            print("  " + x)
    else:
        print("  none ✅")

    print("== 2) 编译 ==")
    bad = []
    known = []
    n_ok = 0
    for p in walk():
        rel = os.path.relpath(p, ROOT)
        try:
            py_compile.compile(p, doraise=True)
            n_ok += 1
        except Exception as e:  # noqa: BLE001
            if rel in KNOWN_BROKEN:
                known.append(f"{rel}: {str(e).splitlines()[0][:90]}")
            else:
                bad.append(f"{rel}: {e}")
    if known:
        print("  [已知既存问题，非本次迁移引入]")
        for x in known:
            print("    " + x)
    if bad:
        fails += 1
        for x in bad[:25]:
            print("  " + x)
    else:
        print(f"  {n_ok} files compiled ✅")

    print("== 3) qt_compat 覆盖 ==")
    n = 0
    for p in walk():
        try:
            with open(p, "r", encoding="utf-8") as f:
                n += sum(1 for line in f if "src.core.qt_compat" in line)
        except Exception:
            continue
    print(f"  {n} 行指向 qt_compat")

    if "--import" in sys.argv:
        print("== 4) 导入链 ==")
        sys.path.insert(0, ROOT)
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        mods = [
            "src.core.qt_compat.QtWidgets",
            "src.core.event_bus",
            "src.utils.theme_manager",
            "ui.widgets.opencode_panel",
            "ui.widgets.main_window",
        ]
        try:
            from src.core.qt_compat.QtWidgets import QApplication
            _app = QApplication.instance() or QApplication([])
        except Exception as e:  # noqa: BLE001
            print(f"  QApplication FAILED: {e}")
            fails += 1
        for m in mods:
            try:
                __import__(m)
                print(f"  {m} OK")
            except Exception as e:  # noqa: BLE001
                fails += 1
                print(f"  {m} FAILED: {type(e).__name__}: {e}")

    print()
    print("RESULT:", "FAIL" if fails else "PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
