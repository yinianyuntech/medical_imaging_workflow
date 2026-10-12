#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""枚举兼容内核。

PyQt5 允许**无作用域**枚举访问（`Qt.AlignCenter`、`QMessageBox.Yes`），
PyQt6 强制**作用域化**（`Qt.AlignmentFlag.AlignCenter`、
`QMessageBox.StandardButton.Yes`）。本模块通过两条路径把旧写法还原：

1. `compat_class(real_cls)` —— 用 `type()` 生成一个**子类**，把该类的**全部枚举成员**
   直接挂成类属性。这样 `QMessageBox.Yes` 可用，同时 `QMessageBox.warning(...)`
   等静态方法照常继承；返回值仍是**真实枚举成员**，`==` / `|` / `int()` 语义不变。
2. `NamespaceProxy` —— `Qt` 这类纯命名空间无法子类化，改用属性代理：
   先查真实属性，再回落到枚举成员索引。
"""

from __future__ import annotations

import enum
from typing import Any, Dict, Optional

__all__ = ["enum_index", "compat_class", "NamespaceProxy"]


def enum_index(cls: type) -> Dict[str, Any]:
    """收集 `cls` 上所有嵌套枚举类的成员，按**成员名**建索引。

    例如 QMessageBox -> {"Yes": StandardButton.Yes, "AcceptRole": ButtonRole.AcceptRole, ...}
    遇到同名冲突时保留**先出现**的那个（与 PyQt5 的解析顺序一致）。
    """
    out: Dict[str, Any] = {}
    for attr in dir(cls):
        try:
            obj = getattr(cls, attr)
        except Exception:
            continue
        if isinstance(obj, type) and issubclass(obj, enum.Enum):
            for key, member in obj.__members__.items():
                out.setdefault(key, member)
    return out


def _exec_alias(real_cls: type) -> Dict[str, Any]:
    """PyQt6 用 `exec()`；旧代码写 `exec_()`。给需要的类补一个**能正确绑定 self** 的别名。

    ⚠️ **绝不能**写成 `{"exec_": getattr(real_cls, "exec")}`。

    PyQt6 里**类级访问** `cls.exec` 返回的是 `builtin_function_or_method`，它有两个陷阱：
      1. 它**已经绑定到类**（实测 `__self__ = <class 'PyQt6.QtWidgets.QDialog'>`）；
      2. 它**不是描述符**（`type(obj).__get__` 不存在）。
    把它塞进子类命名空间后，`dialog.exec_()` 不会重新绑定实例，而是直接拿**类**当
    self 调用底层方法 —— sip 于是报：

        exec(self): first argument of unbound method must have type 'QDialog'

    （这正是"新建项目报错"和"首启向导打开失败"的根因；
      全工程 29 处 `exec_()` 调用全部受影响。）

    真正的描述符藏在 `cls.__dict__["exec"]`（实测 `type=methoddescriptor`）。
    取它才对：
      * 普通方法 → 实例级访问自动绑定实例 ✅
      * **静态方法**（如 `QApplication.exec`）→ `staticmethod` 对象不绑定，语义也正确 ✅
    """
    if hasattr(real_cls, "exec_"):
        return {}
    for klass in real_cls.__mro__:
        raw = klass.__dict__.get("exec")
        if raw is not None:
            return {"exec_": raw}
    return {}


def compat_class(
    real_cls: type,
    *,
    extra: Optional[Dict[str, Any]] = None,
    name: Optional[str] = None,
    with_exec: bool = True,
) -> type:
    """返回带 PyQt5 风格无作用域枚举的子类（无枚举时原样返回）。"""
    ns: Dict[str, Any] = enum_index(real_cls)
    if with_exec:
        ns.update(_exec_alias(real_cls))
    if extra:
        ns.update(extra)
    if not ns:
        return real_cls
    try:
        return type(name or real_cls.__name__, (real_cls,), ns)
    except Exception:
        return real_cls


class NamespaceProxy:
    """`Qt` 命名空间的属性代理：真实属性优先，其次枚举成员。"""

    __slots__ = ("_real", "_index")

    def __init__(self, real: Any):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_index", enum_index(real))

    def __getattr__(self, name: str) -> Any:
        real = object.__getattribute__(self, "_real")
        try:
            return getattr(real, name)
        except AttributeError:
            pass
        index = object.__getattribute__(self, "_index")
        if name in index:
            return index[name]
        raise AttributeError(
            f"{getattr(real, '__name__', 'namespace')} has no attribute {name!r}"
        )

    def __dir__(self):
        real = object.__getattribute__(self, "_real")
        index = object.__getattribute__(self, "_index")
        return sorted(set(dir(real)) | set(index))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<NamespaceProxy {getattr(object.__getattribute__(self,'_real'),'__name__','?')}>"
