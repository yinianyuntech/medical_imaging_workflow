#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取证：compat 层把未绑定的 QDialog.exec 当作 exec_ 注入，导致调用报
   `exec(self): first argument of unbound method must have type 'QDialog'`。

用 QTimer 立即 reject，避免真的进入模态事件循环。
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from PyQt6.QtCore import QTimer, QObject
from PyQt6.QtWidgets import QApplication as _QApp
import PyQt6.QtWidgets as _W

app = _QApp([])

from src.core.qt_compat.QtWidgets import QDialog as CompatDialog  # noqa: E402

RealDialog = _W.QDialog

print("=" * 74)
print("1) 真实 QDialog vs 兼容层 QDialog")
print("=" * 74)
print(f"   真实 QDialog        : {RealDialog}")
print(f"   兼容层 QDialog      : {CompatDialog}")
print(f"   是否同一个类        : {CompatDialog is RealDialog}")
print(f"   MRO                 : {[c.__name__ for c in CompatDialog.__mro__][:4]}")
print(f"   兼容类命名空间里有 exec_ : {'exec_' in CompatDialog.__dict__}")
obj = CompatDialog.__dict__.get("exec_")
print(f"   exec_ 的类型         : {type(obj).__name__}")
print(f"   exec_ 是否实现 __get__ : {hasattr(type(obj), '__get__')}")
print(f"   exec_ 就是 QDialog.exec : {obj is RealDialog.__dict__.get('exec')}")

print("=" * 74)
print("2) 真实 QDialog 直接取 exec / exec_ 对比")
print("=" * 74)
for nm in ("exec", "exec_"):
    v = getattr(RealDialog, nm, None)
    print(f"   QDialog.{nm:6} -> {type(v).__name__ if v else '不存在'}"
          f"   __get__={hasattr(type(v),'__get__') if v else '-'}")


class SubCompat(CompatDialog):
    """模拟应用里的写法：class X(QDialog) ← 用的是兼容层的 QDialog。"""


class SubReal(RealDialog):
    """对照组：直接继承真实 QDialog。"""


print("=" * 74)
print("3) 实际调用（QTimer 立即 reject，避免模态阻塞）")
print("=" * 74)


def try_exec(label, dlg):
    QTimer.singleShot(60, dlg.reject)
    t0 = time.time()
    try:
        r = dlg.exec_()
        print(f"   {label:34} OK  返回={r}  耗时={time.time()-t0:.2f}s")
        return True
    except TypeError as e:
        print(f"   {label:34} TypeError: {e}")
    except Exception as e:  # noqa: BLE001
        print(f"   {label:34} {type(e).__name__}: {e}")
    return False


print("   ---- 用 exec_()（旧写法）----")
ok1 = try_exec("SubReal  (真实 QDialog).exec_()", SubReal())
ok2 = try_exec("SubCompat(兼容 QDialog).exec_()", SubCompat())

print("   ---- 用 exec()（PyQt6 写法）----")
ok3 = try_exec("SubCompat(兼容 QDialog).exec()", SubCompat())
ok4 = try_exec("SubReal  (真实 QDialog).exec()", SubReal())

print("=" * 74)
print("4) 显式未绑定调用（复现错误文本）")
print("=" * 74)
d = SubReal()
try:
    RealDialog.exec(object())
except TypeError as e:
    print(f"   RealDialog.exec(object())  -> TypeError: {e}")
try:
    RealDialog.exec()
except TypeError as e:
    print(f"   RealDialog.exec()          -> TypeError: {e}")

print("=" * 74)
print("结论")
print("=" * 74)
print(f"   真实 QDialog + exec_  : {'可用' if ok1 else '不可用'}")
print(f"   兼容 QDialog + exec_  : {'可用' if ok2 else '不可用'}")
print(f"   兼容 QDialog + exec   : {'可用' if ok3 else '不可用'}")
print(f"   真实 QDialog + exec   : {'可用' if ok4 else '不可用'}")
