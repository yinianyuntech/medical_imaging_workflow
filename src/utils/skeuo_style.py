#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""skeuo_style —— 三维拟物化绘制引擎（QProxyStyle）。

为什么不能只用 QSS：
  Qt 样式表**不支持** box-shadow / inset / 多层渐变叠加 / 镜面高光，
  只能画出"平面渐变 + 描边"。真正的三维观感需要**手绘**：
      受光面 → 倒角挤出 → 镜面高光 → 内阴影 → 投射阴影。

本模块用 `QProxyStyle` 覆盖若干 **primitive**，在控件自身矩形内绘制，
因此**完全不改变任何布局**（不需要 border-width，不动 padding）。

覆盖的 primitive：
    PE_PanelButtonCommand  QPushButton 立体按钮（含按下/悬停/禁用）
    PE_PanelLineEdit       QLineEdit 等内凹井
    PE_FrameLineEdit       同上（部分平台走 Frame）
    PE_FrameGroupBox       分组面板立体板

注意：若某个控件自身设置了样式表（如语义色按钮 #4CAF50），
QStyleSheetStyle 会接管其背景绘制，本引擎自动让位 —— 语义色天然保留。
"""

from __future__ import annotations

import re
from typing import Optional

from src.core.qt_compat.QtCore import QPointF, QRectF, Qt
from src.core.qt_compat.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
)
from src.core.qt_compat.QtWidgets import QProxyStyle, QStyle

# ---------------------------------------------------------------- 光照参数

LIGHT_DIR = (-0.55, -0.83)   # 主光来自左上
SPECULAR = 150               # 镜面高强度
EDGE_LIGHT = 120             # 上/左棱线亮度
EDGE_DARK = 170              # 下/右棱线暗度


# ---------------------------------------------------------------- 工具

def _rounded(rect: QRectF, r: float) -> QPainterPath:
    p = QPainterPath()
    p.addRoundedRect(rect, r, r)
    return p


def _rgba(r: int, g: int, b: int, a: int) -> QColor:
    c = QColor(r, g, b)
    c.setAlpha(max(0, min(255, a)))
    return c


def _lerp(c1: QColor, c2: QColor, t: float) -> QColor:
    return QColor(
        int(c1.red() + (c2.red() - c1.red()) * t),
        int(c1.green() + (c2.green() - c1.green()) * t),
        int(c1.blue() + (c2.blue() - c1.blue()) * t),
    )


def _lighten(c: QColor, amt: int) -> QColor:
    return QColor(min(255, c.red() + amt), min(255, c.green() + amt), min(255, c.blue() + amt))


def _darken(c: QColor, amt: int) -> QColor:
    return QColor(max(0, c.red() - amt), max(0, c.green() - amt), max(0, c.blue() - amt))


def _lighter_a(c: QColor, amt: int) -> QColor:
    """提亮但**保留 alpha**（玻璃填充必须保持半透明）。"""
    return QColor(min(255, c.red() + amt), min(255, c.green() + amt),
                  min(255, c.blue() + amt), c.alpha())


def _darker_a(c: QColor, amt: int) -> QColor:
    """压暗但**保留 alpha**。"""
    return QColor(max(0, c.red() - amt), max(0, c.green() - amt),
                  max(0, c.blue() - amt), c.alpha())


def _shadow_rgb(t: dict, light_rgb=(0, 3, 10)) -> tuple:
    """共享阴影基色入口（两主题同用原值；鎏金底材已回退为冷蓝金属）。"""
    return tuple(light_rgb)


def _with_alpha(c: QColor, a: int) -> QColor:
    return QColor(c.red(), c.green(), c.blue(), max(0, min(255, a)))


# ---------------------------------------------------------------- 主题取色

# ---------------------------------------------------------------- 材质贴图（颗粒）

_TEX_CACHE: dict = {}


def _texture(kind: str):
    """取**磨砂玻璃**颗粒位图（各向同性，可平铺）。

    缓存键含**主题名** —— 否则切换深浅色后仍会复用上一主题的颗粒贴图
    （实测踩过：热切换后颗粒不跟主题变）。
    """
    try:
        from src.utils.skeuomorphic import current_palette
        theme = current_palette().name
    except Exception:
        theme = "dark"
    key = f"{kind}:{theme}"
    if key in _TEX_CACHE:
        return _TEX_CACHE[key]
    pm = None
    try:
        from src.utils.skeuomorphic import frost_pixmap
        pm = frost_pixmap(128, 128)
    except Exception:
        pm = None
    _TEX_CACHE[key] = pm
    return pm


def reset_texture_cache() -> None:
    """主题切换时调用：清空颗粒贴图缓存。"""
    _TEX_CACHE.clear()


def _overlay_texture(painter: QPainter, path: QPainterPath, kind: str,
                     origin: QPointF, opacity: float = 0.85) -> None:
    """把颗粒材质以纹理笔刷叠到已填充的路径上。"""
    pm = _texture(kind)
    if pm is None:
        return
    try:
        painter.save()
        painter.setClipPath(path)
        painter.setOpacity(opacity)
        brush = QBrush(pm)
        brush.setStyle(Qt.BrushStyle.TexturePattern)
        brush.setTransform(brush.transform().translate(origin.x(), origin.y()))
        painter.fillPath(path, brush)
        painter.restore()
    except Exception:
        try:
            painter.restore()
        except Exception:
            pass


def _stroke_bevel(painter: QPainter, path: QPainterPath, rect: QRectF,
                  edge_color: QColor, disabled: bool = False,
                  light_extra: int = 0, dark: bool = True) -> None:
    """用"上下半区裁剪 + 整路径描边"画倒角。

    比 drawArc 稳健得多：drawArc 画的是**整椭圆弧**，在宽扁控件上会变成巨大弧线
    （曾导致按钮渲染成透镜形）。

    亮/暗端颜色**随主题切换**：深色主题用冷蓝白 + 近黑；
    浅色主题用纯白高光 + 蓝灰投影（否则浅色下倒角会糊成一片）。
    """
    if dark:
        top_col = _rgba(210, 235, 255, (60 if disabled else EDGE_LIGHT) + light_extra)
        bot_col = _rgba(0, 3, 10, EDGE_DARK)
    else:
        # 液态玻璃：镜面棱更亮（白），并保留冷蓝背光棱
        top_col = _rgba(255, 255, 255, (128 if disabled else 236) + min(19, light_extra))
        bot_col = _rgba(96, 126, 166, 138)
    half = rect.height() * 0.5
    # 上半：受光棱线
    painter.save()
    painter.setClipRect(QRectF(rect.left() - 1, rect.top() - 1,
                               rect.width() + 2, half + 1.5))
    painter.setPen(QPen(top_col, 1.2))
    painter.drawPath(path)
    painter.restore()
    # 下半：背光棱线
    painter.save()
    painter.setClipRect(QRectF(rect.left() - 1, rect.top() + half - 1.5,
                               rect.width() + 2, half + 2))
    painter.setPen(QPen(bot_col, 1.2))
    painter.drawPath(path)
    painter.restore()
    # 外轮廓（统一收边，避免锯齿）
    painter.setPen(QPen(edge_color, 1.0))
    painter.drawPath(path)


def _parse_rgba(s: str) -> QColor:
    """解析 'rgba(r,g,b,a)'（a 为 0~1 浮点）与 '#RRGGBB'。"""
    try:
        t = str(s).strip()
        if t.lower().startswith("rgba("):
            body = t[t.index("(") + 1: t.rindex(")")]
            parts = [x.strip() for x in body.split(",")]
            r, g, b = int(float(parts[0])), int(float(parts[1])), int(float(parts[2]))
            a = float(parts[3])
            c = QColor(r, g, b)
            c.setAlpha(int(max(0.0, min(1.0, a)) * 255))
            return c
        return QColor(t)
    except Exception:
        return QColor(128, 128, 128, 128)


_SEMANTIC_RE = re.compile(r"background(?:-color)?\s*:\s*(#[0-9A-Fa-f]{6})")


def _semantic_base(widget) -> Optional[QColor]:
    """从控件样式表取**语义底色**（成功绿/危险红/警告橙）。

    为什么必须由引擎读取：引擎绘制的玻璃会**覆盖**控件自身的 `background-color`
    （实测：`Validate All` 的 `#2E7D32` 被画成浅灰玻璃）。所以语义色要在引擎里画。
    只有"被保留下来"的样式表才会走到这里 —— 浅色/深色遗留色都已被 strip 清掉。
    """
    try:
        ss = widget.styleSheet() if widget is not None else ""
    except Exception:
        return None
    if not ss:
        return None
    m = _SEMANTIC_RE.search(ss)
    if not m:
        return None
    c = QColor(m.group(1))
    return c if c.isValid() else None


def _motion_state(option, widget):
    """(是否画悬停, 悬停强度 0..1)。

    有动画层时**以动画属性门控**，而不是以 `State_MouseOver` 门控 ——
    离开控件时 Qt 会**立刻**清掉 `State_MouseOver`，若用 state 位门控，
    离场动画根本没有插值机会、会"啪"地跳回去（比不做动画更难看）。
    详见 `src/utils/skeuo_motion.py`。
    """
    try:
        from src.utils.skeuo_motion import motion, PROP_HOVER
        k = motion(widget, PROP_HOVER)
    except Exception:
        k = None
    if k is not None:
        return (k > 0.002), k
    hov = bool(option.state & QStyle.StateFlag.State_MouseOver)
    return hov, (1.0 if hov else 0.0)


def _focus_state(option, widget):
    """(是否画焦点环, 焦点强度 0..1)。无动画层时退化为读 `State_HasFocus`。"""
    try:
        from src.utils.skeuo_motion import motion, PROP_FOCUS
        k = motion(widget, PROP_FOCUS)
    except Exception:
        k = None
    if k is not None:
        return (k > 0.002), k
    has = bool(option.state & QStyle.StateFlag.State_HasFocus)
    return has, (1.0 if has else 0.0)


def _theme_colors():
    """从当前皮肤取色：**玻璃令牌** + 少量色阶（用于文字/描边）。"""
    try:
        from src.utils.skeuomorphic import current_palette
        p = current_palette()
        return {
            "dark": p.name == "dark",
            "glass_hi": _parse_rgba(p.glass_hi),
            "glass_lo": _parse_rgba(p.glass_lo),
            "glass_rim": _parse_rgba(p.glass_rim),
            "glass_edge": _parse_rgba(p.glass_edge),
            "glass_shadow": _parse_rgba(p.glass_shadow),
            "raise_top": QColor(p.s400),
            "raise_mid": QColor(p.s500),
            "raise_bot": QColor(p.s700),
            "well_top": QColor(p.s900),
            "well_bot": QColor(p.s700),
            "panel_top": QColor(p.s600),
            "panel_bot": QColor(p.s800),
            "edge": QColor(p.s900),
            "accent": QColor(p.accent),
            "accent_hi": QColor(p.accent_hi),
            "text": QColor(p.text),
            "disabled_bg": QColor(p.s700),
            "disabled_text": QColor(p.text_dim),
        }
    except Exception:
        return {
            "dark": True,
            "glass_hi": QColor(30, 58, 104, 158),
            "glass_lo": QColor(10, 22, 44, 178),
            "glass_rim": QColor(200, 232, 255, 108),
            "glass_edge": QColor(0, 8, 22, 184),
            "glass_shadow": QColor(0, 3, 12, 128),
            "raise_top": QColor("#1F3A5F"), "raise_mid": QColor("#182F4E"),
            "raise_bot": QColor("#0B1524"),
            "well_top": QColor("#04070E"), "well_bot": QColor("#0B1524"),
            "panel_top": QColor("#112036"), "panel_bot": QColor("#070D18"),
            "edge": QColor("#04070E"),
            "accent": QColor("#D9A62E"), "accent_hi": QColor("#F3CB5A"),
            "text": QColor("#D8E6FA"),
            "disabled_bg": QColor("#0B1524"), "disabled_text": QColor("#8296B5"),
        }


# ================================================================ 绘制引擎

class SkeuoPainter:
    """把"平面矩形"画成"三维立体件"。"""

    # ------------------------------------------------ 凸起件（按钮）

    @staticmethod
    def paint_raised(painter: QPainter, rect: QRectF, radius: float,
                     raised: bool = True, disabled: bool = False,
                     hovered: bool = False, sunken: bool = False,
                     accent: bool = False, base: Optional[QColor] = None,
                     hover_k: float = 1.0) -> None:
        """绘制带投光、倒角、镜面高光的立体凸起件。

        `base` 非空时用该色作为基色（**语义色按钮**：成功绿/危险红/警告橙），
        否则用玻璃令牌。语义色必须由引擎自己画 —— 实测控件样式表的
        `background-color` 会被引擎的玻璃覆盖，导致渲染成浅灰底白字。

        `hover_k` 是悬停**强度**（0..1，来自过渡动画）：`hovered` 决定走不走
        悬停分支，`hover_k` 决定提亮多少。`hover_k=0` 必须逐像素等于不悬停
        —— 否则动画首帧会跳变（见 `skeuo_motion.py`）。
        """
        k = 1.0 if hover_k is None else max(0.0, min(1.0, float(hover_k)))
        t = _theme_colors()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        inset = 1.0
        r = rect.adjusted(inset, inset, -inset, -inset)
        if r.width() <= 2 or r.height() <= 2:
            painter.restore()
            return

        top = t["raise_top"]
        mid = t["raise_mid"]
        bot = t["raise_bot"]
        if disabled:
            top = _lerp(top, t["disabled_bg"], 0.7)
            mid = _lerp(mid, t["disabled_bg"], 0.7)
            bot = _lerp(bot, t["disabled_bg"], 0.7)
        if hovered and not disabled and k > 0.0:
            top = _lighten(top, int(14 * k))
            mid = _lighten(mid, int(12 * k))
            bot = _lighten(bot, int(10 * k))

        body = r
        # ---- 1) 投射阴影（多层，越近越深）→ 立体悬浮感
        #     深色主题：近黑阴影；液态玻璃（浅色）：**冷蓝灰柔影**——
        #     黑色投影落在亮玻璃上会"发脏"，冷蓝灰才像光被玻璃折射后投下。
        if raised and not sunken:
            if t["dark"]:
                layers = ((3.5, 34), (2.0, 52), (1.0, 74))
                sh_col = (0, 3, 10)
            else:
                layers = ((4.5, 16), (2.4, 28), (1.1, 44))
                sh_col = (84, 114, 164)
            for dy, a in layers:
                sh = body.translated(0, dy)
                painter.fillPath(_rounded(sh, radius), _rgba(sh_col[0], sh_col[1], sh_col[2], a))
        # ---- 2) 挤出侧面（按下时压扁，凸起时露出下沿）
        #
        # ⚠️ 顺序陷阱：侧壁必须**画在面部之上**并裁剪进面部路径（见下方 3b）。
        #    原实现把 side 与 face 放在同一位置（都 `translated(0, depth)`），
        #    两矩形完全相同 → 面把侧壁 100% 覆盖，3D 厚度形同虚设；
        #    连带 hover 对 `bot`（侧壁色）的提亮也变成"像素差 0"，交互零反馈。
        depth = 0.0 if sunken else 2.0

        face = body.translated(0, 1.0 if sunken else 0.0)

        # ---- 3) 受光面：**半透明玻璃**渐变（顶部受光更亮，底部更透）
        #     语义色按钮则用其基色做明暗（保留 3D 倒角）
        if base is not None:
            # 语义色按钮：提亮幅度必须很小。白字压在语义色上，
            # 实测 +34 → 3.23:1、+12 → 4.29:1、+6 → 4.72:1（达标）。
            gh = _with_alpha(_lighter_a(base, 6), 255)
            gl = _with_alpha(_darker_a(base, 28), 255)
            if disabled:
                gh = _lerp(gh, QColor(t["disabled_bg"]), 0.55)
                gl = _lerp(gl, QColor(t["disabled_bg"]), 0.55)
            elif hovered:
                gh = _lighter_a(gh, int(10 * k))
                gl = _lighter_a(gl, int(6 * k))
        else:
            gh, gl = t["glass_hi"], t["glass_lo"]
            if disabled:
                gh = _with_alpha(gh, int(gh.alpha() * 0.40))
                gl = _with_alpha(gl, int(gl.alpha() * 0.40))
            elif hovered:
                # 悬停提亮必须落在 **gh/gl** 上 —— 这两个才是真正画面部的变量。
                # （只提亮 top/mid 是死代码：它们从未参与面部渐变。）
                gh = _lighter_a(gh, int(34 * k))
                gl = _lighter_a(gl, int(26 * k))
        g = QLinearGradient(0, face.top(), 0, face.bottom())
        if not sunken:
            g.setColorAt(0.00, _lighter_a(gh, 24))
            g.setColorAt(0.40, gh)
            g.setColorAt(0.72, gl)
            g.setColorAt(1.00, _darker_a(gl, 8))
        else:
            g.setColorAt(0.00, _darker_a(gl, 6))
            g.setColorAt(0.45, gh)
            g.setColorAt(1.00, _lighter_a(gh, 10))
        path = _rounded(face, radius)
        painter.fillPath(path, QBrush(g))
        if base is None:
            _overlay_texture(painter, path, "glass", face.topLeft(), 0.55)

        # ---- 3b) 挤出下沿：贴底窄带，**画在面部之上**才能看见
        #          （画在下面会被面部完整覆盖 —— 这正是原来 3D 厚度不可见的原因）
        if depth > 0:
            painter.save()
            painter.setClipPath(path)
            band = QRectF(face.left(), face.bottom() - depth, face.width(), depth)
            g_side = QLinearGradient(0, band.top(), 0, band.bottom())
            g_side.setColorAt(0.0, _darken(bot, 6))
            g_side.setColorAt(1.0, _rgba(*_shadow_rgb(t), 205))
            painter.fillRect(band, QBrush(g_side))
            painter.restore()

        # ---- 4) 镜面高光：贴顶窄带（过强会洗掉金属蓝，显得发灰）
        #     语义色按钮跳过：白字压在语义色上，再加高光会直接掉到 4.5:1 以下
        #     液态玻璃（浅色）：更亮的"凝胶盖"白高光 —— 玻璃的标志性受光
        if not sunken and not disabled and base is None:
            painter.save()
            painter.setClipPath(path)
            if t["dark"]:
                band_h = max(3.0, face.height() * 0.30)
                a1 = 72 + int(44 * k if hovered else 0)
                a2 = 30 + int(22 * k if hovered else 0)
                c1, c2 = (215, 240, 255), (160, 205, 255)
            else:
                band_h = max(3.0, face.height() * 0.44)
                a1 = 112 + int(40 * k if hovered else 0)
                a2 = 46 + int(24 * k if hovered else 0)
                c1, c2 = (255, 255, 255), (222, 240, 255)
            sp = QLinearGradient(0, face.top(), 0, face.top() + band_h)
            sp.setColorAt(0.00, _rgba(c1[0], c1[1], c1[2], a1))
            sp.setColorAt(0.45, _rgba(c2[0], c2[1], c2[2], a2))
            sp.setColorAt(1.00, _rgba(255, 255, 255, 0))
            painter.fillRect(QRectF(face.left(), face.top(), face.width(), band_h), QBrush(sp))
            painter.restore()

        # ---- 5) 内凹时：顶部内阴影（光被"井"挡住）
        if sunken:
            painter.save()
            painter.setClipPath(path)
            h = max(6.0, face.height() * 0.55)
            ig = QLinearGradient(0, face.top(), 0, face.top() + h)
            ig.setColorAt(0.0, _rgba(*_shadow_rgb(t, (0, 2, 8)), 170))
            ig.setColorAt(1.0, _rgba(0, 2, 8, 0))
            painter.fillRect(QRectF(face.left(), face.top(), face.width(), h), QBrush(ig))
            painter.restore()

        # ---- 6) 棱线：上/左受光、下/右背光（倒角）
        #     悬停时棱线加亮 → 金属"边缘受光"的直觉反馈
        _stroke_bevel(painter, _rounded(face, radius), face, t["edge"],
                      disabled=disabled, dark=t["dark"],
                      light_extra=int(30 * k) if (hovered and not disabled) else 0)
        if accent:
            painter.save()
            painter.setClipRect(QRectF(face.left() - 1, face.top() - 1,
                                       face.width() + 2, face.height() * 0.5 + 1.5))
            painter.setPen(QPen(t["accent_hi"], 1.4))
            painter.drawPath(_rounded(face, radius))
            painter.restore()

        painter.restore()

    # ------------------------------------------------ 内凹件（输入井）

    @staticmethod
    def paint_well(painter: QPainter, rect: QRectF, radius: float,
                   hovered: bool = False, disabled: bool = False,
                   hover_k: float = 1.0) -> None:
        """绘制内凹井：顶上暗、底沿受光（光线从左上射入）。

        `hovered` / `disabled` **必须在这里处理** —— 输入框/下拉框/滑杆槽的主体
        就是这个井，只在边框上做文章状态变化测不出来（实测 hover 像素差 = 0）。
        `hover_k` 是悬停强度（0..1，过渡动画用）。

        ⚠️ 井底是**半透明**填充，改色只能用 `_lighter_a` / `_darker_a` / `_with_alpha`；
           `_lighten` / `_lerp` 返回 3 参数 QColor（**alpha 丢失**）→ 玻璃立刻变不透明。
        """
        k = 1.0 if hover_k is None else max(0.0, min(1.0, float(hover_k)))
        t = _theme_colors()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        r = rect.adjusted(0.5, 0.5, -0.5, -0.5)
        if r.width() <= 2 or r.height() <= 2:
            painter.restore()
            return
        path = _rounded(r, radius)

        # 1) 井底：**磨砂玻璃内凹**（更暗更透）
        if t["dark"]:
            c_top = _with_alpha(QColor(0, 8, 24), 150)
            c_bot = _with_alpha(QColor(16, 40, 84), 92)
        else:
            # 液态玻璃：顶部淡冷蓝 → 底部近白（玻璃井底的透光感）
            c_top = QColor(132, 162, 204, 100)
            c_bot = QColor(255, 255, 255, 172)
        if disabled:
            # 禁用：压平"深井"层次（顶/底都提亮、拉近）→ 与可用态一眼可分
            c_top = _with_alpha(_lighter_a(c_top, 36), 118)
            c_bot = _with_alpha(_lighter_a(c_bot, 20), 106)
        elif hovered:
            # 悬停：井底整体"被照亮"（按强度插值）
            c_top = _lighter_a(c_top, int(30 * k))
            c_bot = _lighter_a(c_bot, int(26 * k))
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0.0, c_top)
        g.setColorAt(1.0, c_bot)
        painter.fillPath(path, QBrush(g))
        _overlay_texture(painter, path, "glass", r.topLeft(), 0.42 if t["dark"] else 0.26)

        # 2) 顶部内阴影（深度感来源）
        painter.save()
        painter.setClipPath(path)
        h = max(5.0, r.height() * 0.6)
        ig = QLinearGradient(0, r.top(), 0, r.top() + h)
        if t["dark"]:
            if disabled:
                ig.setColorAt(0.0, _rgba(0, 2, 8, 92))
                ig.setColorAt(0.55, _rgba(0, 2, 8, 28))
            else:
                ig.setColorAt(0.0, _rgba(0, 2, 8, 185))
                ig.setColorAt(0.55, _rgba(0, 2, 8, 60))
        else:
            # 液态玻璃：冷蓝内阴影（纯黑会在亮玻璃上发脏）
            if disabled:
                ig.setColorAt(0.0, _rgba(70, 98, 142, 72))
                ig.setColorAt(0.55, _rgba(70, 98, 142, 22))
            else:
                ig.setColorAt(0.0, _rgba(64, 92, 138, 150))
                ig.setColorAt(0.55, _rgba(64, 92, 138, 48))
        ig.setColorAt(1.0, _rgba(0, 2, 8, 0))
        painter.fillRect(QRectF(r.left(), r.top(), r.width(), h), QBrush(ig))
        # 3) 底沿反光（下唇受光）
        lip_rgb = (150, 205, 255) if t["dark"] else (255, 255, 255)
        lip = QLinearGradient(0, r.bottom() - 3, 0, r.bottom())
        lip.setColorAt(0.0, _rgba(lip_rgb[0], lip_rgb[1], lip_rgb[2], 0))
        lip.setColorAt(1.0, _rgba(lip_rgb[0], lip_rgb[1], lip_rgb[2],
                                  58 if disabled else
                                  (95 + int(55 * k) if hovered else 95)))
        painter.fillRect(QRectF(r.left(), r.bottom() - 3, r.width(), 3), QBrush(lip))
        painter.restore()

        # 4) 边框：顶暗、底亮（内凹 = 光线被井口挡住，下唇受光）
        _stroke_bevel(painter, path, r, t["edge"],
                      disabled=disabled,
                      light_extra=-40 + (int(34 * k) if (hovered and not disabled) else 0),
                      dark=t["dark"])

        painter.restore()

    # ------------------------------------------------ 立体面板（分组框）

    @staticmethod
    def paint_panel(painter: QPainter, rect: QRectF, radius: float) -> None:
        """绘制立体金属板：投影 + 受光面 + 内高光/内阴影 + 倒角棱线。"""
        t = _theme_colors()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        r = rect.adjusted(1.0, 1.0, -1.0, -1.0)
        if r.width() <= 4 or r.height() <= 4:
            painter.restore()
            return
        path = _rounded(r, radius)

        # 1) 投影：液态玻璃（浅色）用冷蓝灰柔影 + 更大扩散；深色维持近黑
        if t["dark"]:
            for dy, a in ((4.0, 30), (2.0, 44), (1.0, 60)):
                painter.fillPath(_rounded(r.translated(0, dy), radius), _rgba(0, 3, 10, a))
        else:
            for dy, a in ((5.0, 14), (2.6, 24), (1.2, 36)):
                painter.fillPath(_rounded(r.translated(0, dy), radius), _rgba(84, 114, 164, a))

        # 2) 受光面：**玻璃板**（半透明 + 顶部更亮）
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0.00, _lighter_a(t["glass_hi"], 20))
        g.setColorAt(0.26, t["glass_hi"])
        g.setColorAt(0.72, t["glass_lo"])
        g.setColorAt(1.00, _darker_a(t["glass_lo"], 6))
        painter.fillPath(path, QBrush(g))
        _overlay_texture(painter, path, "glass", r.topLeft(), 0.50 if t["dark"] else 0.30)

        # 3) 顶部内高光（薄板受光的上沿）
        painter.save()
        painter.setClipPath(path)
        if t["dark"]:
            hl_col, hl_h, hl_a = (170, 215, 255), max(10.0, r.height() * 0.06), 62
            sh_col, sh_h, sh_a = (0, 3, 10), 8.0, 110
        else:
            # 液态玻璃：镜面白的内沿高光更亮更高（"玻璃厚度"的受光棱）
            hl_col, hl_h, hl_a = (255, 255, 255), max(12.0, r.height() * 0.09), 132
            sh_col, sh_h, sh_a = (96, 128, 176), 10.0, 54
        hl = QLinearGradient(0, r.top(), 0, r.top() + hl_h)
        hl.setColorAt(0.0, _rgba(hl_col[0], hl_col[1], hl_col[2], hl_a))
        hl.setColorAt(1.0, _rgba(hl_col[0], hl_col[1], hl_col[2], 0))
        painter.fillRect(QRectF(r.left(), r.top(), r.width(), hl_h), QBrush(hl))
        # 底部内阴影（板厚）
        sh = QLinearGradient(0, r.bottom() - sh_h, 0, r.bottom())
        sh.setColorAt(0.0, _rgba(sh_col[0], sh_col[1], sh_col[2], 0))
        sh.setColorAt(1.0, _rgba(sh_col[0], sh_col[1], sh_col[2], sh_a))
        painter.fillRect(QRectF(r.left(), r.bottom() - sh_h, r.width(), sh_h), QBrush(sh))
        # 玻璃"受光点"：左上柔光斑（液态玻璃的标志 —— 光源在玻璃面上的漫反射）
        if not t["dark"] and r.width() > 80 and r.height() > 50:
            spot = QRadialGradient(
                QPointF(r.left() + r.width() * 0.16, r.top() + r.height() * 0.02),
                max(r.width() * 0.34, 90.0),
            )
            spot.setColorAt(0.0, _rgba(255, 255, 255, 88))
            spot.setColorAt(0.55, _rgba(255, 255, 255, 26))
            spot.setColorAt(1.0, _rgba(255, 255, 255, 0))
            painter.fillPath(path, QBrush(spot))
        painter.restore()

        # 4) 棱线：上亮下暗
        _stroke_bevel(painter, path, r, t["edge"], dark=t["dark"])

        painter.restore()


    # ------------------------------------------------ 薄板（表头/标签页）

    @staticmethod
    def paint_slab(painter: QPainter, rect: QRectF, radius: float = 4.0,
                   raised: bool = True, accent_top: bool = False,
                   dim: bool = False, hovered: bool = False,
                   hover_k: float = 1.0) -> None:
        """绘制"薄金属板"：表头单元格 / 标签页卡舌。

        与 paint_raised 的区别：**不画投射阴影**（避免与相邻单元格互相压盖），
        只用受光面 + 倒角棱线表达立体。
        """
        t = _theme_colors()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        r = rect.adjusted(0.5, 0.5, -0.5, -0.5)
        if r.width() <= 2 or r.height() <= 2:
            painter.restore()
            return
        path = _rounded(r, radius)

        gh, gl = t["glass_hi"], t["glass_lo"]
        if dim:
            gh = _with_alpha(gh, int(gh.alpha() * 0.45))
            gl = _with_alpha(gl, int(gl.alpha() * 0.45))
        elif hovered and raised:
            # 悬停：薄板整体受光增强（表头"可点击排序"的可用性提示）
            k = 1.0 if hover_k is None else max(0.0, min(1.0, float(hover_k)))
            gh = _lighter_a(gh, int(30 * k))
            gl = _lighter_a(gl, int(22 * k))

        g = QLinearGradient(0, r.top(), 0, r.bottom())
        if raised:
            g.setColorAt(0.00, _lighter_a(gh, 18))
            g.setColorAt(0.45, gh)
            g.setColorAt(1.00, gl)
        else:
            g.setColorAt(0.00, _with_alpha(QColor(0, 8, 24), 132))
            g.setColorAt(1.00, _with_alpha(gh, 34))
        painter.fillPath(path, QBrush(g))
        _overlay_texture(painter, path, "glass", r.topLeft(), 0.40)

        if accent_top:
            painter.save()
            painter.setClipRect(QRectF(r.left() - 1, r.top() - 1, r.width() + 2, 3))
            painter.setPen(QPen(t["accent_hi"], 2.0))
            painter.drawPath(path)
            painter.restore()

        _stroke_bevel(painter, path, r, t["edge"], dark=t["dark"],
                      light_extra=int(26 * (1.0 if hover_k is None else hover_k))
                      if (hovered and raised) else 0)
        painter.restore()

    # ------------------------------------------------ 键盘焦点环

    @staticmethod
    def paint_focus_ring(painter: QPainter, rect: QRectF, radius: float,
                         k: float = 1.0, inset: float = 1.2,
                         ellipse: bool = False) -> None:
        """键盘焦点环：贴边内缩的电光蓝主环 + 外侧柔和光晕。

        为什么画在控件**内部**：画在外面会被父容器裁掉，或与相邻控件互相压盖
        （本项目最硬的一条约束就是"所有显示 block 没有遮挡"）。

        可访问性理由：`line` 原本靠全局 QSS 的 `:focus { border }` 拿到焦点反馈，
        而 `combo` / `check` / `radio` / `slider` **完全没有** —— 键盘用户看不出
        焦点在哪。统一由引擎画才能跨控件一致，并且跟随主题热切换。

        `ellipse=True` 用于圆形控件（滑杆手柄）—— 给圆钮套方框会很难看。
        `k` 为过渡进度（0..1）：0 表示完全不画。
        """
        if k is None or k <= 0.002:
            return
        kk = max(0.0, min(1.0, float(k)))
        t = _theme_colors()
        a = t["accent_hi"]

        def shape(rr: QRectF, rad: float):
            if ellipse:
                p = QPainterPath()
                p.addEllipse(rr)
                return p
            return _rounded(rr, max(2.0, rad))

        r = QRectF(rect)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        # 外侧光晕（两圈，越外越淡）
        for off, alpha in ((2.8, 46), (1.8, 92)):
            g = r.adjusted(off, off, -off, -off)
            if g.width() <= 5 or g.height() <= 5:
                continue
            painter.setPen(QPen(_rgba(a.red(), a.green(), a.blue(),
                                      int(alpha * kk)), 1.5))
            painter.drawPath(shape(g, radius - off))
        # 主环
        inner = r.adjusted(inset, inset, -inset, -inset)
        if inner.width() > 5 and inner.height() > 5:
            painter.setPen(QPen(_rgba(a.red(), a.green(), a.blue(),
                                      int(242 * kk)), 1.9))
            painter.drawPath(shape(inner, radius - inset))
        painter.restore()

    # ------------------------------------------------ 内凹井（勾选框）

    @staticmethod
    def paint_check(painter: QPainter, rect: QRectF, radius: float,
                    state_on: bool, state_partial: bool = False,
                    hovered: bool = False, disabled: bool = False,
                    hover_k: float = 1.0) -> None:
        """复选框：内凹井 + 立体勾（勾本身带高光/阴影，看起来是"嵌进去的金属件"）。"""
        k = 1.0 if hover_k is None else max(0.0, min(1.0, float(hover_k)))
        t = _theme_colors()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        r = rect.adjusted(0.5, 0.5, -0.5, -0.5)
        if r.width() <= 3 or r.height() <= 3:
            painter.restore()
            return
        path = _rounded(r, radius)

        # 井（磨砂玻璃内凹）—— 半透明填充，只能用 alpha 保留型辅助函数
        if t["dark"]:
            c_top = _with_alpha(QColor(0, 8, 24), 150)
            c_bot = _with_alpha(QColor(16, 40, 84), 92)
        else:
            c_top = QColor(120, 150, 190, 96)
            c_bot = QColor(240, 248, 255, 150)
        if disabled:
            c_top = _with_alpha(_lighter_a(c_top, 36), 118)
            c_bot = _with_alpha(_lighter_a(c_bot, 20), 106)
        elif hovered:
            c_top = _lighter_a(c_top, int(30 * k))
            c_bot = _lighter_a(c_bot, int(26 * k))
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0.0, c_top)
        g.setColorAt(1.0, c_bot)
        painter.fillPath(path, QBrush(g))
        _overlay_texture(painter, path, "glass", r.topLeft(), 0.38)
        painter.save()
        painter.setClipPath(path)
        h = r.height() * 0.6
        ig = QLinearGradient(0, r.top(), 0, r.top() + h)
        ig.setColorAt(0.0, _rgba(*_shadow_rgb(t, (0, 2, 8)), 96 if disabled else 190))
        ig.setColorAt(1.0, _rgba(0, 2, 8, 0))
        painter.fillRect(QRectF(r.left(), r.top(), r.width(), h), QBrush(ig))
        painter.restore()
        _stroke_bevel(painter, path, r, t["edge"],
                      disabled=disabled,
                      light_extra=-45 + (int(34 * k) if (hovered and not disabled) else 0),
                      dark=t["dark"])

        if state_on or state_partial:
            # 禁用态用灰标记色，避免"看着可用但点不动"
            mark = t["disabled_text"] if disabled else t["accent_hi"]
            cx, cy = r.center().x(), r.center().y()
            painter.setRenderHint(QPainter.Antialiasing, True)
            if state_partial:
                pen = QPen(mark, max(2.0, r.height() * 0.22),
                           Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(QPointF(r.left() + r.width() * 0.24, cy),
                                 QPointF(r.right() - r.width() * 0.24, cy))
            else:
                pen = QPen(mark, max(2.0, r.height() * 0.20),
                           Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                           Qt.PenJoinStyle.RoundJoin)
                # 先画暗色描边（下沉感），再画亮色勾
                shadow = QPainterPath()
                shadow.moveTo(r.left() + r.width() * 0.24, cy + r.height() * 0.04)
                shadow.lineTo(r.left() + r.width() * 0.43, r.bottom() - r.height() * 0.26)
                shadow.lineTo(r.right() - r.width() * 0.22, r.top() + r.height() * 0.28)
                painter.setPen(QPen(_rgba(*_shadow_rgb(t), 170),
                                    max(3.0, r.height() * 0.24),
                                    Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                    Qt.PenJoinStyle.RoundJoin))
                painter.drawPath(shadow)
                painter.setPen(pen)
                check = QPainterPath()
                check.moveTo(r.left() + r.width() * 0.24, cy)
                check.lineTo(r.left() + r.width() * 0.43, r.bottom() - r.height() * 0.30)
                check.lineTo(r.right() - r.width() * 0.22, r.top() + r.height() * 0.24)
                painter.drawPath(check)
        painter.restore()

    @staticmethod
    def paint_radio(painter: QPainter, rect: QRectF, state_on: bool,
                    hovered: bool = False, disabled: bool = False,
                    hover_k: float = 1.0) -> None:
        """单选钮：圆形内凹井 + 立体圆点。"""
        k = 1.0 if hover_k is None else max(0.0, min(1.0, float(hover_k)))
        t = _theme_colors()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        r = rect.adjusted(0.5, 0.5, -0.5, -0.5)
        if r.width() <= 3 or r.height() <= 3:
            painter.restore()
            return
        path = QPainterPath()
        path.addEllipse(r)
        if t["dark"]:
            c_top = _with_alpha(QColor(0, 8, 24), 150)
            c_bot = _with_alpha(QColor(16, 40, 84), 92)
        else:
            c_top = QColor(120, 150, 190, 96)
            c_bot = QColor(240, 248, 255, 150)
        if disabled:
            c_top = _with_alpha(_lighter_a(c_top, 36), 118)
            c_bot = _with_alpha(_lighter_a(c_bot, 20), 106)
        elif hovered:
            c_top = _lighter_a(c_top, int(30 * k))
            c_bot = _lighter_a(c_bot, int(26 * k))
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0.0, c_top)
        g.setColorAt(1.0, c_bot)
        painter.fillPath(path, QBrush(g))
        _overlay_texture(painter, path, "glass", r.topLeft(), 0.38)
        painter.save()
        painter.setClipPath(path)
        h = r.height() * 0.6
        ig = QLinearGradient(0, r.top(), 0, r.top() + h)
        ig.setColorAt(0.0, _rgba(*_shadow_rgb(t, (0, 2, 8)), 96 if disabled else 190))
        ig.setColorAt(1.0, _rgba(0, 2, 8, 0))
        painter.fillRect(QRectF(r.left(), r.top(), r.width(), h), QBrush(ig))
        painter.restore()
        _stroke_bevel(painter, path, r, t["edge"],
                      disabled=disabled,
                      light_extra=-45 + (int(34 * k) if (hovered and not disabled) else 0),
                      dark=t["dark"])

        if state_on:
            d = r.adjusted(r.width() * 0.28, r.height() * 0.28,
                           -r.width() * 0.28, -r.height() * 0.28)
            painter.setBrush(QBrush(t["disabled_text"] if disabled else t["accent_hi"]))
            painter.setPen(QPen(_rgba(*_shadow_rgb(t), 170), 1.0))
            painter.drawEllipse(d)
            painter.setPen(QPen(_rgba(255, 255, 255, 120), 1.0))
            painter.drawArc(d, 30 * 16, 150 * 16)
        painter.restore()


# ================================================================ QProxyStyle

class SkeuomorphicStyle(QProxyStyle):
    """把 primitive 绘制接管到三维引擎。"""

    # 调试计数（供探针确认接管是否生效）+ 最近一次异常
    hits = {
        "button": 0, "well": 0, "groupbox": 0,
        "combo": 0, "scroll": 0, "slider": 0,
        "header": 0, "tab": 0, "checkbox": 0, "radio": 0,
    }
    last_error = ""

    def __init__(self, base: str = "Fusion"):
        super().__init__(base)
        self._engine = SkeuoPainter()

    # ------------------------------------------------ primitives

    def drawPrimitive(self, element, option, painter, widget=None):
        E = QStyle.PrimitiveElement
        try:
            if element == E.PE_PanelButtonCommand:
                SkeuomorphicStyle.hits["button"] += 1
                self._button(option, painter, widget)
                return
            if element in (E.PE_PanelLineEdit, E.PE_FrameLineEdit):
                SkeuomorphicStyle.hits["well"] += 1
                self._well(option, painter, widget)
                return
            if element == E.PE_FrameGroupBox:
                SkeuomorphicStyle.hits["groupbox"] += 1
                self._groupbox(option, painter, widget)
                return
            if element == E.PE_IndicatorCheckBox:
                SkeuomorphicStyle.hits["checkbox"] += 1
                self._checkbox(option, painter, widget)
                return
            if element == E.PE_IndicatorRadioButton:
                SkeuomorphicStyle.hits["radio"] += 1
                self._radio(option, painter, widget)
                return
        except Exception:
            import traceback
            SkeuomorphicStyle.last_error = f"[primitive {element}] {traceback.format_exc()}"
        super().drawPrimitive(element, option, painter, widget)

    # ------------------------------------------------ controls

    def drawControl(self, element, option, painter, widget=None):
        C = QStyle.ControlElement
        try:
            if element == C.CE_HeaderSection:
                SkeuomorphicStyle.hits["header"] += 1
                self._header(option, painter, widget)
                return
            if element == C.CE_TabBarTabShape:
                SkeuomorphicStyle.hits["tab"] += 1
                self._tab(option, painter, widget)
                return
        except Exception:
            import traceback
            SkeuomorphicStyle.last_error = f"[control {element}] {traceback.format_exc()}"
        super().drawControl(element, option, painter, widget)

    # ------------------------------------------------ complex controls

    def drawComplexControl(self, cc, option, painter, widget=None):
        C = QStyle.ComplexControl
        try:
            if cc == C.CC_GroupBox:
                self._groupbox(option, painter, widget)
                return
            if cc == C.CC_ComboBox:
                SkeuomorphicStyle.hits["combo"] += 1
                self._combo(option, painter, widget)
                return
            if cc == C.CC_ScrollBar:
                SkeuomorphicStyle.hits["scroll"] += 1
                self._scrollbar(option, painter, widget)
                return
            if cc == C.CC_Slider:
                SkeuomorphicStyle.hits["slider"] += 1
                self._slider(option, painter, widget)
                return
        except Exception:
            import traceback
            SkeuomorphicStyle.last_error = f"[complex {cc}] {traceback.format_exc()}"
        super().drawComplexControl(cc, option, painter, widget)

    # ------------------------------------------------ 新增控件绘制

    def _checkbox(self, option, painter, widget):
        S = QStyle.StateFlag
        on = bool(option.state & S.State_On)
        partial = bool(option.state & S.State_NoChange)
        hovered, hk = _motion_state(option, widget)
        focused, fk = _focus_state(option, widget)
        self._engine.paint_check(painter, QRectF(option.rect), 4.0, on, partial,
                                 hovered=hovered,
                                 disabled=not bool(option.state & S.State_Enabled),
                                 hover_k=hk)
        # 焦点环套整个控件（指示器 + 文字），与 Qt Fusion 的习惯一致
        if fk > 0.002 and widget is not None:
            self._engine.paint_focus_ring(painter, QRectF(widget.rect()), 6.0,
                                          fk, inset=1.0)

    def _radio(self, option, painter, widget):
        S = QStyle.StateFlag
        on = bool(option.state & S.State_On)
        hovered, hk = _motion_state(option, widget)
        focused, fk = _focus_state(option, widget)
        self._engine.paint_radio(painter, QRectF(option.rect), on,
                                 hovered=hovered,
                                 disabled=not bool(option.state & S.State_Enabled),
                                 hover_k=hk)
        if fk > 0.002 and widget is not None:
            self._engine.paint_focus_ring(painter, QRectF(widget.rect()), 8.0,
                                          fk, inset=1.0)

    def _header(self, option, painter, widget):
        S = QStyle.StateFlag
        r = QRectF(option.rect)
        hovered = bool(option.state & S.State_MouseOver)
        pressed = bool(option.state & S.State_Sunken)

        # ⚠️ QHeaderView **不会**把 State_MouseOver 放进 option。
        #    实测：真实光标停在表头上、widget.underMouse() == True，
        #    但绘制时刻 state 位只有 ['Enabled']（QHeaderView 的表头悬停
        #    是由 QStyleSheetStyle 的 :hover 伪状态实现的，不进 style option）。
        #    → 引擎只能自己判定：用真实光标位置反查命中的 section。
        if not hovered and widget is not None:
            try:
                from src.core.qt_compat.QtCore import QPoint as _QP
                from src.core.qt_compat.QtGui import QCursor as _QC
                local = widget.mapFromGlobal(_QC.pos())
                if widget.rect().contains(local):
                    idx = int(widget.logicalIndexAt(local))
                    mine = int(getattr(option, "section", -1))
                    if idx >= 0 and idx == mine:
                        hovered = True
            except Exception:
                pass

        # 表头是"可点击排序"的：悬停提亮、按下下沉 —— 缺了就没有可用性提示
        self._engine.paint_slab(painter, r, 0.0, raised=not pressed,
                                hovered=hovered or pressed)
        # 文字由 CE_HeaderLabel 绘制（不在此接管）

    def _tab(self, option, painter, widget):
        S = QStyle.StateFlag
        selected = bool(option.state & S.State_Selected)
        hovered, hk = _motion_state(option, widget)
        focused, fk = _focus_state(option, widget)
        r = QRectF(option.rect)
        # 选中的卡舌"抬起"并带顶部电光蓝；未选中略沉
        self._engine.paint_slab(painter, r, 6.0, raised=selected,
                                accent_top=selected, dim=not selected and not hovered,
                                hovered=hovered, hover_k=hk)
        # 当前页 + 键盘焦点：给卡舌套焦点环
        if selected and fk > 0.002:
            self._engine.paint_focus_ring(painter, r, 6.0, fk, inset=1.2)

    def _combo(self, option, painter, widget):
        S = QStyle.StateFlag
        r = QRectF(option.rect)
        enabled = bool(option.state & S.State_Enabled)
        hovered, hk = _motion_state(option, widget)
        focused, fk = _focus_state(option, widget)
        self._engine.paint_raised(painter, r, 7.0 if not _theme_colors()["dark"] else 5.0,
                                  raised=True, sunken=False,
                                  hovered=hovered, disabled=not enabled,
                                  hover_k=hk)
        # 键盘焦点环（原来完全没有 —— 键盘用户看不出焦点在下拉框上）
        if fk > 0.002:
            self._engine.paint_focus_ring(painter, r, 7.0 if not _theme_colors()["dark"] else 5.0,
                                          fk, inset=1.2)

        t = _theme_colors()
        editable = bool(getattr(option, "editable", False))
        # 下拉箭头区域
        arrow = None
        try:
            arrow = self.subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                        QStyle.SubControl.SC_ComboBoxArrow, widget)
            arrow = QRectF(arrow)
        except Exception:
            arrow = QRectF(r.right() - 24.0, r.top(), 24.0, r.height())

        if arrow.width() > 4 and arrow.height() > 4:
            # 箭头按钮：小凸起
            self._engine.paint_raised(painter, arrow.adjusted(2.0, 2.0, -2.0, -2.0),
                                      4.0, raised=True, sunken=False,
                                      hovered=hovered, disabled=not enabled,
                                      hover_k=hk)
            cx = arrow.center().x()
            cy = arrow.center().y()
            tri = QPainterPath()
            w, h = max(4.0, arrow.width() * 0.26), max(3.0, arrow.height() * 0.20)
            tri.moveTo(cx - w, cy - h * 0.6)
            tri.lineTo(cx + w, cy - h * 0.6)
            tri.lineTo(cx, cy + h * 0.9)
            tri.closeSubpath()
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(QPen(_rgba(*_shadow_rgb(t), 170), 1.0))
            painter.setBrush(QBrush(t["accent_hi"] if enabled else t["disabled_text"]))
            painter.drawPath(tri)
            painter.restore()

        if editable:
            return  # 可编辑组合框内部有 QLineEdit，文字由它绘制

        # ⚠️ 这里**绝对不能再画文字**。QComboBox::paintEvent 的顺序是：
        #       drawComplexControl(CC_ComboBox, opt)   ← 走到本函数（画壳）
        #       drawControl(CE_ComboBoxLabel, opt)     ← Qt 随后**再画一遍文字**
        #    原来本函数里也 drawText 了一遍 —— 同一串字被错位画了两遍 = **重影**。
        #    文字交给 CE_ComboBoxLabel：它自带省略号处理，而且禁用态会用调色板的
        #    disabled 颜色组，比手绘更准。
        #
        #    至此全引擎**不再手绘任何文字** —— 从结构上消灭"引擎 + Qt 各画一遍"
        #    这一整类重影（表头、标签页、分组框标题也一直是交给 Qt 画的）。

    def _scrollbar(self, option, painter, widget):
        C = QStyle.ComplexControl
        SC = QStyle.SubControl
        S = QStyle.StateFlag
        t = _theme_colors()
        r = QRectF(option.rect)
        if r.width() < 4 or r.height() < 4:
            return

        vertical = True
        try:
            vertical = option.orientation == Qt.Orientation.Vertical
        except Exception:
            vertical = r.height() >= r.width()

        enabled = bool(option.state & S.State_Enabled)
        hovered, hk = _motion_state(option, widget)
        pressed = bool(option.state & S.State_Sunken)
        try:
            over_slider = bool(option.activeSubControls & SC.SC_ScrollBarSlider)
        except Exception:
            over_slider = False

        # 槽：内凹
        self._engine.paint_well(painter, r, 6.0,
                                hovered=hovered, disabled=not enabled,
                                hover_k=hk)

        # 滑块
        try:
            slider = QRectF(self.subControlRect(C.CC_ScrollBar, option,
                                                SC.SC_ScrollBarSlider, widget))
        except Exception:
            slider = QRectF()
        if slider.width() < 2 or slider.height() < 2:
            return
        self._engine.paint_raised(painter, slider, 6.0, raised=True,
                                  hovered=(hovered or over_slider),
                                  sunken=pressed,
                                  disabled=not enabled, hover_k=hk)

    def _slider(self, option, painter, widget):
        C = QStyle.ComplexControl
        SC = QStyle.SubControl
        S = QStyle.StateFlag
        t = _theme_colors()
        enabled = bool(option.state & S.State_Enabled)
        hovered, hk = _motion_state(option, widget)
        focused, fk = _focus_state(option, widget)
        pressed = bool(option.state & S.State_Sunken)
        try:
            groove = QRectF(self.subControlRect(C.CC_Slider, option,
                                                SC.SC_SliderGroove, widget))
            handle = QRectF(self.subControlRect(C.CC_Slider, option,
                                                SC.SC_SliderHandle, widget))
        except Exception:
            return
        if groove.width() < 4 or groove.height() < 2:
            return

        horizontal = True
        try:
            horizontal = option.orientation == Qt.Orientation.Horizontal
        except Exception:
            horizontal = groove.width() >= groove.height()

        # 槽：内凹（中间一条）
        if horizontal:
            gh = min(8.0, groove.height())
            gr = QRectF(groove.left(), groove.center().y() - gh / 2.0, groove.width(), gh)
        else:
            gw = min(8.0, groove.width())
            gr = QRectF(groove.center().x() - gw / 2.0, groove.top(), gw, groove.height())
        self._engine.paint_well(painter, gr, 4.0,
                                hovered=hovered, disabled=not enabled,
                                hover_k=hk)

        # 已填充部分：电光蓝（用 handle 位置反推）
        try:
            span = getattr(option, "maximum", 0) - getattr(option, "minimum", 0)
            val = getattr(option, "sliderPosition", 0) - getattr(option, "minimum", 0)
            frac = (val / span) if span else 0.0
        except Exception:
            frac = 0.0
        frac = max(0.0, min(1.0, frac))
        if horizontal:
            fill = QRectF(gr.left(), gr.top(), gr.width() * frac, gr.height())
        else:
            fill = QRectF(gr.left(), gr.bottom() - gr.height() * frac, gr.width(), gr.height() * frac)
        if fill.width() > 1 and fill.height() > 1:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setClipPath(_rounded(gr, 4.0))
            fg = QLinearGradient(0, fill.top(), 0, fill.bottom())
            if enabled:
                fg.setColorAt(0.0, _lighten(t["accent_hi"], 10))
                fg.setColorAt(1.0, t["accent"])
            else:
                # 禁用：电光蓝去饱和 → 灰（与可用态一眼可分）
                fg.setColorAt(0.0, _lerp(t["accent_hi"], t["disabled_bg"], 0.62))
                fg.setColorAt(1.0, _lerp(t["accent"], t["disabled_bg"], 0.62))
            painter.fillPath(_rounded(fill, 4.0), QBrush(fg))
            painter.restore()

        if handle.width() < 2 or handle.height() < 2:
            return
        # 手柄：立体圆钮
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        hpath = QPainterPath()
        hpath.addEllipse(handle.adjusted(1, 1, -1, -1))
        if enabled:
            bump = 26 if pressed else (int(26 * hk) if hovered else 0)
            c1 = _lighten(t["raise_top"], 60 + bump)
            c2 = _lighten(t["raise_mid"], 20 + bump)
            c3 = _lighten(t["raise_bot"], bump)
        else:
            c1 = _lerp(t["raise_top"], t["disabled_bg"], 0.72)
            c2 = _lerp(t["raise_mid"], t["disabled_bg"], 0.72)
            c3 = _lerp(t["raise_bot"], t["disabled_bg"], 0.72)
        hg = QLinearGradient(0, handle.top(), 0, handle.bottom())
        hg.setColorAt(0.0, c1)
        hg.setColorAt(0.5, c2)
        hg.setColorAt(1.0, c3)
        painter.fillPath(hpath, QBrush(hg))
        # 镜面高光（禁用态直接省略 → 少了"金属反光"这个可用性暗示）
        if enabled:
            painter.setClipPath(hpath)
            sp = QRadialGradient(QPointF(handle.center().x() - handle.width() * 0.14,
                                         handle.top() + handle.height() * 0.26),
                                 handle.width() * 0.75)
            sp.setColorAt(0.0, _rgba(255, 255, 255, 150))
            sp.setColorAt(1.0, _rgba(255, 255, 255, 0))
            painter.fillPath(hpath, QBrush(sp))
            painter.setClipping(False)
        _stroke_bevel(painter, hpath, QRectF(handle), t["edge"],
                      disabled=not enabled, dark=t["dark"])
        painter.restore()
        # 滑杆手柄的键盘焦点环（圆形 → 必须用椭圆环，套方框很难看）
        if fk > 0.002:
            self._engine.paint_focus_ring(painter, QRectF(handle),
                                          handle.width() / 2.0, fk,
                                          inset=1.0, ellipse=True)

    def _button(self, option, painter, widget):
        S = QStyle.StateFlag
        enabled = bool(option.state & S.State_Enabled)
        hovered, hk = _motion_state(option, widget)
        focused, fk = _focus_state(option, widget)
        sunken = bool(option.state & (S.State_Sunken | S.State_On))

        rect = QRectF(option.rect)
        # 留出投影空间：内容内缩，避免投影被裁
        body = rect.adjusted(1.0, 1.0, -1.0, -4.0)
        # 液态玻璃（浅色）用更大的圆角 —— 大圆角是玻璃的形态语言
        rad = 8.0 if not _theme_colors()["dark"] else 6.0
        # 深色主题：默认/选中(按下)按钮画金色顶弧 —— 按钮的"强调色"高亮（浅色不动）
        _accent_arc = bool(_theme_colors()["dark"]) and (
            bool(option.state & S.State_Default) or sunken)
        self._engine.paint_raised(
            painter, body, rad,
            raised=True, disabled=not enabled, hovered=hovered, sunken=sunken,
            accent=_accent_arc, base=_semantic_base(widget), hover_k=hk,
        )
        # 键盘焦点环：内缩画在按钮面上（不能超出 body，否则会与相邻控件压盖）
        if fk > 0.002 and not sunken:
            self._engine.paint_focus_ring(painter, body, rad, fk, inset=1.8)

    def _well(self, option, painter, widget):
        S = QStyle.StateFlag
        rect = QRectF(option.rect)
        hovered, hk = _motion_state(option, widget)
        focused, fk = _focus_state(option, widget)
        rad = 7.0 if not _theme_colors()["dark"] else 5.0
        self._engine.paint_well(
            painter, rect, rad,
            hovered=hovered,
            disabled=not bool(option.state & S.State_Enabled),
            hover_k=hk)
        # 输入框的键盘焦点环（原来只靠全局 QSS 的 :focus 边框，
        # 而那个边框同时会把引擎的 3D 井顶掉 —— 现在统一由引擎画）
        if fk > 0.002:
            self._engine.paint_focus_ring(painter, rect, rad, fk, inset=1.0)

    def _groupbox(self, option, painter, widget):
        """立体金属板（标题由原生 caption 绘制在板子上方，避免重复/裁切）。"""
        rect = QRectF(option.rect)
        if rect.width() < 16 or rect.height() < 16:
            return
        body = rect.adjusted(0.0, 10.0, 0.0, -1.0)
        rad = 14.0 if not _theme_colors()["dark"] else 9.0
        self._engine.paint_panel(painter, body, rad)


# ---------------------------------------------------------------- 安装

_INSTALLED = None


def install(app) -> bool:
    """安装三维风格（幂等）。返回是否成功。"""
    global _INSTALLED
    try:
        from src.utils.skeuomorphic import SKIN_ENABLED
        if not SKIN_ENABLED:
            return False
    except Exception:
        pass
    try:
        style = SkeuomorphicStyle("Fusion")
        app.setStyle(style)
        _INSTALLED = style
    except Exception:
        return False
    # 过渡动画层：悬停/焦点的渐变。装了 3D 风格才有意义，失败不影响静态渲染。
    try:
        from src.utils.skeuo_motion import install_motion
        install_motion(app)
    except Exception:
        pass
    return True


def installed() -> Optional[SkeuomorphicStyle]:
    return _INSTALLED
