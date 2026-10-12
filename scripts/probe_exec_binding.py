#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核准事实：PyQt6 的方法在**类级访问**与**实例级访问**下的绑定行为。

决定 `exec_` 别名该怎么写，必须先把这些事实测出来，不能猜。
全部诊断都**不真正调用 exec()**（避免进入模态循环阻塞）。
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from PyQt6.QtWidgets import QApplication as _QApp
import PyQt6.QtWidgets as _W
import PyQt6.QtGui as _G

app = _QApp([])

from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QDialog, QMessageBox, QFileDialog, QInputDialog, QProgressDialog, QMenu,
    QApplication as CompatApp,
)

RealDialog = _W.QDialog


def describe(label, obj, owner=None):
    t = type(obj).__name__
    self_ = getattr(obj, "__self__", None)
    name = getattr(obj, "__name__", "?")
    s_txt = repr(self_) if self_ is not None else "None"
    print(f"   {label:46} type={t:28} name={name:16} __self__={s_txt}")


print("=" * 100)
print("1) 类级访问：cls.exec（真实类 vs 兼容类）")
print("=" * 100)
describe("RealDialog.exec (class-level)", RealDialog.exec)
describe("CompatDialog.exec (class-level)", QDialog.exec)
describe("RealDialog.__dict__['exec']", RealDialog.__dict__.get("exec"))
print(f"   type(RealDialog.exec) 有 __get__ : {hasattr(type(RealDialog.exec), '__get__')}")
print(f"   RealDialog.exec is RealDialog.__dict__['exec'] : "
      f"{RealDialog.exec is RealDialog.__dict__.get('exec')}")

print("=" * 100)
print("2) 实例级访问：d.exec（这才是所有 PyQt6 代码依赖的路径）")
print("=" * 100)
d_real = RealDialog()
m = d_real.exec
describe("RealDialog().exec", m)
print(f"      __self__ is instance : {getattr(m, '__self__', None) is d_real}")

d_compat = QDialog()
m2 = d_compat.exec
describe("CompatDialog().exec", m2)
print(f"      __self__ is instance : {getattr(m2, '__self__', None) is d_compat}")


class SubReal(RealDialog):
    pass


class SubCompat(QDialog):
    pass


for cls in (SubReal, SubCompat):
    inst = cls()
    mm = inst.exec
    describe(f"{cls.__name__}().exec", mm)
    print(f"      __self__ is instance : {getattr(mm, '__self__', None) is inst}")

print("=" * 100)
print("3) compat QDialog 实例上 exec_ 的绑定（病根所在）")
print("=" * 100)
inst = SubCompat()
e = inst.exec_
describe("SubCompat().exec_", e)
print(f"      __self__ is instance : {getattr(e, '__self__', None) is inst}")

print("=" * 100)
print("4) 其它被 compat 包装的类：exec 是普通方法还是静态方法？")
print("=" * 100)
for nm, cls, real in (
    ("QMessageBox", QMessageBox, _W.QMessageBox),
    ("QFileDialog", QFileDialog, _W.QFileDialog),
    ("QInputDialog", QInputDialog, _W.QInputDialog),
    ("QProgressDialog", QProgressDialog, _W.QProgressDialog),
    ("QMenu", QMenu, _W.QMenu),
    ("QApplication", CompatApp, _W.QApplication),
):
    raw = getattr(real, "exec", None)
    if raw is None:
        print(f"   {nm:16} 无 exec")
        continue
    has_get = hasattr(type(raw), "__get__")
    s = getattr(raw, "__self__", None)
    s_txt = repr(s) if s is not None else "None"
    print(f"   {nm:16} class-level type={type(raw).__name__:28} __get__={has_get} "
          f"__self__={s_txt}")

    # 实例级绑定
    try:
        if cls is CompatApp:
            continue
        if cls is QMenu:
            continue
        if cls in (QMessageBox,):
            ins = cls()
        elif cls in (QFileDialog,):
            ins = cls()
        else:
            ins = None
        if ins is not None:
            bm = getattr(ins, "exec")
            print(f"                    instance 级 __self__ is instance : "
                  f"{getattr(bm, '__self__', None) is ins}")
    except Exception as exc:  # noqa: BLE001
        print(f"                    instance 级探测失败: {exc}")

print("=" * 100)
print("5) main.py 用的是哪种写法")
print("=" * 100)
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    with open(os.path.join(here, "main.py"), encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh, 1):
            if "exec" in line and ("app" in line or "exec_" in line):
                print(f"   main.py:{i}: {line.strip()[:90]}")
except Exception as exc:  # noqa: BLE001
    print("   读取失败:", exc)
