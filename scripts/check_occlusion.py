#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_occlusion.py —— 显示区块遮挡 / 挤压 / 溢出自动检测。

在真实 windows 平台下完整构建 MainWindow，逐页激活并强制布局，然后按四类规则体检：

  R1 挤压( squeezed )   —— 设了固定/最小尺寸的控件被渲染得更小
  R2 溢出( overflow )   —— 子控件矩形超出父容器矩形（父容器不可滚动时）
  R3 同级重叠( overlap ) —— 同一父容器下两个可见同级控件互相遮挡
  R4 塌陷( collapsed )  —— 可见控件被压成 <=2px

豁免：
  * QScrollArea 的 viewport 内的内容高于视口 = 正常滚动，不算遮挡；
  * 明确的对象叠加（如浮层 overlay）按 objectName 白名单跳过。

用法：python scripts/check_occlusion.py [--json 输出路径]
退出码 0 = 无问题。
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("MIMW_SKIN", "metal")

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.core.qt_compat.QtCore import Qt, QRect  # noqa: E402
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QScrollArea, QAbstractScrollArea, QStackedWidget,
    QSplitter, QGroupBox, QTabWidget,
)

# 允许叠加的 objectName（浮层、覆盖层）
OVERLAY_WHITELIST = {"modelLoadingOverlay", "mimwOverlay"}
MIN_OVERLAP_PX = 3


def _is_overlay(w) -> bool:
    try:
        name = w.objectName() or ""
    except Exception:
        return False
    return name in OVERLAY_WHITELIST or "overlay" in name.lower()


def _inside_scroll_viewport(w) -> bool:
    """控件是否位于某个滚动视口内（其内容超出视口属于正常滚动）。"""
    p = w.parentWidget()
    depth = 0
    while p is not None and depth < 40:
        try:
            if p.objectName() == "qt_scrollarea_viewport":
                return True
            if isinstance(p, QScrollArea):
                return True
        except Exception:
            pass
        p = p.parentWidget()
        depth += 1
    return False


def _ancestor_fixed(w):
    """返回祖先中被固定尺寸的控件（用于判断挤压是否由祖先滚动造成）。"""
    p = w.parentWidget()
    depth = 0
    while p is not None and depth < 20:
        if _inside_scroll_viewport(p):
            return True
        p = p.parentWidget()
        depth += 1
    return False


def check_page(page: QWidget, page_name: str, issues: list):
    """对单个页面做四类体检。"""
    try:
        widgets = [page] + list(page.findChildren(QWidget))
    except Exception:
        return

    visible = []
    for w in widgets:
        try:
            if not w.isVisible() or w.width() <= 0 or w.height() <= 0:
                continue
        except Exception:
            continue
        visible.append(w)

    vis_set = set(id(x) for x in visible)

    for w in visible:
        if _is_overlay(w):
            continue
        try:
            r = w.rect()
            ww, hh = w.width(), w.height()
            name = w.objectName() or ""
            cls = type(w).__name__
            label = f"{cls}[{name}]" if name else cls

            # ---- R4 塌陷 ----
            if ww <= 2 or hh <= 2:
                issues.append({
                    "rule": "R4_collapsed", "page": page_name, "widget": label,
                    "detail": f"尺寸被压成 {ww}x{hh}",
                })
                continue

            # ---- R1 挤压 ----
            minw, minh = w.minimumWidth(), w.minimumHeight()
            if minw > 0 and ww < minw - 1:
                if not _inside_scroll_viewport(w):
                    issues.append({
                        "rule": "R1_squeezed", "page": page_name, "widget": label,
                        "detail": f"宽 {ww} < 最小宽 {minw}",
                    })
            if minh > 0 and hh < minh - 1:
                if not _inside_scroll_viewport(w):
                    issues.append({
                        "rule": "R1_squeezed", "page": page_name, "widget": label,
                        "detail": f"高 {hh} < 最小高 {minh}",
                    })

            # ---- R2 溢出 ----
            par = w.parentWidget()
            if par is not None and id(par) in vis_set and not _inside_scroll_viewport(w):
                try:
                    pg = w.geometry()
                    pr = par.rect()
                    if pg.left() < pr.left() - 1 or pg.top() < pr.top() - 1 or \
                       pg.right() > pr.right() + 1 or pg.bottom() > pr.bottom() + 1:
                        over = (
                            max(0, pr.left() - pg.left()) + max(0, pg.right() - pr.right()),
                            max(0, pr.top() - pg.top()) + max(0, pg.bottom() - pr.bottom()),
                        )
                        if over[0] > 4 or over[1] > 4:
                            issues.append({
                                "rule": "R2_overflow", "page": page_name, "widget": label,
                                "detail": (f"超出父 {type(par).__name__} "
                                           f"水平{over[0]}px 垂直{over[1]}px"),
                            })
                except Exception:
                    pass
        except Exception:
            continue

    # ---- R3 同级重叠（滚动区内同样不允许互相遮挡）----
    by_parent = {}
    for w in visible:
        if _is_overlay(w):
            continue
        try:
            par = w.parentWidget()
            if par is None or id(par) not in vis_set:
                continue
            by_parent.setdefault(id(par), (par, []))[1].append(w)
        except Exception:
            continue

    for _, (par, kids) in by_parent.items():
        n = len(kids)
        if n < 2 or n > 60:
            continue
        for i in range(n):
            for j in range(i + 1, n):
                a, b = kids[i], kids[j]
                try:
                    # QSplitter 的子项由分割器管理，允许邻接
                    if isinstance(par, QSplitter):
                        continue
                    ga, gb = a.geometry(), b.geometry()
                    inter = ga.intersected(gb)
                    if inter.width() > MIN_OVERLAP_PX and inter.height() > MIN_OVERLAP_PX:
                        la = a.objectName() or type(a).__name__
                        lb = b.objectName() or type(b).__name__
                        issues.append({
                            "rule": "R3_overlap", "page": page_name,
                            "widget": f"{la} <-> {lb}",
                            "detail": (f"重叠 {inter.width()}x{inter.height()}px "
                                       f"(父 {type(par).__name__})"),
                        })
                except Exception:
                    continue


def self_test() -> int:
    """用**故意植入**的缺陷验证检测器本身有效（防止假阴性）。"""
    from src.core.qt_compat.QtWidgets import QWidget as _W, QPushButton, QLabel

    host = _W()
    host.resize(400, 300)

    # 植入 1：同级重叠
    a = QPushButton(host)
    a.setObjectName("plantedA")
    a.setGeometry(10, 10, 200, 60)
    b = QPushButton(host)
    b.setObjectName("plantedB")
    b.setGeometry(150, 40, 200, 60)   # 与 a 重叠 60x30

    # 植入 2：挤压（最小高 150，实际 30）
    c = QPushButton(host)
    c.setObjectName("plantedC")
    c.setMinimumHeight(150)
    c.setGeometry(10, 200, 200, 30)

    # 植入 3：溢出父容器
    d = QPushButton(host)
    d.setObjectName("plantedD")
    d.setGeometry(380, 280, 120, 60)  # 越界

    # 植入 4：文字横向截断（不换行）
    e = QLabel(host)
    e.setObjectName("plantedE")
    e.setWordWrap(False)
    e.setText("这是一段非常长的用于验证文字截断检测的中文文本，应该远远超出控件宽度")
    e.setGeometry(10, 240, 80, 22)

    # 植入 5：文字纵向裁切（自动换行但高度不足）
    f = QLabel(host)
    f.setObjectName("plantedF")
    f.setWordWrap(True)
    f.setText("这是一段会自动换行的长文本用于验证纵向裁切检测" * 3)
    f.setGeometry(10, 266, 120, 16)

    # 植入 6：多行文本纵向裁切（\n 换行 + wordWrap=False，曾被漏检）
    gm = QLabel(host)
    gm.setObjectName("plantedG")
    gm.setWordWrap(False)
    gm.setText("项目: 默认项目\nID: default\n描述: 系统默认项目")
    gm.setGeometry(10, 288, 200, 26)

    host.show()
    _app = QApplication.instance()
    for _ in range(6):
        _app.processEvents()

    issues = []
    check_page(host, "selftest", issues)
    check_text_fit(host, "selftest", issues)
    rules = sorted({i["rule"] for i in issues})
    print("== 检测器自检（植入缺陷） ==")
    for i in issues:
        print(f"   [{i['rule']}] {i['widget']} — {i['detail']}")

    ok = True
    for need in ("R3_overlap", "R2_overflow", "R7A_text_truncated",
                 "R7B_text_clipped"):
        if need not in rules:
            print(f"   !! 漏检: {need}")
            ok = False
    # 多行裁切必须被捕获（曾因只测宽度而漏检）
    if not any(i["rule"] == "R7B_text_clipped" and i["widget"] == "plantedG" for i in issues):
        print("   !! 漏检: 多行文本裁切 plantedG")
        ok = False
    print("   自检:", "PASS ✅" if ok else "FAIL ❌")
    host.close()
    return 0 if ok else 1


def dump_widgets(pattern: str, pages) -> None:
    """打印名字匹配的控件几何，便于人工核对。"""
    from src.core.qt_compat.QtWidgets import QWidget as _W
    print(f"\n== 几何转储 (匹配 '{pattern}') ==")
    for idx, name, page in pages:
        try:
            for w in [page] + list(page.findChildren(_W)):
                nm = (w.objectName() or "")
                cn = type(w).__name__
                if pattern.lower() in nm.lower() or pattern.lower() in cn.lower():
                    fx = ""
                    try:
                        if w.minimumWidth() == w.maximumWidth() and w.minimumHeight() == w.maximumHeight():
                            fx = f" [FIXED {w.minimumWidth()}x{w.minimumHeight()}]"
                    except Exception:
                        pass
                    print(f"   {name:26} {cn:18} {nm:20} "
                          f"geo={w.width()}x{w.height()} vis={w.isVisible()}{fx}")
        except Exception:
            continue


def _plain_text(w) -> str:
    """取控件显示文本；HTML 标记剥离后再测宽。"""
    try:
        from src.core.qt_compat.QtWidgets import QLabel, QAbstractButton

        if isinstance(w, QLabel):
            t = w.text()
        elif isinstance(w, QAbstractButton):
            t = w.text()
        else:
            return ""
        t = t or ""
        if "<" in t and ">" in t:
            t = re.sub(r"<[^>]+>", "", t)
        return t.strip()
    except Exception:
        return ""


def check_text_fit(page: QWidget, page_name: str, issues: list) -> int:
    """R7 文字适配：检测**文字被截断 / 被裁切**（保证"所有字体不被遮挡"）。

    R7A 横向截断：不换行的文本，实际宽度 > 可用宽度
    R7B 纵向裁切：换行文本的高度超出可用高度
    返回检查过的文本控件数。
    """
    from src.core.qt_compat.QtWidgets import QLabel, QAbstractButton, QComboBox

    checked = 0
    try:
        widgets = [page] + list(page.findChildren(QWidget))
    except Exception:
        return 0

    for w in widgets:
        try:
            if not w.isVisible() or w.width() <= 0 or w.height() <= 0:
                continue
        except Exception:
            continue
        if isinstance(w, QComboBox):
            continue  # 组合框按设计省略显示
        txt = _plain_text(w)
        if not txt or len(txt) < 2:
            continue
        checked += 1

        try:
            fm = w.fontMetrics()
            cr = w.contentsRect()
            avail_w = max(1, cr.width())
            avail_h = max(1, cr.height())
            name = w.objectName() or type(w).__name__

            wrap = False
            try:
                wrap = bool(w.wordWrap())
            except Exception:
                wrap = False

            lines = txt.split("\n") if "\n" in txt else []
            if lines and len(lines) > 1:
                # 显式多行（\n）：按行测宽 + 累计行高，wordWrap 与否都要判
                need_h = len(lines) * fm.lineSpacing()
                need_w = max(fm.horizontalAdvance(l) for l in lines)
                if need_h > avail_h + 2:
                    issues.append({
                        "rule": "R7B_text_clipped", "page": page_name, "widget": name,
                        "detail": (f"多行文本需 {need_h}px 高（{len(lines)} 行），"
                                   f"控件仅 {avail_h}px；末行“{lines[-1][:20]}”被裁切"),
                    })
                elif need_w > avail_w + 2:
                    issues.append({
                        "rule": "R7A_text_truncated", "page": page_name, "widget": name,
                        "detail": f"多行文本最宽行 {need_w}px > 可用 {avail_w}px",
                    })
            elif wrap:
                br = fm.boundingRect(QRect(0, 0, avail_w, 100000),
                                     int(Qt.TextWordWrap), txt)
                if br.height() > avail_h + 2:
                    issues.append({
                        "rule": "R7B_text_clipped", "page": page_name, "widget": name,
                        "detail": (f"换行文本需要 {br.height()}px 高，控件仅 {avail_h}px；"
                                   f"文字“{txt[:26]}…”被裁切"),
                    })
            else:
                adv = fm.horizontalAdvance(txt)
                if adv > avail_w + 2:
                    issues.append({
                        "rule": "R7A_text_truncated", "page": page_name, "widget": name,
                        "detail": (f"文本宽 {adv}px > 可用 {avail_w}px；"
                                   f"“{txt[:26]}…”被截断"),
                    })
        except Exception:
            continue
    return checked


def _wcag_lum(c) -> float:
    """WCAG 相对亮度。"""
    def f(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c.red()) + 0.7152 * f(c.green()) + 0.0722 * f(c.blue())


def _contrast(c1, c2) -> float:
    l1, l2 = _wcag_lum(c1), _wcag_lum(c2)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


_DECL_COLOR_RE = re.compile(
    r"(?<![-a-zA-Z])color\s*:\s*(#[0-9A-Fa-f]{6}|#[0-9A-Fa-f]{3}|white|black)", re.I)


def _declared_text_color(w):
    """取控件**声明的文字色**：样式表 `color:` 优先，其次 palette。

    为什么不再靠"聚类找前景"：带立体高光的按钮上，**镜面高光带**会形成比文字更大的
    亮度簇（引擎的高光带占 30% 高度），"第二显著簇"会选中高光而不是文字
    —— 实测把白字深绿按钮判成 2.61:1。

    文字色是**确定值**（Qt 就按它渲染），真正需要"测量"的是背景。
    """
    from src.core.qt_compat.QtGui import QColor as _QC, QPalette as _QP

    try:
        ss = (w.styleSheet() or "") if w is not None else ""
    except Exception:
        ss = ""
    if ss:
        m = _DECL_COLOR_RE.search(ss)
        if m:
            tok = m.group(1).strip().lower()
            if tok == "white":
                return _QC(255, 255, 255)
            if tok == "black":
                return _QC(0, 0, 0)
            c = _QC(tok)
            if c.isValid():
                return c
    try:
        c = w.palette().color(_QP.ColorRole.WindowText)
        if c.isValid() and c.alpha() > 0:
            return c
    except Exception:
        pass
    return None


def check_contrast(page: QWidget, page_name: str, issues: list,
                   page_img=None) -> int:
    """R9 对比度：用**合成后的实际像素**判定前景/背景。

    关键：不能单独 grab 一个透明背景的 QLabel（背景会变黑导致 fg==bg 假阳性）。
    改为一次性抓整页，再按控件坐标裁剪 → 得到真实合成背景。

    阈值 WCAG AA：正文 4.5:1，大字号(≥18pt 或 粗体≥14pt) 3:1。
    禁用控件豁免（WCAG 1.4.3 例外）。
    """
    from src.core.qt_compat.QtGui import QColor
    from src.core.qt_compat.QtCore import QPoint

    if page_img is None:
        try:
            page_img = page.grab()
        except Exception:
            return 0
    try:
        dpr = float(page_img.devicePixelRatio() or 1.0)
    except Exception:
        dpr = 1.0
    img = page_img.toImage()

    checked = 0
    try:
        widgets = [page] + list(page.findChildren(QWidget))
    except Exception:
        return 0

    for w in widgets:
        try:
            if not w.isVisible() or w.width() < 6 or w.height() < 6:
                continue
            if not w.isEnabled():
                continue          # 禁用控件豁免
        except Exception:
            continue
        txt = _plain_text(w)
        if not txt or len(txt) < 2:
            continue
        try:
            pos = w.mapTo(page, QPoint(0, 0))
            x0 = int(pos.x() * dpr)
            y0 = int(pos.y() * dpr)
            cw = int(w.width() * dpr)
            ch = int(w.height() * dpr)
            if cw < 6 or ch < 6:
                continue
            x1 = min(img.width(), x0 + cw)
            y1 = min(img.height(), y0 + ch)
            x0 = max(0, x0)
            y0 = max(0, y0)
            if x1 - x0 < 6 or y1 - y0 < 6:
                continue

            # 只采样"内部"：排除最外圈，避免边框/倒角高光被误当成文字色
            inset = int(max(2, min(cw, ch) // 10))
            inset = min(inset, 8)
            ix0, iy0 = x0 + inset, y0 + inset
            ix1, iy1 = x1 - inset, y1 - inset
            if ix1 - ix0 < 4 or iy1 - iy0 < 4:
                ix0, iy0, ix1, iy1 = x0, y0, x1, y1

            step = max(1, min(ix1 - ix0, iy1 - iy0) // 40)
            # 用**亮度百分位**取前景/背景，而不是直方图众数+阈值：
            # 大而空的标签里文字像素可低至 0.05%（661x202 只放 4 个字），
            # 任何"按比例设阈"的做法都会漏判 → 误报 1.0:1 假阳性。
            samples = []
            for y in range(iy0 + 1, iy1 - 1, step):
                for x in range(ix0 + 1, ix1 - 1, step):
                    c = img.pixelColor(x, y)
                    samples.append((_wcag_lum(c), c))
            n = len(samples)
            if n < 40:
                continue
            samples.sort(key=lambda t: t[0])

            # ---- 有效性守卫 ----
            # (1) 区域过于平坦 → 没找到文字（如自绘画布），无法判定，跳过
            spread = samples[int(n * 0.98)][0] - samples[int(n * 0.02)][0]
            if spread < 0.010:
                continue
            # (2) 文字只占极小比例（大空白标签，如 661x202 放 4 个字）
            #     → 任何采样统计都无法可靠定位字形，跳过并由 R7/人工覆盖
            try:
                fh = max(8.0, float(w.fontMetrics().height()))
            except Exception:
                fh = 12.0
            ink = len(txt) * fh * fh * 0.6
            area = float(cw * ch)
            if area > ink * 25.0:
                continue

            # ---- 前景：优先用"声明的文字色"（准确），否则回退到聚类法 ----
            # 背景：取内部像素的**中位数**（稳健，代表主导表面色）
            bg = QColor(samples[n // 2][1])
            declared = _declared_text_color(w)
            if declared is not None:
                best = declared
            else:
                LUM_BINS = 64
                hist = [0] * LUM_BINS
                rep = [None] * LUM_BINS
                for lum, c in samples:
                    b = min(LUM_BINS - 1, max(0, int(lum * (LUM_BINS - 1))))
                    hist[b] += 1
                    if rep[b] is None:
                        rep[b] = c
                bg_bin = max(range(LUM_BINS), key=lambda i: hist[i])
                need = max(6, int(n * 0.008))
                best_bin, best_cnt = None, 0
                for b in range(LUM_BINS):
                    if abs(b - bg_bin) < 8:
                        continue
                    if hist[b] < need:
                        continue
                    if hist[b] > best_cnt:
                        best_bin, best_cnt = b, hist[b]
                if best_bin is None:
                    continue
                bg = QColor(rep[bg_bin] or samples[n // 2][1])
                best = QColor(rep[best_bin])
            checked += 1
            ratio = _contrast(bg, best)
            fnt = w.font()
            large = fnt.pointSize() >= 18 or (fnt.bold() and fnt.pointSize() >= 14)
            need = 3.0 if large else 4.5
            if ratio < need:
                name = w.objectName() or type(w).__name__
                issues.append({
                    "rule": "R9_low_contrast", "page": page_name, "widget": name,
                    "detail": (f"对比度 {ratio:.2f}:1 < {need}:1  "
                               f"前景#{best.red():02X}{best.green():02X}{best.blue():02X} "
                               f"/ 背景#{bg.red():02X}{bg.green():02X}{bg.blue():02X}  "
                               f"“{txt[:22]}…”"),
                })
        except Exception:
            continue
    return checked


def check_render_uniformity(win, issues) -> None:
    """R6 渲染伪影：检测标题栏等贴图横条是否出现**持续性色阶断层**。

    判别方式（区分"贴图接缝"与"设计上的 1px 刻度线"）：
      * 把该行按 x 等分成 K 段，取每段**均值**；
      * 相邻段均值跳变 >=8 级 → 判定为接缝（整块色差，肉眼可见的断层）；
      * 1px 刻度线只会让段均值变化 <1 级，不会误报。
    另附高阈值孤立尖峰检测（>=45 级）以捕捉阴影残影的硬边。
    """
    try:
        frame = getattr(win, "_title_frame", None)
        if frame is None:
            return
        pm = frame.grab()
        img = pm.toImage()
        w, h = img.width(), img.height()
        if w < 200 or h < 14:
            return

        def _row(x0, x1, y):
            out = []
            for x in range(x0, x1, 2):
                c = img.pixelColor(x, y)
                out.append((c.red() + c.green() + c.blue()) / 3.0)
            return out

        K = 16
        for y in (4, h - 5):
            samples = _row(2, w - 2, y)
            if len(samples) < K * 4:
                continue
            seg = len(samples) // K
            means = [sum(samples[i * seg:(i + 1) * seg]) / seg for i in range(K)]
            worst, worst_i = 0.0, -1
            for i in range(K - 1):
                d = abs(means[i + 1] - means[i])
                if d > worst:
                    worst, worst_i = d, i
            # 孤立尖峰（1px 硬边残影）
            spike = 0.0
            for i in range(1, len(samples) - 1):
                up = samples[i] - samples[i - 1]
                dn = samples[i] - samples[i + 1]
                if up > 0 and dn > 0:
                    spike = max(spike, min(up, dn))
                elif up < 0 and dn < 0:
                    spike = max(spike, min(-up, -dn))

            if worst >= 8:
                issues.append({
                    "rule": "R6_render_artifact", "page": "MainWindow(shell)",
                    "widget": "mimwTitleBar",
                    "detail": (f"y={y} 第 {worst_i + 1}/{K} 段处存在 {worst:.1f} 级"
                               f"**持续性**色阶断层（贴图接缝 / 分块色差）"),
                })
            elif spike >= 45:
                issues.append({
                    "rule": "R6_render_artifact", "page": "MainWindow(shell)",
                    "widget": "mimwTitleBar",
                    "detail": f"y={y} 检测到 {spike:.0f} 级孤立硬边尖峰（阴影残影）",
                })
            else:
                print(f"[shell] 标题栏渲染 y={y}: 段间最大跳变 {worst:.1f} 级、"
                      f"孤立尖峰 {spike:.0f} 级  ✅")
    except Exception as e:  # noqa: BLE001
        issues.append({"rule": "R0_error", "page": "MainWindow(shell)", "widget": "uniformity",
                       "detail": f"{type(e).__name__}: {e}"})


def check_material_purity(win, issues) -> None:
    """R8 材质纯色性：面板材质必须与**当前皮肤主色调**一致，不允许杂色条纹/伪彩。

    判定：取当前调色板 s600（面板中调）的最强通道 ch，采样像素须满足
    ch >= 其余两通道；杂色比例 > 0.5% 即报警。
    （原实现写死"冷蓝"——鎏金深色主题亮出 99.97% 假阳性后改为主题感知；
    浅色主题 s600 的最强通道仍是蓝 → 判据与旧版完全一致。）
    """
    try:
        from src.core.qt_compat.QtWidgets import QGroupBox
        from src.core.qt_compat.QtGui import QColor
        from src.utils.skeuomorphic import current_palette
        rc = QColor(current_palette().s600)
        chan = max((("r", rc.red()), ("g", rc.green()), ("b", rc.blue())),
                   key=lambda t: t[1])[0]
        pm_widget = getattr(win, "project_management_widget", None)
        if pm_widget is None:
            return
        box = None
        for gb in pm_widget.findChildren(QGroupBox):
            if gb.title() == "项目管理":
                box = gb
                break
        if box is None or box.width() < 200 or box.height() < 250:
            return

        pm = box.grab()
        img = pm.toImage()
        W, H = img.width(), img.height()
        x0, x1 = int(W * 0.35), int(W * 0.95)
        y0, y1 = 100, max(120, H - 80)
        total = bad = 0
        for y in range(y0, y1, 4):
            for x in range(x0, x1, 4):
                c = img.pixelColor(x, y)
                total += 1
                cv = {"r": c.red(), "g": c.green(), "b": c.blue()}
                others = [v for k, v in cv.items() if k != chan]
                if cv[chan] < others[0] or cv[chan] < others[1]:
                    bad += 1
        if total == 0:
            return
        ratio = bad / total
        if ratio > 0.005:
            issues.append({
                "rule": "R8_material_impurity", "page": "MainWindow(shell)",
                "widget": "panel material",
                "detail": (f"面板材质出现 {ratio * 100:.2f}% 偏离主色调('{chan}')像素"
                           f"（{bad}/{total}），存在杂色条纹/伪彩"),
            })
        else:
            print(f"[shell] 面板材质纯色性: 偏离主色('{chan}') {bad}/{total} "
                  f"({ratio * 100:.2f}%)  ✅")
    except Exception as e:  # noqa: BLE001
        issues.append({"rule": "R0_error", "page": "MainWindow(shell)",
                       "widget": "material_purity",
                       "detail": f"{type(e).__name__}: {e}"})


def main() -> int:
    app = QApplication.instance() or QApplication([])

    if "--self-test" in sys.argv:
        return self_test()

    from src.utils.skeuomorphic import apply_global  # noqa: E402
    apply_global(app)
    try:
        from src.utils.skeuo_style import install as install_skeuo_style
        install_skeuo_style(app)
    except Exception:
        pass

    from ui.widgets.main_window import MainWindow  # noqa: E402

    win = MainWindow(remaining_seconds=0, license_exp_ts=0)
    win.resize(1680, 1000)
    # ★ 页脚 opencode 面板由 main.py 通过 attach_opencode() 挂载，
    #   而它是 `centralWidget().layout()` 的成员，**与 stacked_widget 平级** ——
    #   原先检测器只遍历 stack 内的页面，于是**完全没检查过这个面板**，
    #   实测漏掉过一个浅色主题下 1.09:1 的对比度缺陷。这里按真实路径把它挂上。
    try:
        from src.kernel.tools.ui_bridge import UIBridge
        from src.kernel.kernel_boot import KernelBoot
        win.attach_opencode(UIBridge(), KernelBoot())
    except Exception as _e:  # noqa: BLE001
        print(f"[warn] attach_opencode 失败，页脚面板将不参与检查: {_e}")
    win.show()

    def pump(n=12):
        for _ in range(n):
            app.processEvents()
            time.sleep(0.04)

    pump(10)

    stack = win.stacked_widget
    issues = []
    pages = []
    for i in range(stack.count()):
        holder = stack.widget(i)
        inner = holder.widget() if isinstance(holder, QScrollArea) else holder
        try:
            name = (inner.objectName() or type(inner).__name__)
        except Exception:
            name = f"page{i}"
        pages.append((i, name, inner))

    # ---- 页面本体 vs 视口（最关键：QStackedWidget 不滚动，页面过高即被裁切）----
    for idx, name, w in pages:
        try:
            stack.setCurrentIndex(idx)
            pump(5)
            holder = stack.widget(idx)
            # 有滚动容器时：内容高 > 视口 属于正常滚动；只检查容器本身是否超出
            if isinstance(holder, QScrollArea):
                hw, hh = holder.width(), holder.height()
                sr = stack.rect()
                if hw > sr.width() + 1 or hh > sr.height() + 1:
                    issues.append({
                        "rule": "R2_overflow", "page": name, "widget": f"{name}(scroll)",
                        "detail": f"滚动容器 {hw}x{hh} 超出视口 {sr.width()}x{sr.height()}",
                    })
                continue
            sr = stack.rect()
            pw, ph = w.width(), w.height()
            if pw > sr.width() + 1 or ph > sr.height() + 1:
                issues.append({
                    "rule": "R2_overflow", "page": name, "widget": f"{name}(page)",
                    "detail": (f"页面 {pw}x{ph} 超出视口 {sr.width()}x{sr.height()}，"
                               f"底部/右侧被裁切 "
                               f"({max(0, ph - sr.height())}px 高 / {max(0, pw - sr.width())}px 宽不可见)"),
                })
        except Exception as e:  # noqa: BLE001
            issues.append({"rule": "R0_error", "page": name, "widget": "-",
                           "detail": f"{type(e).__name__}: {e}"})

    # ---- R5 屏幕遮挡：窗口最小尺寸超出屏幕可用区 => 底部/右侧被屏幕裁掉 ----
    try:
        scr = QApplication.primaryScreen()
        avail = scr.availableGeometry()
        mh = win.minimumSizeHint()
        need_h, need_w = mh.height(), mh.width()
        if need_h > avail.height() or need_w > avail.width():
            issues.append({
                "rule": "R5_offscreen", "page": "MainWindow(shell)", "widget": "MainWindow",
                "detail": (f"窗口最小尺寸 {need_w}x{need_h} 超出屏幕可用区 "
                           f"{avail.width()}x{avail.height()}；"
                           f"底部 {max(0, need_h - avail.height())}px / "
                           f"右侧 {max(0, need_w - avail.width())}px 会被屏幕裁掉"),
            })
        else:
            print(f"[shell] 窗口最小尺寸 {need_w}x{need_h} <= 屏幕可用 "
                  f"{avail.width()}x{avail.height()}  ✅")
    except Exception as e:  # noqa: BLE001
        issues.append({"rule": "R0_error", "page": "MainWindow(shell)", "widget": "-",
                       "detail": f"screen check: {type(e).__name__}: {e}"})

    for idx, name, w in pages:
        try:
            stack.setCurrentIndex(idx)
            pump(6)
            n_txt = check_text_fit(w, name, issues)
            check_page(w, name, issues)
            try:
                page_img = w.grab()          # 整页抓一次，用真实合成像素判对比度
            except Exception:
                page_img = None
            n_ctr = check_contrast(w, name, issues, page_img=page_img)
            print(f"[page] {name:30} 文本控件 {n_txt} 个 / 对比度已检 {n_ctr} 个")
        except Exception as e:  # noqa: BLE001
            issues.append({"rule": "R0_error", "page": name, "widget": "-",
                           "detail": f"{type(e).__name__}: {e}"})

    # 主窗口壳层（标题栏 / 菜单栏 / 状态栏 / opencode 面板）
    try:
        stack.setCurrentIndex(0)
        pump(4)
        check_page(win, "MainWindow(shell)", issues)
        check_render_uniformity(win, issues)
        check_material_purity(win, issues)
        # ★ 壳层控件的**对比度**也要查：这些控件与 stacked_widget 平级，
        #   不会被上面的分页循环覆盖。实测漏过页脚面板的 1.09:1、
        #   标题栏项目文字的 3.51:1、状态栏的 4.08:1（均为浅色主题）。
        shell_targets = []
        tb = getattr(win, "_title_frame", None)
        if tb is not None:
            shell_targets.append(("TitleBar", tb))
        try:
            shell_targets.append(("MenuBar", win.menuBar()))
            shell_targets.append(("StatusBar", win.statusBar()))
        except Exception:
            pass
        panel = getattr(win, "opencode_panel", None)
        if panel is not None:
            shell_targets.append(("OpenCodePanel", panel))
        for nm, sw in shell_targets:
            try:
                if not sw.isVisible() or sw.width() < 8 or sw.height() < 8:
                    continue
                n_s = check_contrast(sw, f"shell:{nm}", issues,
                                     page_img=sw.grab())
                print(f"[shell] {nm:30} 对比度已检 {n_s} 个")
            except Exception as e:  # noqa: BLE001
                issues.append({"rule": "R0_error", "page": f"shell:{nm}",
                               "widget": "-", "detail": f"{type(e).__name__}: {e}"})

        # 菜单栏：菜单项文字由 QStyle **直接绘制**，没有子控件 ——
        # 上面那类"遍历子控件"的检查完全查不到它（显示为"已检 0 个"）。
        # 这里用 palette 的文字色 + 实测底色单独核对一次。
        try:
            from src.core.qt_compat.QtGui import QColor as _QC, QPalette as _QP
            mb = win.menuBar()
            if mb.isVisible() and mb.width() > 40 and mb.height() > 8:
                mimg = mb.grab().toImage()
                _bins: dict = {}
                for yy in range(2, max(3, mimg.height() - 2), 2):
                    for xx in range(2, max(3, mimg.width() - 2), 2):
                        c = mimg.pixelColor(xx, yy)
                        k = (c.red() // 32, c.green() // 32, c.blue() // 32)
                        e = _bins.setdefault(k, [0, {}])
                        e[0] += 1
                        rgb = (c.red(), c.green(), c.blue())
                        e[1][rgb] = e[1].get(rgb, 0) + 1
                if _bins:
                    best = max(_bins.values(), key=lambda e: e[0])
                    rgb, _ = max(best[1].items(), key=lambda kv: kv[1])
                    bgc = _QC(*rgb)
                    fgc = mb.palette().color(_QP.ColorRole.WindowText)
                    rr_mb = _contrast(fgc, bgc)
                    ok_mb = rr_mb >= 4.5
                    print(f"[shell] {'MenuBar':30} 文字 {fgc.name()} on {bgc.name()} "
                          f"= {rr_mb:.2f}:1  {'OK' if ok_mb else '★ 低于 4.5'}")
                    if not ok_mb:
                        issues.append({
                            "rule": "R9_low_contrast", "page": "shell:MenuBar",
                            "widget": "QMenuBar",
                            "detail": (f"菜单栏文字对比度 {rr_mb:.2f}:1 < 4.5:1 "
                                       f"(前景 {fgc.name()} / 背景 {bgc.name()})")})
        except Exception as e:  # noqa: BLE001
            issues.append({"rule": "R0_error", "page": "shell:MenuBar",
                           "widget": "-", "detail": f"{type(e).__name__}: {e}"})
    except Exception:
        pass

    # ---- 报告 ----
    print("=" * 78)
    print("显示区块遮挡自检  ——  页面数:", len(pages))
    print("=" * 78)
    if not issues:
        print("✅ 未发现遮挡 / 挤压 / 溢出 / 塌陷")
    else:
        order = {"R3_overlap": 0, "R1_squeezed": 1, "R2_overflow": 2, "R4_collapsed": 3, "R0_error": 4}
        issues.sort(key=lambda x: (order.get(x["rule"], 9), x["page"]))
        for it in issues:
            print(f"[{it['rule']}] {it['page']} :: {it['widget']} — {it['detail']}")
        print()
        counts = {}
        for it in issues:
            counts[it["rule"]] = counts.get(it["rule"], 0) + 1
        print("汇总:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    if "--json" in sys.argv:
        p = sys.argv[sys.argv.index("--json") + 1]
        with open(p, "w", encoding="utf-8") as f:
            json.dump(issues, f, ensure_ascii=False, indent=2)
        print("json:", p)

    if "--dump" in sys.argv:
        dump_widgets(sys.argv[sys.argv.index("--dump") + 1], pages)

    print("\nRESULT:", "PASS" if not issues else "ISSUES")
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
