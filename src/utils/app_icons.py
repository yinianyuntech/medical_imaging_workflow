#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""app_icons —— 应用级矢量图标系统（主题感知 · 零外部资源）。

设计目标
--------
* **零资源依赖**：图标以 SVG 源码内联在模块里，随代码打包（PyInstaller 无需额外
  收集 assets/），也避免路径在 frozen/源码两种形态下不一致。
* **主题感知**：图标在渲染时按当前皮肤调色板取色（`current_palette()`），
  深色主题取亮色描边、浅色主题取深色描边；主题热切换后调用 `refresh_all()`
  即可全量重绘已注册图标。
* **单一色板**：24x24 viewBox、2px 描边、圆头圆角 —— 所有图标共用同一视觉语言，
  在 14~20px 小尺寸下仍清晰。

用法
----
    from src.utils.app_icons import apply_icon, icon, icon_pixmap

    apply_icon(self.add_project_button, "plus")                 # 跟随文字色
    apply_icon(self.process_btn, "play", role="on")             # 白色（实色按钮上）
    self.setWindowIcon(icon("layers", role="accent", size=24))  # 任意取用
    label.setPixmap(icon_pixmap("database", role="chip", size=48))  # 大图标

主题热切换：`refresh_all()` 遍历注册表重设图标（死对象自动清理）。
"""

from __future__ import annotations

import weakref
from typing import List, Optional, Tuple

from src.core.qt_compat.QtCore import QRectF, QSize, Qt
from src.core.qt_compat.QtGui import QColor, QIcon, QPainter, QPixmap

try:  # PyQt6 优先；兼容旧环境 PyQt5
    from PyQt6.QtSvg import QSvgRenderer as _QSvgRenderer  # type: ignore
except Exception:  # noqa: BLE001
    try:
        from PyQt5.QtSvg import QSvgRenderer as _QSvgRenderer  # type: ignore
    except Exception:  # noqa: BLE001
        _QSvgRenderer = None  # type: ignore


# ============================================================ 图标定义
# 24x24 viewBox / 2px 描边。fill="none" 走描边；需要实心的形状单独标 fill。
_SVG_HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round">'
)

_ICONS = {
    # ---- 通用操作 ----
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "check": '<path d="M4.5 12.5l5 5 10-11"/>',
    "refresh": ('<polyline points="20.5 4.5 20.5 10 15 10"/>'
                '<path d="M19.7 15a8.5 8.5 0 1 1-1.9-9.1l2.7 4.1"/>'),
    "trash": ('<path d="M4 7h16"/>'
              '<path d="M9.5 7V5.6A1.1 1.1 0 0 1 10.6 4.5h2.8a1.1 1.1 0 0 1 1.1 1.1V7"/>'
              '<path d="M6.5 7l.9 12.1a1.1 1.1 0 0 0 1.1 1h7a1.1 1.1 0 0 0 1.1-1L17.5 7"/>'
              '<path d="M10.2 11v5.6M13.8 11v5.6"/>'),
    "folder": ('<path d="M3.5 7a1.8 1.8 0 0 1 1.8-1.8h3.9L11.3 7.9h7.4a1.8 1.8 0 0 1 1.8 1.8'
               'v8.5a1.8 1.8 0 0 1-1.8 1.8H5.3a1.8 1.8 0 0 1-1.8-1.8z"/>'),
    "folder-plus": ('<path d="M3.5 7a1.8 1.8 0 0 1 1.8-1.8h3.9L11.3 7.9h7.4a1.8 1.8 0 0 1 1.8 1.8'
                    'v8.5a1.8 1.8 0 0 1-1.8 1.8H5.3a1.8 1.8 0 0 1-1.8-1.8z"/>'
                    '<path d="M12 11.5v6M9 14.5h6"/>'),
    "folder-open": ('<path d="M3.5 7a1.8 1.8 0 0 1 1.8-1.8h3.9L11.3 7.9h7.4a1.8 1.8 0 0 1 1.8 1.8'
                    'v1.3H7.2a1.8 1.8 0 0 0-1.7 1.25L3.5 18z"/>'
                    '<path d="M7.2 11l-2 7.1a1.3 1.3 0 0 0 1.25 1.65h10.9'
                    'a1.8 1.8 0 0 0 1.72-1.28L21.5 11z"/>'),
    "file": ('<path d="M6.5 3.5h7.2L18.5 8.4v12.1h-12z"/>'
             '<path d="M13.4 3.5v5.1h5.1"/>'),
    "file-text": ('<path d="M6.5 3.5h7.2L18.5 8.4v12.1h-12z"/>'
                  '<path d="M13.4 3.5v5.1h5.1"/>'
                  '<path d="M9.5 12.6h6M9.5 16.2h6"/>'),
    "save": ('<path d="M5 3.5h11l3.5 3.5v13.5h-14.5z"/>'
             '<path d="M8 3.5v5.6h7V3.5"/>'
             '<path d="M8 20.5V14h8v6.5"/>'),
    "upload": ('<path d="M12 15.5V4.5M7.5 9L12 4.5 16.5 9"/>'
               '<path d="M4.5 20h15"/>'),
    "download": ('<path d="M12 4.5V15.5M7.5 11L12 15.5 16.5 11"/>'
                 '<path d="M4.5 20h15"/>'),
    "import": ('<path d="M12 4v9.5M7.5 9.5L12 14l4.5-4.5"/>'
               '<path d="M4.5 17.5v1.3a1.7 1.7 0 0 0 1.7 1.7h11.6a1.7 1.7 0 0 0 1.7-1.7'
               'v-1.3"/>'),
    "export": ('<path d="M12 14V4.5M7.5 9L12 4.5 16.5 9"/>'
               '<path d="M4.5 17.5v1.3a1.7 1.7 0 0 0 1.7 1.7h11.6a1.7 1.7 0 0 0 1.7-1.7'
               'v-1.3"/>'),
    "copy": ('<rect x="8.8" y="8.8" width="10.7" height="11.7" rx="1.6"/>'
             '<path d="M5.2 15.2H4.6a1.6 1.6 0 0 1-1.6-1.6V4.8a1.6 1.6 0 0 1 1.6-1.6h8.6'
             'a1.6 1.6 0 0 1 1.6 1.6v.6"/>'),
    "search": '<circle cx="10.5" cy="10.5" r="6"/>'
              '<path d="M15 15l5.5 5.5"/>',
    "settings": ('<path d="M4.5 7h8.3M17.5 7h2M4.5 17h1.3M10.5 17h9"/>'
                 '<circle cx="15.2" cy="7" r="2.3"/>'
                 '<circle cx="8.3" cy="17" r="2.3"/>'),
    "filter": '<path d="M4 5h16l-6 7.2v6L10 20v-7.8z"/>',
    "eye": ('<path d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12z"/>'
            '<circle cx="12" cy="12" r="3"/>'),
    "info": ('<circle cx="12" cy="12" r="8.5"/>'
             '<path d="M12 11.2v5.3"/><path d="M12 7.9h.01"/>'),
    "help": ('<circle cx="12" cy="12" r="8.5"/>'
             '<path d="M9.6 9.3a2.6 2.6 0 1 1 3.6 2.4c-.85.42-1.2 1-1.2 1.8v.3"/>'
             '<path d="M12 16.6h.01"/>'),
    "warning": ('<path d="M12 4.2l9 15.6H3z"/>'
                '<path d="M12 10v4.4"/><path d="M12 17.4h.01"/>'),
    "clock": ('<circle cx="12" cy="12" r="8.5"/>'
              '<path d="M12 7.4V12l3.1 2.1"/>'),
    "home": '<path d="M4 11l8-7 8 7"/><path d="M6.2 9.4V20h11.6V9.4"/>',
    # ---- 导航 ----
    "chevron-left": '<path d="M14.5 6l-6 6 6 6"/>',
    "chevron-right": '<path d="M9.5 6l6 6-6 6"/>',
    "arrow-left": '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    "arrow-right": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "arrow-up": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "arrow-down": '<path d="M12 5v14M6 13l6 6 6-6"/>',
    # ---- 业务/领域 ----
    "database": ('<ellipse cx="12" cy="5.6" rx="7.6" ry="2.9"/>'
                 '<path d="M4.4 5.6v12.8c0 1.6 3.4 2.9 7.6 2.9s7.6-1.3 7.6-2.9V5.6"/>'
                 '<path d="M4.4 12c0 1.6 3.4 2.9 7.6 2.9s7.6-1.3 7.6-2.9"/>'),
    "image": ('<rect x="3.5" y="4.5" width="17" height="15" rx="2"/>'
              '<path d="M3.5 15.8l4.9-4.9 3.4 3.4 3.5-3.5 5.2 5.2"/>'
              '<circle cx="9" cy="9.4" r="1.5"/>'),
    "scan-text": ('<path d="M4 8V6.3A2.3 2.3 0 0 1 6.3 4H8M16 4h1.7A2.3 2.3 0 0 1 20 6.3V8'
                  'M20 16v1.7a2.3 2.3 0 0 1-2.3 2.3H16M8 20H6.3A2.3 2.3 0 0 1 4 17.7V16"/>'
                  '<path d="M8 9.6h8M8 12.6h8M8 15.6h5"/>'),
    "layers": ('<path d="M12 3.2l8.5 4.4L12 12 3.5 7.6z"/>'
               '<path d="M3.5 12l8.5 4.4 8.5-4.4"/>'
               '<path d="M3.5 16.4L12 20.8l8.5-4.4"/>'),
    "cpu": ('<rect x="7" y="7" width="10" height="10" rx="1.6"/>'
            '<rect x="10.6" y="10.6" width="2.8" height="2.8"/>'
            '<path d="M10 3.6V7M14 3.6V7M10 17v3.4M14 17v3.4M3.6 10H7M3.6 14H7M17 10h3.4'
            'M17 14h3.4"/>'),
    "sparkles": ('<path d="M11 3.6l1.75 4.65L17.4 10l-4.65 1.75L11 16.4l-1.75-4.65L4.6 10'
                 'l4.65-1.75z"/>'
                 '<path d="M18.4 14.6l.85 2.15 2.15.85-2.15.85-.85 2.15-.85-2.15-2.15-.85'
                 '2.15-.85z"/>'),
    "flask": ('<path d="M9.6 3.6h4.8M10.7 3.6v6.1L5.9 18a1.7 1.7 0 0 0 1.5 2.5h9.2'
              'a1.7 1.7 0 0 0 1.5-2.5l-4.8-8.3V3.6"/>'
              '<path d="M8.2 14.6h7.6"/>'),
    "chart": ('<path d="M4.5 4v15.5a1 1 0 0 0 1 1H20"/>'
              '<path d="M9 16.5v-5M13.4 16.5V7.8M17.8 16.5v-3.6"/>'),
    "table": ('<rect x="3.5" y="4.5" width="17" height="15" rx="2"/>'
              '<path d="M3.5 9.4h17M9.6 9.4v10.1M3.5 14.4h17"/>'),
    "crosshair": ('<circle cx="12" cy="12" r="7"/>'
                  '<path d="M12 2.5V6M12 18v3.5M2.5 12H6M18 12h3.5"/>'),
    "wand": ('<path d="M14.8 4.4l4.8 4.8L8.4 20.4l-4.8-4.8z"/>'
             '<path d="M6.2 2.8v3M4.7 4.3h3M19 15.6v3M17.5 17.1h3"/>'),
    "plug": ('<path d="M9 3.5V8M15 3.5V8"/>'
             '<path d="M6.4 8h11.2v3.1a5.6 5.6 0 0 1-11.2 0z"/>'
             '<path d="M12 16.7v3.8"/>'),
    "edit": ('<path d="M4 20.5h4L20.5 8 16 3.5 4 16z"/>'
             '<path d="M13.6 5.9l4.5 4.5"/>'),
    "send": ('<path d="M3.5 11.4L20.6 4l-7.3 16.6-2.6-6.7z"/>'
             '<path d="M10.7 13.9L20.6 4"/>'),
    "robot": ('<rect x="4.5" y="7.5" width="15" height="11" rx="2.4"/>'
              '<path d="M12 3.5v4"/><circle cx="12" cy="3" r="0.9"/>'
              '<path d="M9 12.2h.01M15 12.2h.01"/>'
              '<path d="M9.5 15.4h5"/>'),
    "theme": ('<circle cx="12" cy="12" r="4.2"/>'
              '<path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4'
              'M5.2 5.2L6.9 6.9M17.1 17.1l1.7 1.7M18.8 5.2l-1.7 1.7M6.9 17.1l-1.7 1.7"/>'),
    "play": '<path d="M8 5.3v13.4L19 12z" fill="{c}" stroke="none"/>',
    "stop": '<rect x="7" y="7" width="10" height="10" rx="1.6" fill="{c}" stroke="none"/>',
    "idea": ('<path d="M9 18.5h6M10 21h4"/>'
             '<path d="M12 3.5a6 6 0 0 1 3.6 10.8c-.7.55-1.1 1.2-1.1 2.2h-5'
             'c0-1-.4-1.65-1.1-2.2A6 6 0 0 1 12 3.5z"/>'),
    "medcross": ('<rect x="3.8" y="3.8" width="16.4" height="16.4" rx="4.4"/>'
                 '<path d="M12 8.2v7.6M8.2 12h7.6"/>'),
    "pulse": '<path d="M3 12.5h4.2l2.3-6 3.8 11.6 2.2-5.6H21"/>',
    "book": ('<path d="M4.5 5.5A2 2 0 0 1 6.5 3.5H19.5v15H6.5a2 2 0 0 0-2 2z"/>'
             '<path d="M4.5 5.5V20.5"/>'),
}

_ALIASES = {
    "add": "plus",
    "delete": "trash",
    "remove": "trash",
    "reload": "refresh",
    "sync": "refresh",
    "next": "chevron-right",
    "prev": "chevron-left",
    "ok": "check",
    "done": "check",
    "x": "close",
    "clear": "close",
    "primary": "play",
    "run": "play",
    "start": "play",
    "magic": "wand",
    "template": "wand",
    "ai": "sparkles",
    "summary": "cpu",
    "preview": "eye",
    "feedback": "chart",
    "clean": "sparkles",
    "project": "folder",
    "sample": "database",
    "dicom": "image",
    "text": "file-text",
    "ocr": "scan-text",
    "seg": "layers",
}


# ============================================================ 调色板 & 渲染

def _role_color(role: str) -> str:
    """把语义角色映射为当前主题的实际颜色。"""
    fallback = {
        "text": "#E8EEF7", "dim": "#B3C6E0", "strong": "#FFFFFF",
        "accent": "#1E90FF", "accent_hi": "#5CC8FF", "chip": "#A8E0FF",
        "on": "#FFFFFF", "on_dim": "rgba(255,255,255,0.78)",
        "success": "#F2FFF6", "danger": "#FFF3F3", "warning": "#FFF9EF",
        "muted": "#9AA9BF",
    }
    try:
        from src.utils.skeuomorphic import current_palette
        p = current_palette()
        table = {
            "text": p.text,
            "dim": p.text_dim,
            "strong": p.text_strong,
            "accent": p.accent,
            "accent_hi": p.accent_hi,
            "chip": p.chip_text,
            "muted": p.s200,
        }
        if role in table:
            return table[role]
    except Exception:  # noqa: BLE001
        pass
    return fallback.get(role, fallback["text"])


def _resolve_name(name: str) -> str:
    n = str(name or "").strip().lower()
    n = _ALIASES.get(n, n)
    if n not in _ICONS:
        n = "info"
    return n


def _svg_data(name: str) -> bytes:
    body = _ICONS[name]
    # play/stop 等实心形状把当前色写进 fill 占位符；占位色随意，最终统一被 SourceIn 染色
    if "{c}" in body:
        body = body.replace("{c}", "#FFFFFF")
    # 描边色同样占位化（渲染后会被整体染色，颜色本身不重要）
    return (_SVG_HEAD.format(c="#000000") + body + "</svg>").encode("utf-8")


_pixmap_cache = {}
_icon_cache = {}


def _dpr() -> float:
    try:
        from src.core.qt_compat.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            scr = app.primaryScreen()
            if scr is not None:
                return max(2.0, float(scr.devicePixelRatio() or 1.0))
    except Exception:  # noqa: BLE001
        pass
    return 2.0


def _fallback_glyph(painter: QPainter, name: str, size: float) -> None:
    """QtSvg 不可用时的退路：画一个圆角方块 + 首字母（物理像素坐标）。"""
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#FFFFFF"))
    r = size * 0.14
    painter.drawRoundedRect(1, 1, size - 2, size - 2, r, r)
    painter.setPen(QColor("#000000"))
    f = painter.font()
    f.setPointSizeF(max(5.0, size * 0.42))
    f.setBold(True)
    painter.setFont(f)
    painter.drawText(0, 0, int(size), int(size), Qt.AlignmentFlag.AlignCenter,
                     (name or "?")[:1].upper())


def pixmap(name: str, role: str = "text", size: int = 16) -> QPixmap:
    """渲染命名图标为 QPixmap（逻辑尺寸 size，带 DPR 缩放，线条清晰）。"""
    key = _resolve_name(name)
    color = _role_color(role)
    sz = max(8, int(size))
    dp = _dpr()
    ck = (key, color, sz, dp)
    hit = _pixmap_cache.get(ck)
    if hit is not None:
        return hit
    pm = QPixmap(int(round(sz * dp)), int(round(sz * dp)))
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    try:
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        w = float(pm.width())
        h = float(pm.height())
        if _QSvgRenderer is not None:
            try:
                # ⚠️ 必须在**未打 DPR 标记**的物理坐标系里显式给目标矩形渲染。
                # 先 setDevicePixelRatio 会让 QPainter 视口/世界坐标错位，
                # SVG 会偏移且被放大（实测：close 图标画出 53..127 而非 26..101）。
                rend = _QSvgRenderer(_svg_data(key))
                rend.render(painter, QRectF(0.0, 0.0, w, h))
            except Exception:  # noqa: BLE001
                _fallback_glyph(painter, key, w)
        else:
            _fallback_glyph(painter, key, w)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(QRectF(0.0, 0.0, w, h), QColor(color))
    finally:
        painter.end()
    # 染色完成后再标记 DPR（逻辑尺寸 = 物理尺寸 / dpr）
    pm.setDevicePixelRatio(dp)
    _pixmap_cache[ck] = pm
    return pm


def icon_pixmap(name: str, role: str = "text", size: int = 16) -> QPixmap:
    """pixmap() 的语义化别名（给 QLabel.setPixmap 用的大图标）。"""
    return pixmap(name, role, size)


def icon(name: str, role: str = "text", size: int = 16) -> QIcon:
    """构造 QIcon。缓存同参数结果，避免重复渲染。"""
    key = _resolve_name(name)
    color = _role_color(role)
    sz = max(8, int(size))
    ck = (key, color, sz)
    hit = _icon_cache.get(ck)
    if hit is not None:
        return hit
    ic = QIcon(pixmap(key, role, sz))
    _icon_cache[ck] = ic
    return ic


# ============================================================ 注册 & 主题热刷新
# 注册表条目：(holder, name, role, size)
#   holder 二选一：
#     * weakref.ref(控件) —— 控件由 Python 创建、被父级持有，weakref 稳定且不泄漏；
#     * 强引用（QAction）—— **必须**！C++ 侧创建的 QAction（如 QMenu.menuAction()、
#       或父级为 C++ 的菜单项）其 Python 包装器一旦无引用即被回收，weakref 立刻
#       死亡 → refresh_all 静默跳过 → 换主题后菜单图标仍是旧色（浅色下"洗白"不可见）。
#       实测：8 个顶级菜单 action 全部丢失（87 注册 / 79 刷新）。
_registry: List[Tuple[object, str, str, int]] = []


def _obj_of(holder):
    """holder → 目标对象；weakref 已死返回 None。"""
    if isinstance(holder, weakref.ReferenceType):
        return holder()
    return holder


def _sweep_dead() -> None:
    alive = []
    for entry in _registry:
        obj = _obj_of(entry[0])
        if obj is None:
            continue
        try:
            # C++ 对象已删除时，包装器仍在但访问会抛 RuntimeError
            obj.objectName()
        except RuntimeError:
            continue
        except Exception:  # noqa: BLE001
            pass
        alive.append(entry)
    _registry[:] = alive


def apply_icon(target, name: str, role: str = "text", size: int = 16,
               icon_size: Optional[bool] = None) -> QIcon:
    """给按钮/动作设置图标，并登记到主题热刷新注册表。

    * QPushButton：同时设置 iconSize（默认 True，尺寸跟随 size）。
    * QAction：只设置图标（菜单图标尺寸由样式决定）。
    返回设置的 QIcon，方便调用方复用。
    """
    ic = icon(name, role, size)
    try:
        target.setIcon(ic)
        is_widget = hasattr(target, "setIconSize") and hasattr(target, "objectName")
        if is_widget and (icon_size is None or icon_size):
            target.setIconSize(QSize(int(size), int(size)))
    except Exception:  # noqa: BLE001
        return ic
    try:
        if is_widget:
            holder = weakref.ref(target)
        else:
            # QAction（无 setIconSize）：强引用，防止 C++ 创建的包装器被 GC
            holder = target
        _registry.append((holder, _resolve_name(name), role, int(size)))
    except TypeError:  # 不可弱引用的对象（极少见）
        try:
            _registry.append((target, _resolve_name(name), role, int(size)))
        except Exception:  # noqa: BLE001
            pass
    return ic


def apply_pixmap(label, name: str, role: str = "text", size: int = 16) -> QPixmap:
    """给 QLabel 设置图标位图，并登记到主题热刷新注册表。

    QLabel 没有 setIcon（不随主题自动换色），必须显式登记，
    否则主题热切换后位图仍是旧主题的描边色（浅色下会"洗白"看不见）。
    """
    pm = pixmap(name, role, size)
    try:
        label.setPixmap(pm)
    except Exception:  # noqa: BLE001
        return pm
    try:
        _registry.append((weakref.ref(label), _resolve_name(name), role, int(size)))
    except TypeError:
        pass
    return pm


def refresh_all() -> int:
    """主题热切换后全量重设已注册图标。返回成功刷新数量。"""
    global _pixmap_cache, _icon_cache
    _pixmap_cache = {}
    _icon_cache = {}
    n = 0
    _sweep_dead()
    for entry in list(_registry):
        holder, name, role, size = entry
        obj = _obj_of(holder)
        if obj is None:
            continue
        try:
            if hasattr(obj, "setIcon"):
                # 按钮 / QAction
                obj.setIcon(icon(name, role, size))
                if hasattr(obj, "setIconSize"):
                    obj.setIconSize(QSize(size, size))
            elif hasattr(obj, "setPixmap"):
                # QLabel 位图
                obj.setPixmap(pixmap(name, role, size))
            else:
                continue
            n += 1
        except Exception:  # noqa: BLE001
            continue
    _sweep_dead()
    return n


def names() -> List[str]:
    """全部可用图标名（不含别名）。"""
    return sorted(_ICONS.keys())
