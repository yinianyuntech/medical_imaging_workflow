#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""skeuomorphic —— 光影拟物化（金属 / 玻璃）全局皮肤系统。

设计约束（Qt 样式表的硬限制）：
  * QSS **不支持** `box-shadow` / `inset` / `text-shadow` / `filter`；
  * 因此"光影"用三招模拟：
      1. **多段渐变** —— 顶部亮、底部暗 = 凸起；反向 = 内凹；
      2. **分边异色边框** —— 上/左边取高光色、下/右边取阴影色 = 斜面倒角；
      3. **真实投影** —— 用 `QGraphicsDropShadowEffect` 给外壳元素加外阴影。
  * 光效强度、开关可通过环境变量控制：`MIMW_SKIN=metal|off`（默认 metal）。

只做"外观层"，不改任何布局与业务逻辑。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

from src.core.qt_compat.QtCore import Qt
from src.core.qt_compat.QtGui import (QColor, QLinearGradient, QRadialGradient,
                                      QPainter, QPen, QBrush, QPixmap)
from src.core.qt_compat.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget

SKIN_ENABLED = str(os.environ.get("MIMW_SKIN", "metal")).strip().lower() != "off"
SHADOW_ENABLED = str(os.environ.get("MIMW_SKIN_SHADOW", "1")).strip() != "0"


# ============================================================ 设计令牌

# ============================================================ 字体栈
# 实测（rsna311 / Windows）：本机**没有** Microsoft YaHei；可用的是
#   Source Han Sans CN（思源黑体，7 字重：ExtraLight/Light/Regular/Medium/Bold/Heavy）
#   Bahnschrift（DIN 风、科技感强）  Cascadia Mono（科技感等宽）  SimHei  Segoe UI
# 因此以思源黑体为主，YaHei 仅作为其它机器的回退保留。
FONT_UI = ("'Source Han Sans CN','Microsoft YaHei UI','Microsoft YaHei',"
           "'SimHei','Segoe UI'")
FONT_DISPLAY = ("'Bahnschrift','Source Han Sans CN','Microsoft YaHei',"
                "'SimHei','Segoe UI'")
FONT_MONO = "'Cascadia Mono','Consolas','Source Han Sans CN','Courier New'"

# 排版层级（pt）：标题 > 强调 > 正文 > 辅助
SIZE_TITLE = 18
SIZE_HEAD = 13
SIZE_BODY = 13
SIZE_DIM = 12


def ui_font(size: int = SIZE_BODY, weight: int = 400, display: bool = False,
            letter_spacing: float = 0.0):
    """构造 QFont（QSS 不支持 letter-spacing，必须走 QFont）。"""
    from src.core.qt_compat.QtGui import QFont
    f = QFont("Bahnschrift" if display else "Source Han Sans CN")
    f.setPointSizeF(float(size))
    try:
        f.setWeight(int(weight))
    except Exception:
        f.setBold(int(weight) >= 600)
    if letter_spacing:
        try:
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, float(letter_spacing))
        except Exception:
            pass
    # 保证中英文都能命中：设一组回退族
    try:
        f.setFamilies(["Source Han Sans CN", "Bahnschrift", "Microsoft YaHei UI",
                       "Microsoft YaHei", "SimHei", "Segoe UI"])
    except Exception:
        pass
    return f


def data_font(size: int = SIZE_BODY, weight: int = 600, letter_spacing: float = 0.0):
    """**数据/仪表字体**：数字与西文走 Cascadia Mono（等宽 → 列对齐），
    中文自动回落思源黑体（Cascadia Mono 无 CJK 字形）。
    """
    from src.core.qt_compat.QtGui import QFont
    f = QFont("Cascadia Mono")
    f.setPointSizeF(float(size))
    try:
        f.setWeight(int(weight))
    except Exception:
        f.setBold(int(weight) >= 600)
    if letter_spacing:
        try:
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, float(letter_spacing))
        except Exception:
            pass
    try:
        f.setFamilies(["Cascadia Mono", "Consolas", "Source Han Sans CN",
                       "Microsoft YaHei", "SimHei"])
    except Exception:
        pass
    return f


@dataclass(frozen=True)
class MetalPalette:
    """金属色阶：数字越大越暗（900 最深）。"""

    name: str
    s900: str
    s800: str
    s700: str
    s600: str
    s500: str
    s400: str
    s300: str
    s200: str
    accent: str
    accent_hi: str
    text: str
    text_dim: str
    text_strong: str
    hl: str      # 高光（冷蓝白，带透明度）
    hl_soft: str
    sh: str      # 阴影（深蓝黑，带透明度）
    sh_soft: str
    edge_hi: str    # 面板顶部棱线（冷蓝高光）
    edge_soft: str  # 面板左侧棱线
    chip_text: str  # 标牌标题文字（亮青）
    # ---- 模糊玻璃令牌 ----
    glass_hi: str      # 玻璃顶部（半透明白蓝）
    glass_lo: str      # 玻璃底部（更透）
    glass_rim: str     # 边缘反光
    glass_edge: str    # 外缘暗线
    glass_shadow: str  # 投射阴影
    bg_glow: str       # 背景装饰辉光（让玻璃"有东西可模糊"）


DARK_METAL = MetalPalette(
    name="dark",
    # ===== 冷蓝金属底 + 深黄（金琥珀）强调色 =====
    # 底材/投影/背景=原冷蓝金属（未动）；**深黄只作强调色**：
    # 字体高亮（分组标题/芯片）、按钮高亮（默认/选中文字、焦点环）、
    # 菜单高亮（选中项金底深字、菜单栏悬停金晕）。
    s900="#04070E", s800="#070D18", s700="#0B1524", s600="#112036",
    s500="#182F4E", s400="#1F3A5F", s300="#365C8C", s200="#6E96C8",
    accent="#D9A62E", accent_hi="#F3CB5A",
    text="#F2F7FF", text_dim="#B3C6E0", text_strong="#FFFFFF",
    hl="rgba(255,214,120,0.26)", hl_soft="rgba(255,214,120,0.12)",
    sh="rgba(0,4,12,0.82)", sh_soft="rgba(0,4,12,0.44)",
    edge_hi="rgba(255,208,110,0.55)", edge_soft="rgba(255,208,110,0.22)",
    chip_text="#F5D680",
    glass_hi="rgba(30,58,104,0.62)", glass_lo="rgba(10,22,44,0.70)",
    glass_rim="rgba(200,232,255,0.42)", glass_edge="rgba(0,8,22,0.72)",
    glass_shadow="rgba(0,3,12,0.50)", bg_glow="rgba(40,120,230,0.22)",
)

LIGHT_ALU = MetalPalette(
    name="light",
    # ===== 液态玻璃（Liquid Glass）=====
    # 冷色冰川空气背景 + 近白半透明玻璃体：面板=半透明白玻璃，边缘镜面高光，
    # 投影=冷蓝灰（纯黑投影在亮玻璃上会"发脏"）。
    # 色阶整体提亮、降饱和：玻璃后面应当感到"有一种透明的东西"。
    s900="#AFC2DE", s800="#C2D1E8", s700="#D6E2F3", s600="#E4EDF9",
    s500="#EEF4FC", s400="#F5F9FF", s300="#FAFDFF", s200="#FFFFFF",
    accent="#0B6BD4", accent_hi="#2E93F0",
    text="#0A1524", text_dim="#33445E", text_strong="#000000",
    hl="rgba(255,255,255,0.98)", hl_soft="rgba(255,255,255,0.72)",
    sh="rgba(84,114,164,0.38)", sh_soft="rgba(84,114,164,0.20)",
    edge_hi="rgba(255,255,255,1.0)", edge_soft="rgba(255,255,255,0.72)",
    chip_text="#0A4E96",
    # 玻璃令牌：上端更亮更实（镜面受光），下端更透（透镜透射），
    # 外缘暗线用低饱和冷蓝（玻璃的"厚度感"来自这条线）
    # 注意：面板要**真透**——alpha 高到 0.85+ 就成白卡了，环境光透不过来。
    glass_hi="rgba(255,255,255,0.78)",
    glass_lo="rgba(214,231,250,0.44)",
    glass_rim="rgba(255,255,255,1.0)",
    glass_edge="rgba(146,174,212,0.52)",
    glass_shadow="rgba(84,114,164,0.22)",
    bg_glow="rgba(170,215,255,0.75)",
)


def current_palette() -> MetalPalette:
    """按当前主题返回色阶。

    可用 `MIMW_THEME=light|dark` 强制覆盖，便于无头渲染与验证两套主题。
    """
    env = str(os.environ.get("MIMW_THEME", "")).strip().lower()
    if env in ("light", "dark"):
        # 同步 ThemeManager，避免"调色板已切、但控件仍按旧主题分支取色"的错配
        # （R9 实测踩过：MIMW_THEME=light 下部分控件仍用深色 #3E3E3E）
        try:
            from src.utils.theme_manager import ThemeManager
            ThemeManager._current_theme = env
        except Exception:
            pass
        return LIGHT_ALU if env == "light" else DARK_METAL
    try:
        from src.utils.theme_manager import ThemeManager
        if str(ThemeManager.get_current_theme()).lower() == "light":
            return LIGHT_ALU
    except Exception:
        pass
    return DARK_METAL


# ============================================================ 渐变/斜面工具

def _grad(p: MetalPalette, top: str, bottom: str, mid: Optional[str] = None) -> str:
    if mid:
        return (f"qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                f"stop:0 {top}, stop:0.52 {mid}, stop:1 {bottom})")
    return f"qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {top},stop:1 {bottom})"


def _bevel(p: MetalPalette, radius: int = 6, raised: bool = True) -> str:
    """分边异色边框：raised=True 凸起（上亮下暗），否则内凹。"""
    top = p.hl if raised else p.sh
    bottom = p.sh if raised else p.hl_soft
    return (
        f"border: 1px solid {p.s900};"
        f"border-top-color: {top};"
        f"border-left-color: {top if raised else p.s900};"
        f"border-bottom-color: {bottom};"
        f"border-right-color: {bottom if raised else p.s900};"
        f"border-radius: {radius}px;"
    )


def _materials_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "MedicalImagingWorkflow", "cache", "skin")
    os.makedirs(d, exist_ok=True)
    return d


# 材质生成器版本：改动生成逻辑或配色后 +1，即可自动使旧缓存失效
# v7：浅色主题切换为「液态玻璃」（新增 backdrop 环境背景）
_MATERIAL_VERSION = 7


def ensure_materials(p: Optional[MetalPalette] = None, force: bool = False) -> dict:
    """把程序化材质（拉丝金属、噪点）落成 PNG，供 QSS `url()` 引用。

    QSS 不能内联生成位图，只能引用文件；文件名带**版本号 + 配色名**，
    因此换肤/改生成器后会自动重新生成，不会读到旧缓存。
    """
    p = p or current_palette()
    ver = f"v{_MATERIAL_VERSION}"
    out = {}
    files = {
        "frost": (f"frost_{p.name}_{ver}.png", lambda: frost_pixmap(128, 128, p)),
        # 标题栏：玻璃条（半透明 + 颗粒 + 顶部受光）
        "titlebar": (f"titlebar_{p.name}_{ver}.png", lambda: surface_pixmap("raised", 256, 96, p)),
        "surface_panel": (f"surface_panel_{p.name}_{ver}.png", lambda: surface_pixmap("panel", 128, 1024, p)),
        "surface_raised": (f"surface_raised_{p.name}_{ver}.png", lambda: surface_pixmap("raised", 128, 1024, p)),
        "surface_sunken": (f"surface_sunken_{p.name}_{ver}.png", lambda: surface_pixmap("sunken", 128, 1024, p)),
        # 液态玻璃「环境背景」（浅色模式整窗铺底；玻璃面板靠在它上面显透明）
        "backdrop": (f"backdrop_{p.name}_{ver}.png", lambda: backdrop_pixmap(1600, 1000, p)),
    }
    for key, (name, maker) in files.items():
        path = os.path.join(_materials_dir(), name)
        if force or not os.path.exists(path):
            try:
                pm = maker()
                pm.save(path, "PNG")
            except Exception:
                pass
        if os.path.exists(path):
            out[key] = path.replace("\\", "/")
    return out


def surface_pixmap(kind: str = "panel", width: int = 128, height: int = 1024,
                   p: Optional[MetalPalette] = None) -> QPixmap:
    """生成"带颗粒的金属面"贴图（纵向渐变 + 磨砂颗粒 + 细拉丝）,供 QSS 的
    `background-image: repeat-x` 使用。

    设计要点：
      * **横向恒定** → repeat-x 无缝；
      * 高度 1024 足够覆盖绝大多数面板，纵向不重复（避免条带）；
      * 圆角仍由 QSS 的 border-radius 裁切，本贴图不画圆角，因此**不改变任何布局**。
    """
    import random

    p = p or current_palette()
    dark = p.name == "dark"
    pm = QPixmap(width, height)
    pm.fill(QColor(p.s700))
    painter = QPainter(pm)
    try:
        painter.setRenderHint(QPainter.Antialiasing, False)

        if kind == "raised":
            top, mid, bot = p.s500, p.s600, p.s700
        elif kind == "sunken":
            top, mid, bot = p.s900, p.s800, p.s700
        else:  # panel
            top, mid, bot = p.s600, p.s700, p.s900

        # 1) 纵向金属渐变（前 40% 变化明显，之后收敛，模拟受光→背光）
        g = QLinearGradient(0, 0, 0, height)
        g.setColorAt(0.00, QColor(top))
        g.setColorAt(0.12, QColor(mid))
        g.setColorAt(0.55, QColor(bot))
        g.setColorAt(1.00, QColor(bot))
        painter.fillRect(0, 0, width, height, QBrush(g))

        # 2) 磨砂颗粒（可见但不脏）：逐行均匀 → 无缝
        rnd = random.Random(hash(kind) & 0xFFFF)
        for y in range(height):
            r = rnd.random()
            if r < 0.34:
                col = QColor(120, 185, 255, rnd.randint(14, 40))
            elif r < 0.68:
                col = QColor(0, 4, 14, rnd.randint(14, 44))
            else:
                col = QColor(190, 225, 255, rnd.randint(6, 20))
            painter.setPen(QPen(col, 1))
            painter.drawLine(0, y, width, y)

        # 3) 顶部受光高光带（横向恒定）
        band = QLinearGradient(0, 0, 0, max(24, height // 40))
        band.setColorAt(0.0, QColor(150, 205, 255, 60 if dark else 90))
        band.setColorAt(1.0, QColor(150, 205, 255, 0))
        painter.fillRect(0, 0, width, max(24, height // 40), QBrush(band))
    finally:
        painter.end()
    return pm


def backdrop_pixmap(width: int = 1600, height: int = 1000,
                    p: Optional[MetalPalette] = None) -> "QPixmap":
    """液态玻璃的「环境背景」：空气感渐变 + 大尺度柔光光斑 + 极细颗粒。

    它不是装饰噪声 —— 玻璃面板的"透明感"全靠它：没有可见的背景内容，
    半透明面板看起来就只是纯色块（这是 Apple Liquid Glass 的关键：
    玻璃必须"有东西可透"）。QSS 里用 `border-image ... stretch stretch`
    拉伸铺满窗口（柔光斑变形无感）。
    """
    p = p or current_palette()
    dark = p.name == "dark"
    pm = QPixmap(width, height)
    painter = QPainter(pm)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)

        # 1) 空气感基底：上冰川白 → 下冰蓝
        if dark:
            g = QLinearGradient(0, 0, 0, height)
            g.setColorAt(0.0, QColor(p.s700))
            g.setColorAt(0.5, QColor(p.s800))
            g.setColorAt(1.0, QColor(p.s900))
        else:
            g = QLinearGradient(0, 0, 0, height)
            g.setColorAt(0.00, QColor("#F7FAFF"))
            g.setColorAt(0.45, QColor("#E3EEFA"))
            g.setColorAt(1.00, QColor("#D2E3F8"))
        painter.fillRect(0, 0, width, height, QBrush(g))

        # 2) 大尺度柔光光斑（径向渐变本身就是"模糊"的 —— 静态模糊，零渲染开销）
        #    必须有**可感知的色彩**：玻璃面板靠它显出"透光/滤色"的透明感。
        if not dark:
            glows = (
                # (cx, cy, radius, color)  —— 直径 0.9~1.5 画幅，保证边界处已衰减到 0
                (0.14, -0.06, 0.72, QColor(168, 220, 255, 255)),  # 左上：天光青
                (1.02, 0.16, 0.70, QColor(166, 188, 255, 172)),   # 右上：淡紫蓝
                (0.45, 1.10, 0.62, QColor(138, 200, 255, 150)),   # 底部中央：冰蓝
                (0.04, 0.96, 0.50, QColor(255, 255, 255, 190)),   # 左下：乳白
                (0.58, 0.42, 0.72, QColor(255, 255, 255, 110)),   # 中央：珍珠光
            )
            for cx, cy, r, col in glows:
                rg = QRadialGradient(width * cx, height * cy, width * r)
                c0 = QColor(col)
                c1 = QColor(col)
                c1.setAlpha(0)
                rg.setColorAt(0.0, c0)
                rg.setColorAt(0.55, QColor(c0.red(), c0.green(), c0.blue(),
                                           int(c0.alpha() * 0.42)))
                rg.setColorAt(1.0, c1)
                painter.fillRect(0, 0, width, height, QBrush(rg))

            # 3) 顶部斜向柔光薄纱（更像"光穿过玻璃"而不是平涂）
            sheen = QLinearGradient(0, 0, width * 0.7, height * 0.9)
            sheen.setColorAt(0.0, QColor(255, 255, 255, 150))
            sheen.setColorAt(0.35, QColor(255, 255, 255, 34))
            sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(0, 0, width, height, QBrush(sheen))

        # 4) 极细颗粒（让大块渐变不出现色带；alpha 很低，肉眼几乎不可见）
        import random
        rnd = random.Random(20260)
        for _ in range(int(width * height * 0.03)):
            x, y = rnd.randrange(width), rnd.randrange(height)
            if dark:
                c = QColor(160, 200, 255, rnd.randint(4, 12))
            else:
                c = QColor(120, 156, 210, rnd.randint(3, 9))
            painter.setPen(QPen(c, 1))
            painter.drawPoint(x, y)
    finally:
        painter.end()
    return pm


def _noise_pixmap(width: int = 128, height: int = 128, p: Optional[MetalPalette] = None) -> "QPixmap":
    """细颗粒噪点（玻璃/磨砂质感）。"""
    import random
    p = p or current_palette()
    pm = QPixmap(width, height)
    pm.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pm)
    try:
        rnd = random.Random(4242)
        dark = QColor(0, 0, 0)
        light = QColor(255, 255, 255)
        for _ in range(int(width * height * 0.16)):
            x, y = rnd.randrange(width), rnd.randrange(height)
            c = light if rnd.random() > 0.5 else dark
            c = QColor(c)
            c.setAlpha(rnd.randint(8, 26))
            painter.setPen(QPen(c, 1))
            painter.drawPoint(x, y)
    finally:
        painter.end()
    return pm


# ============================================================ 全局 QSS

def global_qss(p: Optional[MetalPalette] = None, heavy: bool = True) -> str:
    """生成全局样式表。heavy=True 为浓重金属/玻璃质感。"""
    p = p or current_palette()
    mat = ensure_materials(p)
    frost = f"url({mat['frost']})" if mat.get("frost") else "none"
    surf_panel = f"url({mat['surface_panel']})" if mat.get("surface_panel") else "none"
    surf_raised = f"url({mat['surface_raised']})" if mat.get("surface_raised") else "none"
    surf_sunken = f"url({mat['surface_sunken']})" if mat.get("surface_sunken") else "none"

    raised = _grad(p, p.s500, p.s700, p.s600)
    raised_hover = _grad(p, p.s400, p.s600, p.s500)
    pressed = _grad(p, p.s800, p.s600)
    sunken = _grad(p, p.s800, p.s700)
    # 玻璃：半透明纵向渐变（**不用图像**，避免与 background-color 冲突）
    glass = _grad(p, p.glass_hi, p.glass_lo)
    chrome = glass
    panel = _grad(p, p.glass_hi, p.glass_lo)
    chip = _grad(p, p.s400, p.s700)

    dark = p.name == "dark"

    # ---- 液态玻璃（浅色）专项：更亮/更透/冷色投影；深色主题保持金属原样 ----
    if dark:
        window_bg = (
            "background: qradialgradient(cx:0.22, cy:0.02, radius:1.35,"
            " fx:0.22, fy:0.02,"
            f" stop:0 {p.bg_glow}, stop:0.32 {p.s700}, stop:1 {p.s900});"
        )
        glass_bar = _grad(p, p.glass_hi, "rgba(0,0,0,0.06)")
        menu_bg = _grad(p, p.s600, p.s700)
        popup_bg = _grad(p, p.s600, p.s700)
        chip_bg = _grad(p, p.s600, p.s700)
        table_bg = _grad(p, p.glass_lo, "rgba(0,10,28,0.16)")
        table_alt = _grad(p, "rgba(255,255,255,0.030)", "rgba(0,10,28,0.10)")
        sep_col = p.s900
        # 鎏金选中态：亮金渐变 + 深字（奶油字压金渐变下半段对比度不足）
        sel_grad = _grad(p, p.accent_hi, p.accent)
        sel_fg = "#241B04"
        menu_sel_fg = " color: #241B04;"
        combo_sel = " selection-color: #241B04;"
        # 菜单栏悬停=金色高亮晕（强调色，非背景）
        mbar_sel_bg = _grad(p, "rgba(255,214,120,0.26)", "rgba(255,214,120,0.08)")
        mbar_sel_bd = p.edge_hi
        checked_rule = f"\nQPushButton:checked {{ color: {p.accent_hi}; }}"
    else:
        # 环境背景：拉伸铺满整窗（柔光斑变形无感）——玻璃面板"有东西可透"
        backdrop = f"url({mat['backdrop']})" if mat.get("backdrop") else "none"
        window_bg = f"border-image: {backdrop} 0 0 0 0 stretch stretch;"
        glass_bar = _grad(p, "rgba(255,255,255,0.88)", "rgba(226,238,251,0.66)")
        # 弹层要更实（保证正文对比度），只在边缘保留玻璃感
        menu_bg = _grad(p, "rgba(253,254,255,0.97)", "rgba(233,241,252,0.97)")
        popup_bg = menu_bg
        chip_bg = _grad(p, "rgba(255,255,255,0.92)", "rgba(226,238,252,0.85)")
        table_bg = _grad(p, "rgba(255,255,255,0.78)", "rgba(234,242,252,0.62)")
        table_alt = _grad(p, "rgba(255,255,255,0.42)", "rgba(222,234,250,0.38)")
        sep_col = "rgba(130,158,196,0.60)"
        # 液态玻璃（浅色）保持既有选中态（白字蓝底）—— 浅色已冻结
        sel_grad = _grad(p, p.accent, p.s500)
        sel_fg = "#FFFFFF"
        menu_sel_fg = ""
        combo_sel = ""
        mbar_sel_bg = _grad(p, p.glass_hi, "rgba(255,255,255,0.02)")
        mbar_sel_bd = p.glass_rim
        checked_rule = ""

    # 液态玻璃（浅色）用更大圆角 —— 大圆角是玻璃的形态语言
    menu_rad = 11 if not dark else 10
    table_rad = 12 if not dark else 10
    pane_rad = 12 if not dark else 9

    return f"""
/* ================= 全局基底 ================= */
QWidget {{
    font-family: {FONT_UI};
    font-size: {SIZE_BODY}px;
    color: {p.text};
}}
QMainWindow, QDialog, QWizard {{
    /* 背景：冷蓝底 + 顶部装饰辉光 —— 让上面的玻璃面板"有东西可模糊" */
    {window_bg}
}}
QMainWindow::separator {{ background: {p.s900}; width: 1px; height: 1px; }}
QWidget#qt_scrollarea_viewport, QScrollArea {{ background: transparent; border: none; }}
QAbstractScrollArea {{ border: none; }}

/* ================= 玻璃菜单栏 ================= */
QMenuBar {{
    background: {glass_bar};
    border-bottom: 1px solid {p.glass_edge};
    border-top: 1px solid {p.glass_rim};
    padding: 3px 4px;
}}
QMenuBar::item {{
    padding: 5px 11px; margin: 1px 2px;
    border-radius: 6px;
    background: transparent;
    font-size: {SIZE_HEAD}px;
    font-weight: 600;
}}
QMenuBar::item:selected {{
    background: {mbar_sel_bg};
    border: 1px solid {mbar_sel_bd};
}}
QMenuBar::item:pressed {{ background: {_grad(p, "rgba(255,255,255,0.04)", p.glass_lo)}; }}

QMenu {{
    background: {menu_bg};
    border: 1px solid {p.glass_edge};
    border-top-color: {p.glass_rim};
    border-radius: {menu_rad}px;
    padding: 6px;
}}
QMenu::item {{ padding: 6px 24px 6px 14px; border-radius: 5px;
    font-size: {SIZE_HEAD}px; font-weight: 500; }}
QMenu::item:selected {{
    background: {sel_grad};{menu_sel_fg}
    border-top: 1px solid {p.hl};
}}
QMenu::separator {{ height: 1px; background: {sep_col}; margin: 5px 8px; }}

/* ================= 金属面板 + 标牌标题（拟物核心） ================= */
/* QGroupBox 的**背景/边框**必须留给三维引擎（src/utils/skeuo_style.py），
   否则 QStyleSheetStyle 会接管绘制，引擎的 PE_FrameGroupBox 就不再被调用。
   这里只设置非盒模型属性（颜色/字体），实测不影响引擎接管。 */
QGroupBox {{
    color: {p.accent_hi};
    font-size: {SIZE_HEAD}px;
    font-weight: 700;
}}

/* ================= 金属凸起按钮 ================= */
/* 注意：按钮/输入框/分组框的**背景与边框交给三维绘制引擎**
   (src/utils/skeuo_style.py)。这里只保留排版属性（padding/字体/颜色），
   否则 QSS 会接管背景绘制，三维倒角与投射阴影就不生效了。 */
QPushButton {{
    padding: 7px 15px;
    font-size: {SIZE_HEAD}px;
    font-weight: 600;
}}
QPushButton:hover {{ color: {p.text_strong}; }}
QPushButton:default {{ color: {p.accent_hi}; }}{checked_rule}

/* ⚠️ 禁用/选中态**不设** background / border。
   一旦设了，QStyleSheetStyle 就会接管绘制并**跳过三维引擎**，
   按钮退化成平涂色块 —— 实测禁用按钮一直是 QSS 平涂，
   引擎里那段 disabled 玻璃**根本没被执行过**。
   这两个状态现在交给引擎画（见 skeuo_style._button 的 disabled/sunken 分支）。
   （只写 color 是安全的：color 不构成 drawable 规则，不会触发接管。） */

/* ================= 内凹输入控件 ================= */
QLineEdit, QTextEdit, QTextBrowser, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
    /* ⚠️ 竖向 padding 必须小。QSS 的 padding / min-height 会被
       QStyleSheetStyle 转成**真实的 minimumSize**，从而**压过**应用里的
       `setFixedHeight(22~26)` —— 实测下拉框被撑到 30px、溢出 32px 的工具条 2px。
       本项目的固定行高只有 22/24/26/32，所以竖向占用要控制在 ~24px 以内。
       引擎自己会画井的立体感，视觉内边距不依赖 QSS padding。 */
    padding: 3px 8px;
    selection-background-color: {p.accent};
    selection-color: {sel_fg};
}}
/* ⚠️ 这里**不能**给 :focus 设 border。
   设了会让 QStyleSheetStyle 接管，引擎的 3D 井在聚焦时**整块消失**
   —— 实测 `line/focus` 像素差 244，本质是"3D 井没了 + 多了条 1px 边框"，
   而不是"多了一圈焦点反馈"。焦点环现在由引擎统一绘制
   （`SkeuoPainter.paint_focus_ring`），因此 combo/check/radio/slider
   也能有同样一致、且跟随主题热切换的焦点环。 */
QLineEdit:disabled, QTextEdit:disabled {{
    color: {p.text_dim};
}}

/* 组合框：背景/边框/箭头交给三维引擎。
   ⚠️ 这里**不能**写 `min-height` —— QStyleSheetStyle 会把它转成真实的
   `setMinimumSize`，直接压过应用里的 `setFixedHeight(24)`，
   把下拉框撑到 30px 并溢出 32px 高的工具条（实测溢出 2px，R10 可复现）。 */
QComboBox {{
    padding: 3px 8px;
}}
QComboBox QAbstractItemView {{
    background: {popup_bg};
    border: 1px solid {p.glass_edge};
    border-radius: 8px;
    selection-background-color: {p.accent};{combo_sel}
    outline: none;
}}

/* 勾选框/单选钮指示器：内凹井 + 立体勾（三维引擎绘制）。
   这里只约束**尺寸**，不设背景/边框 —— 设了背景/边框会阻断引擎接管。 */
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}

/* 滚动条：槽与滑块交给三维引擎（内凹槽 + 立体滑块） */

/* 表格/列表：玻璃面 + 引擎绘制的表头
   字体用等宽栈：数字/西文走 Cascadia Mono（列自动对齐，仪表感），
   中文**自动回落**思源黑体（Cascadia Mono 无 CJK 字形）。 */
QTableView, QTreeView, QListWidget, QTableWidget, QTreeWidget {{
    background: {table_bg};
    alternate-background-color: {table_alt};
    gridline-color: {p.glass_edge};
    border: 1px solid {p.glass_edge};
    border-top-color: {p.glass_rim};
    border-radius: {table_rad}px;
    selection-background-color: {p.accent};
    selection-color: {sel_fg};
    font-family: {FONT_MONO};
    font-size: {SIZE_BODY}px;
    outline: none;
}}
/* 数值输入：同样等宽 */
QSpinBox, QDoubleSpinBox {{
    font-family: {FONT_MONO};
    font-weight: 600;
}}
/* 表头单元格：背景/边框交给三维引擎（薄金属板） */
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    color: {p.text_strong};
    padding: 7px 9px;
    font-size: {SIZE_HEAD}px;
    font-weight: 700;
}}
QTableView::item:selected, QTreeView::item:selected, QListWidget::item:selected,
QTreeWidget::item:selected {{
    background: {sel_grad};
}}
QListWidget::item, QTreeWidget::item {{ padding: 4px 6px; }}
QTableCornerButton::section {{
    background: {_grad(p, p.s500, p.s700)};
    border: 1px solid {p.s900};
}}

/* ================= 标签页（金属卡舌） ================= */
QTabWidget::pane {{
    background: {glass};
    border: 1px solid {p.s900};
    border-top-color: {p.hl_soft};
    border-radius: {pane_rad}px;
    top: -1px;
}}
/* 标签页卡舌：形状完全交给三维引擎（选中抬起 + 顶部电光蓝）。
   这里**不能**保留任何 QTabBar::tab 规则，否则 QStyleSheetStyle 接管 CE_TabBarTabShape。 */

/* 滑块：槽/填充/手柄交给三维引擎（内凹槽 + 立体圆钮） */

/* ================= 进度条 ================= */
QProgressBar {{
    background: {sunken};
    border: 1px solid {p.s900};
    border-radius: 8px;
    text-align: center;
    color: {p.text};
    min-height: 14px;
}}
QProgressBar::chunk {{
    background: {_grad(p, p.accent_hi, p.accent)};
    border-radius: 7px;
}}

/* ================= 状态栏（玻璃） ================= */
QStatusBar {{
    background: {glass_bar};
    border-top: 1px solid {p.glass_edge};
    color: {p.text_dim};
}}
QStatusBar QLabel {{ color: {p.text_dim}; padding: 0 6px; }}
QStatusBar::item {{ border: none; }}

/* ================= 分隔器 / 提示 ================= */
QSplitter::handle {{ background: {p.s900}; }}
QSplitter::handle:hover {{ background: {p.accent}; }}
QToolTip {{
    background: {menu_bg};
    color: {p.text};
    border: 1px solid {p.accent};
    border-radius: 5px;
    padding: 4px 7px;
}}
"""


# ============================================================ 真实投影

def apply_shadow(widget: QWidget, blur: int = 22, dy: int = 5,
                 alpha: int = 190, color: Optional[str] = None) -> bool:
    """给外壳元素加 `QGraphicsDropShadowEffect` 外投影（QSS 做不到真正的投影）。"""
    if not (SKIN_ENABLED and SHADOW_ENABLED):
        return False
    try:
        p = current_palette()
        eff = QGraphicsDropShadowEffect(widget)
        eff.setBlurRadius(int(blur))
        eff.setOffset(0, int(dy))
        c = QColor(color or ("#000000" if p.name == "dark" else "#7A8798"))
        c.setAlpha(int(alpha))
        eff.setColor(c)
        widget.setGraphicsEffect(eff)
        return True
    except Exception:
        return False


def apply_inner_glow(widget: QWidget, blur: int = 16, alpha: int = 70) -> bool:
    """柔和内高光（用零偏移投影近似"发光"）。"""
    return apply_shadow(widget, blur=blur, dy=0, alpha=alpha, color="#FFFFFF")


# ============================================================ 应用入口

def apply_global(app: Optional[QApplication] = None, *, heavy: bool = True) -> bool:
    """把皮肤装到 QApplication（覆盖 ThemeManager 之后的最终样式）。"""
    if not SKIN_ENABLED:
        return False
    app = app or QApplication.instance()
    if app is None:
        return False
    try:
        p = current_palette()
        # 应用默认字体：让没有 QSS 覆盖的控件（含自绘文本）也用同一字体栈
        try:
            app.setFont(ui_font(SIZE_BODY, 400))
        except Exception:
            pass
        app.setStyleSheet(global_qss(p, heavy=heavy))
        _apply_palette(app, p)
        return True
    except Exception:
        return False


def _apply_palette(app: QApplication, p: MetalPalette) -> None:
    from src.core.qt_compat.QtGui import QPalette
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(p.s800))
    pal.setColor(QPalette.WindowText, QColor(p.text))
    pal.setColor(QPalette.Base, QColor(p.s800))
    pal.setColor(QPalette.AlternateBase, QColor(p.s700))
    pal.setColor(QPalette.Text, QColor(p.text))
    pal.setColor(QPalette.Button, QColor(p.s600))
    pal.setColor(QPalette.ButtonText, QColor(p.text))
    pal.setColor(QPalette.Highlight, QColor(p.accent))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ToolTipBase, QColor(p.s600))
    pal.setColor(QPalette.ToolTipText, QColor(p.text))
    pal.setColor(QPalette.PlaceholderText, QColor(p.text_dim))
    app.setPalette(pal)


# ---------------------------------------------------------------- 画刷材质

def frost_pixmap(width: int = 128, height: int = 128,
                 p: Optional[MetalPalette] = None) -> QPixmap:
    """**磨砂玻璃**颗粒贴图：各向同性细颗粒。

    与拉丝金属的本质区别：**无方向性**（金属是定向横纹 + 刻度线）。
    边缘环绕绘制使贴图可无缝平铺。
    """
    import random

    p = p or current_palette()
    warm = p.name == "dark"
    pm = QPixmap(width, height)
    pm.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pm)
    try:
        painter.setRenderHint(QPainter.Antialiasing, False)
        rnd = random.Random(90210)
        n = int(width * height * 0.62)
        for _ in range(n):
            x, y = rnd.randrange(width), rnd.randrange(height)
            light = rnd.random() > 0.44
            c = QColor(235, 245, 255) if light else QColor(10, 20, 40)
            c.setAlpha(rnd.randint(5, 22))
            painter.setPen(QPen(c, 1))
            # 环绕绘制 → 平铺无缝
            for dx in (-width, 0, width):
                for dy in (-height, 0, height):
                    painter.drawPoint(x + dx, y + dy)
    finally:
        painter.end()
    return pm


def surface_pixmap(kind: str = "panel", width: int = 128, height: int = 1024,
                   p: Optional[MetalPalette] = None) -> QPixmap:
    """带颗粒的**半透明玻璃面**贴图（供 QSS `background-image` 平铺）。

    保持横向恒定以保证 `repeat-x` 无缝；不再有条纹与刻度。
    """
    import random

    p = p or current_palette()
    dark = p.name == "dark"
    pm = QPixmap(width, height)
    pm.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pm)
    try:
        painter.setRenderHint(QPainter.Antialiasing, False)

        # 1) 半透明纵向玻璃渐变（顶部更亮 = 受光面）
        if kind == "raised":
            top = QColor(180, 215, 255, 40 if dark else 66)
            bot = QColor(120, 165, 230, 14 if dark else 30)
        elif kind == "sunken":
            top = QColor(0, 8, 22, 132 if dark else 46)
            bot = QColor(0, 8, 22, 74 if dark else 22)
        else:  # panel
            top = QColor(175, 210, 255, 30 if dark else 54)
            bot = QColor(120, 170, 235, 10 if dark else 24)
        g = QLinearGradient(0, 0, 0, height)
        g.setColorAt(0.00, top)
        g.setColorAt(0.42, QColor(top.red(), top.green(), top.blue(),
                                  int(top.alpha() * 0.62)))
        g.setColorAt(1.00, bot)
        painter.fillRect(0, 0, width, height, QBrush(g))

        # 2) 各向同性玻璃颗粒（无方向性）
        rnd = random.Random(31337)
        for _ in range(int(width * height * 0.30)):
            x, y = rnd.randrange(width), rnd.randrange(height)
            light = rnd.random() > 0.5
            c = QColor(240, 248, 255) if light else QColor(0, 10, 26)
            c.setAlpha(rnd.randint(4, 16))
            painter.setPen(QPen(c, 1))
            painter.drawPoint(x, y)

        # 3) 顶部一层薄高光（玻璃边缘受光）
        band = QLinearGradient(0, 0, 0, max(16, height // 48))
        band.setColorAt(0.0, QColor(235, 245, 255, 58 if dark else 92))
        band.setColorAt(1.0, QColor(235, 245, 255, 0))
        painter.fillRect(0, 0, width, max(16, height // 48), QBrush(band))
    finally:
        painter.end()
    return pm


def title_bar_qss(p: Optional[MetalPalette] = None) -> str:
    """顶部标题栏：**玻璃条** —— 半透明受光面 + 上亮下暗收边。"""
    p = p or current_palette()
    if p.name == "light":
        # 液态玻璃：上镜面白 → 下冰蓝，底缘冷蓝收边（不再是深色压边）
        return f"""
QFrame#mimwTitleBar {{
    background: {_grad(p, "rgba(255,255,255,0.94)", "rgba(214,228,248,0.72)")};
    border: none;
    border-top: 1px solid {p.glass_rim};
    border-bottom: 1px solid rgba(132,160,200,0.55);
}}
QFrame#mimwTitleBar QLabel {{ background: transparent; }}
"""
    return f"""
QFrame#mimwTitleBar {{
    background: {_grad(p, p.glass_hi, "rgba(0,10,28,0.22)")};
    border: none;
    border-top: 1px solid {p.glass_rim};
    border-bottom: 1px solid {p.glass_edge};
}}
QFrame#mimwTitleBar QLabel {{ background: transparent; }}
"""


def title_bar_foreground_qss(p: Optional[MetalPalette] = None) -> str:
    """标题栏文字：**只设颜色**。

    字体（族/字号/字重/**字距**）必须走 QFont —— Qt 的 QSS **不支持 letter-spacing**。
    """
    p = p or current_palette()
    if p.name == "dark":
        main_c, sub_c = p.text_strong, p.text_dim
    else:
        main_c, sub_c = "#08111F", p.text_dim
    return f"""
QLabel#mimwTitleText {{ color: {main_c}; }}
QLabel#mimwProjectText {{ color: {sub_c}; }}
"""


def glass_panel_qss(p: Optional[MetalPalette] = None) -> str:
    """玻璃面板：半透明渐变 + 顶部反光边。"""
    p = p or current_palette()
    return f"""
QWidget#mimwGlass {{
    background: {_grad(p, p.glass_hi, p.glass_lo)};
    border: 1px solid {p.glass_edge};
    border-top-color: {p.glass_rim};
    border-radius: 10px;
}}
"""


# ============================================================ 局部样式清理

# 浅色主题遗留的"硬编码外壳色 + 深色文字色"：命中即认为与全局皮肤冲突
_LIGHT_MARKERS = (
    "#FFFFFF", "#ffffff", "#FFF", "#F5F5F5", "#FAFAFA", "#F8F9FA",
    "#E0E0E0", "#CCCCCC", "#DDD", "#ddd", "#F0F0F0", "#E3F2FD",
    "#F2F2F2", "#707070", "#5A5A5A", "#6A6A6A", "#4A4A4A",
    "#2E86AB", "#1976D2", "#D0D0D0",
    "#CCC", "#EEE", "#AAA", "#f0f0f0", "#fafafa", "#f8f9fa", "#e3f2fd",
    # 深灰系文字色：在深色皮肤上对比度不足（实测 1.15~1.57:1），必须清掉
    "#666666", "#666", "#343434", "#333333", "#333", "#444444", "#444",
    "#555555", "#555", "#777777", "#777", "#888888", "#888", "#999999", "#999",
    "#AAAAAA", "#AAA", "#BBBBBB", "#CCC",
    "#2C3E50", "#34495E", "#1C2C3C",
    # ---- 深色主题专属色（ThemeManager/qdarkstyle 的紫色系 + 灰阶）----
    # 构造期写死这些颜色的控件在浅色主题下会"紫底紫字"，必须清掉交由实时皮肤决定
    "#E879F9", "#F5D0FE", "#D8B4FE", "#E9D5FF", "#F0ABFC", "#DB61A2",
    "#2D2D30", "#3E3E42", "#45454D", "#5C5C61", "#68686D", "#252526",
    "#333337", "#1E1E1E", "#2B2B2B", "#3A3A3A", "#4A4A4A",
)
# 功能性语义色（成功/危险/警告/选中）：命中则**保留**该局部样式
_KEEP_MARKERS = (
    "#4CAF50", "#4CAC54", "#F44336", "#FC6C6C", "#FF9800", "#FC9C04",
    "#D32F2F", "#45a049", "#F57C00", "#39FF14", "#FF00FF", "#B0B0B0",
    "#047CCC", "#2196F3", "#FF6B6B", "#C62828", "#2E7D32", "#B45309",
    "#FF1744", "#F01440", "#D91035",
    "#009688", "#00796B", "#00695C", "#004D40", "#4CAF50",
)

# 语义色 → 可访问性修正（保证白字满足 WCAG AA 4.5:1）
_CONTRAST_FIX = {
    "#4CAF50": "#2E7D32",   # 成功绿：白字 2.79:1 → 5.13:1
    "#4CAC54": "#2E7D32",
    "#45a049": "#256428",
    "#F44336": "#C62828",   # 危险红：2.7:1 → 5.62:1
    "#FC6C6C": "#C62828",
    "#D32F2F": "#9B1C1C",
    "#FF9800": "#B45309",   # 警告橙：2.07:1 → 4.52:1
    "#FC9C04": "#B45309",
    "#FF6B6B": "#C62828",
    "#FF1744": "#C62828",   # 亮红：白字 3.85:1 → 5.62:1
    "#F57C00": "#92400E",
    "#047CCC": "#0369A1",   # 信息蓝：4.30:1 → 4.90:1
    "#2196F3": "#0369A1",
    "#009688": "#00695C",   # 青：白字 3.55:1 → 5.90:1
    "#00796B": "#004D40",
}


# 自带主题管理的控件（按 objectName）：它们的样式表由自己按当前主题生成，
# 绝不能被 strip_conflicting_stylesheets 的"清浅色外壳色"逻辑动到。
_SELF_THEMED_OBJECTS = ("ocPanel",)


def _match_marker(ss: str, markers) -> bool:
    """大小写不敏感地匹配颜色标记（源码里 #f0f0f0 与 #F0F0F0 混用，
    大小写敏感匹配会漏掉一半 —— 实测漏掉了 toolbar 的浅色底）。"""
    low = ss.lower()
    return any(m.lower() in low for m in markers)


def _remap_contrast_colors(ss: str) -> str:
    """把语义色替换成可访问性达标的深色变体（大小写不敏感）。"""
    out = ss
    for old, new in _CONTRAST_FIX.items():
        out = re.sub(re.escape(old), new, out, flags=re.IGNORECASE)
    return out


def _in_fixed_height_ancestor(w) -> bool:
    """祖先链里是否存在"高度固定"的容器。

    如果是，就**不能**靠提高 minimumHeight 让文字装下 —— 容器长不高，
    提高最小值只会把子控件顶出容器边界（实测：`setFixedSize(300,150)`
    的功能按钮里，描述标签被顶出 8px，最后一行字被按钮边缘切掉）。
    """
    seen = 0
    try:
        p = w.parentWidget()
    except Exception:
        return False
    while p is not None and seen < 24:
        seen += 1
        try:
            lo, hi = int(p.minimumHeight()), int(p.maximumHeight())
            if hi < 16777215 and lo >= hi:
                return True
        except Exception:
            pass
        try:
            p = p.parentWidget()
        except Exception:
            break
    return False


def ensure_text_fits(root) -> dict:
    """字号被皮肤放大后，让"装不下文字"的标签自动长高，避免裁字。

    只处理**确实超出**的控件（need > height），把 minimumHeight 提到所需高度；
    父容器若是"最小高度"型（非固定），会随之自然撑开。

    ⚠️ 但若祖先里有**高度固定**的容器（`setFixedSize` / `setFixedHeight`），
    则跳过 —— 那种情况长不上去，强行提最小值会把子控件顶出容器
    （见 `_in_fixed_height_ancestor` 的说明）。这类"内容比容器大"的
    布局问题应由容器自己放宽尺寸解决，不由本函数掩盖。
    """
    if root is None:
        return {"fixed": 0}
    from src.core.qt_compat.QtCore import QRect, Qt as _Qt
    from src.core.qt_compat.QtWidgets import QLabel, QAbstractButton, QWidget

    fixed = 0
    skipped = 0
    try:
        widgets = [root] + list(root.findChildren(QWidget))
    except Exception:
        return {"fixed": 0}

    for w in widgets:
        if not isinstance(w, (QLabel, QAbstractButton)):
            continue
        try:
            t = str(w.text() or "")
        except Exception:
            continue
        if "<" in t and ">" in t:
            t = re.sub(r"<[^>]+>", "", t)
        t = t.strip()
        if len(t) < 2:
            continue
        if _in_fixed_height_ancestor(w):
            skipped += 1
            continue
        try:
            fm = w.fontMetrics()
            if "\n" in t:
                # 多行标签：**无条件**保证最小高度 —— init_ui 阶段布局尚未计算，
                # 用 w.height() 判断会误判（实测漏掉 3 处裁字）。
                need = len(t.split("\n")) * fm.lineSpacing() + 2
                if need > (w.minimumHeight() or 0):
                    w.setMinimumHeight(int(need))
                    fixed += 1
                continue
            wrap = False
            try:
                wrap = bool(w.wordWrap())
            except Exception:
                wrap = False
            if wrap:
                need = fm.boundingRect(
                    QRect(0, 0, max(10, w.contentsRect().width()), 100000),
                    int(_Qt.TextWordWrap), t).height() + 2
                if need > (w.minimumHeight() or 0):
                    w.setMinimumHeight(int(need))
                    fixed += 1
                continue
            # 单行：只在实际被压扁时才补
            need = fm.height() + 2
            if need > w.height() + 1 and need > (w.minimumHeight() or 0):
                w.setMinimumHeight(int(need))
                fixed += 1
        except Exception:
            continue
    return {"fixed": fixed, "skipped_fixed_ancestor": skipped}


_NUMERIC_RE = re.compile(r"\d+\.\d+|\d{2,}")


def apply_data_font(root) -> dict:
    r"""把**数值型文本**的标签/按钮自动切到等宽数据字体。

    判定：文本中出现小数（`\d+\.\d+`）或 ≥2 位连续数字（`\d{2,}`）。
    这样"置信度: 0.82""面积 12.4""样本 24 个"会获得等宽读数感，
    而纯文字标签（新建项目/项目管理）不受影响。
    """
    if root is None:
        return {"data_font": 0}
    from src.core.qt_compat.QtWidgets import QLabel, QAbstractButton, QWidget

    n = 0
    try:
        widgets = [root] + list(root.findChildren(QWidget))
    except Exception:
        return {"data_font": 0}
    for w in widgets:
        if not isinstance(w, (QLabel, QAbstractButton)):
            continue
        try:
            t = str(w.text() or "")
        except Exception:
            continue
        if "<" in t and ">" in t:
            t = re.sub(r"<[^>]+>", "", t)
        if not _NUMERIC_RE.search(t):
            continue
        try:
            cur = w.font()
            if "Cascadia" in (cur.family() or ""):
                continue
            w.setFont(data_font(SIZE_BODY, 600))
            n += 1
        except Exception:
            continue
    return {"data_font": n}


def strip_conflicting_stylesheets(root: QWidget) -> dict:
    """清理与全局皮肤冲突的**局部硬编码样式**，让全局 QSS 生效。

    策略：只清"浅色外壳色"而**不含**功能性语义色的内联样式表；
    含语义色（成功绿/危险红/警告橙等）的一律保留，避免破坏状态色含义。

    Returns:
        {"scanned": n, "stripped": n, "kept": n}
    """
    if not SKIN_ENABLED or root is None:
        return {"scanned": 0, "stripped": 0, "kept": 0}
    from src.core.qt_compat.QtWidgets import QWidget as _QW

    scanned = stripped = kept = 0
    try:
        widgets = [root] + list(root.findChildren(_QW))
    except Exception:
        widgets = [root]

    for w in widgets:
        try:
            ss = w.styleSheet()
        except Exception:
            continue
        if not ss or len(ss) < 12:
            continue
        # ---- 自带主题管理的控件：**绝不清理** ----
        # 这类控件的样式表是"按当前主题生成"的（内含成对/多套颜色），
        # 一旦被"清浅色外壳色"的逻辑动到，主题感知就断了。
        # 实测踩过：opencode 页脚面板的样式表含 `#FFFFFF`（在 _LIGHT_MARKERS 里）
        # → 会被清掉 → 面板退回硬编码色，浅色主题下标题对比度 1.09:1。
        try:
            if (w.objectName() in _SELF_THEMED_OBJECTS
                    or bool(w.property("skin_self_themed"))):
                kept += 1
                continue
        except Exception:
            pass
        scanned += 1
        if _match_marker(ss, _KEEP_MARKERS):
            kept += 1
            new_ss = _remap_contrast_colors(ss)
            # 语义色控件（成功绿/危险红/警告橙）：
            # 裸声明列表（无选择器）在父级合成时解析不可靠 —— 实测页面合成里
            # `background-color:#2E7D32;color:white` 会渲染成浅灰底白字。
            # 显式包一层 QPushButton 选择器即可稳定生效。
            #
            # ⚠️ 不要再追加 `background-image: none`：
            # 全局 QSS 已不再给按钮设背景（改由 3D 引擎绘制），
            # 而显式的 background-image:none 会让 Qt 把整个 background 规则一起重置，
            # 语义色消失、露出引擎的浅色玻璃（实测：合成渲染成 #E4F1FB）。
            body = new_ss.strip()
            if body and "{" not in body:
                body = "QPushButton { " + body.replace("\n", " ").strip() + " }"
            if body != ss:
                try:
                    w.setStyleSheet(body)
                except Exception:
                    pass
            continue
        if _match_marker(ss, _LIGHT_MARKERS):
            try:
                w.setStyleSheet("")
                stripped += 1
            except Exception:
                pass
        else:
            kept += 1
    return {"scanned": scanned, "stripped": stripped, "kept": kept}
