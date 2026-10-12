#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""状态过渡动画层：悬停 / 键盘焦点的渐变过渡。

为什么必须单独一层
==================

`QProxyStyle` 是**无状态绘制器** —— Qt 每次重绘都独立调用它，
它拿不到"上一帧画到哪儿了"。所以过渡进度**只能存在控件上**
（动态属性），由事件驱动更新，绘制时再读回来。

核心设计
========

1. **布尔决定"是否画"，浮点决定"画多强"**
   引擎里 `hovered` 决定走不走悬停分支，`hover_k` 决定提亮多少。
   这样 `hover_k == 0` 能**精确复现**"无悬停"的样子 —— 动画的起点
   与静态渲染完全一致，不会出现首帧跳变。

2. **门控必须由动画驱动，不能由 state 位驱动**
   离开控件时 Qt **立刻**清掉 `State_MouseOver`。若用 state 位门控，
   离场动画根本没有插值机会，会"啪"地跳回去（比不做动画更难看）。
   所以：有动画属性时以属性为准（`> 0.001` 即视为"仍在悬停中"）。

3. **无动画层时自动退化为布尔**
   离屏渲染、`preview_skin.py`、静态体检脚本不安装动画层，
   `motion()` 返回 `None` → 引擎退回读 state 位 → **既有渲染逐像素不变**。

用法
====

    from src.utils.skeuo_motion import install_motion, PROP_HOVER, PROP_FOCUS
    install_motion(app)                      # 幂等；通常在 skeuo_style.install() 里调
    k = motion(widget, PROP_HOVER)           # None = 无动画层

测量：`scripts/probe_motion.py`（验证"中间帧确实在两端之间"，而不只是首尾两帧不同）。
"""

from typing import Optional

from src.core.qt_compat.QtCore import (
    QObject, QEvent, QVariantAnimation, QEasingCurve,
)
from src.core.qt_compat.QtWidgets import QWidget

# 动态属性名（存控件上；前缀避免与业务属性冲突）
PROP_HOVER = "_sk_hover"
PROP_FOCUS = "_sk_focus"

# 过渡时长。取 160ms：比 200ms 利落，又明显比瞬变柔和；
# 且远小于真机点验的等待窗口（约 0.7s），不会把测量搅成"测到中间帧"。
DURATION = 160

_EPS = 0.002

# ---------------------------------------------------------------- 状态读取


def motion(widget, prop: str) -> Optional[float]:
    """读取动画进度（0..1）。返回 `None` 表示**没有动画层**（退化为布尔）。"""
    if widget is None:
        return None
    try:
        v = widget.property(prop)
    except Exception:
        return None
    if v is None:
        return None
    try:
        return max(0.0, min(1.0, float(v)))
    except Exception:
        return None


def motion_hover(widget):
    """返回 `(是否画悬停, 悬停强度)`；无动画层时第二项为 1.0。"""
    k = motion(widget, PROP_HOVER)
    if k is None:
        return None, 1.0
    return (k > _EPS), k


# ---------------------------------------------------------------- 需要动画的控件


_ANIMATED = None


def _animated_classes():
    """只对引擎真正接管的控件做动画（避免给全应用每个控件都挂动画）。"""
    from src.core.qt_compat.QtWidgets import (
        QAbstractButton, QAbstractSlider, QAbstractSpinBox,
        QLineEdit, QComboBox, QTextEdit, QPlainTextEdit, QTabBar,
    )
    return (QAbstractButton, QAbstractSlider, QAbstractSpinBox,
            QLineEdit, QComboBox, QTextEdit, QPlainTextEdit, QTabBar)


def is_animated(w) -> bool:
    global _ANIMATED
    if _ANIMATED is None:
        try:
            _ANIMATED = _animated_classes()
        except Exception:
            _ANIMATED = ()
    try:
        return isinstance(w, _ANIMATED)
    except Exception:
        return False


# ---------------------------------------------------------------- 控制器


class MotionController(QObject):
    """应用级事件过滤器 → 驱动悬停/焦点的过渡动画。"""

    def __init__(self, app, duration: int = DURATION):
        super().__init__(app)
        self.duration = int(duration)
        self._anims: dict = {}
        self._map: dict = {}
        self.seen = 0        # 统计：过滤器看到的事件数（供性能核查）
        T = QEvent.Type
        for name, prop, target in (("Enter", PROP_HOVER, 1.0),
                                   ("Leave", PROP_HOVER, 0.0),
                                   ("FocusIn", PROP_FOCUS, 1.0),
                                   ("FocusOut", PROP_FOCUS, 0.0)):
            try:
                self._map[getattr(T, name)] = (prop, target)
            except Exception:
                pass

    # ---- 事件入口 ----
    def eventFilter(self, obj, ev):
        # 热路径：一次 C++ 调用 + 一次 dict 查找，其余全部提前返回
        try:
            hit = self._map.get(ev.type())
        except Exception:
            return False
        if hit is None:
            return False
        self.seen += 1
        try:
            if not isinstance(obj, QWidget) or not is_animated(obj):
                return False
        except Exception:
            return False
        self._to(obj, hit[0], hit[1])
        return False

    # ---- 驱动 ----
    def _to(self, w, prop: str, target: float):
        cur = motion(w, prop)
        if cur is None:
            try:
                w.setProperty(prop, 0.0)
            except Exception:
                return
            cur = 0.0
        if abs(cur - target) < _EPS:
            # 已到位：直接写终值，避免"零距离动画"抖动
            self._write(w, prop, target)
            return

        key = (id(w), prop)
        anim = self._anims.get(key)
        if anim is None:
            try:
                anim = QVariantAnimation(self)
            except Exception:
                self._write(w, prop, target)
                return
            anim.setDuration(self.duration)
            try:
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            except Exception:
                pass
            self._anims[key] = anim
            # 控件销毁时清理：字典持有控件引用会阻止回收 → 必须挂钩销毁信号
            try:
                w.destroyed.connect(lambda *_, k=key: self._drop(k))
            except Exception:
                pass

        try:
            anim.stop()
        except Exception:
            pass
        try:
            anim.valueChanged.disconnect()
        except Exception:
            pass
        try:
            anim.valueChanged.connect(
                lambda v, w=w, prop=prop: self._write(w, prop, v))
        except Exception:
            pass
        try:
            anim.setStartValue(float(cur))
            anim.setEndValue(float(target))
            anim.start()
        except Exception:
            self._write(w, prop, target)

    @staticmethod
    def _write(w, prop: str, v):
        try:
            w.setProperty(prop, float(v))
            w.update()
        except Exception:
            pass

    def _drop(self, key):
        a = self._anims.pop(key, None)
        if a is not None:
            try:
                a.stop()
                a.deleteLater()
            except Exception:
                pass

    def stop_all(self):
        for key in list(self._anims):
            self._drop(key)


# ---------------------------------------------------------------- 安装


_CONTROLLER: Optional[MotionController] = None


def install_motion(app, duration: int = DURATION) -> Optional[MotionController]:
    """安装过渡动画层（幂等）。"""
    global _CONTROLLER
    if _CONTROLLER is not None:
        return _CONTROLLER
    try:
        _CONTROLLER = MotionController(app, duration)
        app.installEventFilter(_CONTROLLER)
    except Exception:
        _CONTROLLER = None
    return _CONTROLLER


def installed() -> Optional[MotionController]:
    return _CONTROLLER


def uninstall_motion(app=None):
    """卸载（测试用：验证"无动画层时逐像素不变"）。"""
    global _CONTROLLER
    if app is None:
        try:
            from src.core.qt_compat.QtWidgets import QApplication
            app = QApplication.instance()
        except Exception:
            app = None
    c = _CONTROLLER
    _CONTROLLER = None
    if c is not None:
        c.stop_all()
        if app is not None:
            try:
                app.removeEventFilter(c)
            except Exception:
                pass
    return c
