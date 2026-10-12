#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视觉缺陷审计：重影 + 控件溢出 block。

两类问题分开取证：

A. **控件溢出**（几何可判定）
   逐控件比较：子控件矩形是否越出父容器矩形 / 是否越出引擎**实际绘制的**面。
   注意引擎绘制的面往往比 widget 矩形小（例如分组框的面是
   `rect().adjusted(0, 10, 0, -1)`）—— 布局只保证"在 widget 内"，
   并不保证"在绘制面内"，这个差值就是溢出的温床。

B. **文字重影**（像素可判定）
   同一串字形被画两遍、且错开几个像素 → 墨迹的水平自相关
   会在小位移处出现次峰。用这个特征做检测。

用法：
    python scripts/audit_visual_defects.py
    python scripts/audit_visual_defects.py --self-test
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("MIMW_SKIN", "metal")

for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import numpy as np
except Exception:  # noqa: BLE001
    np = None

from src.core.qt_compat.QtCore import Qt, QPoint, QRect, QSize  # noqa: E402
from src.core.qt_compat.QtGui import QImage, QPainter, QFont, QColor  # noqa: E402
from src.core.qt_compat.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QScrollArea, QGroupBox, QPushButton, QLabel,
    QComboBox, QLineEdit, QCheckBox, QTableWidget, QTabWidget, QFrame,
)

# ================================================================ B. 重影检测


def qimage_to_rgb(img: QImage):
    """QImage → (h, w, 3) float32 数组。

    ⚠️ PyQt6 的 `constBits()` 返回 `sip.voidptr`，**必须先 `setsize()`**，
    否则 `np.frombuffer` 拿到 0 字节 → 静默变成空数组 → 检测器永远返回 0
    （实测踩过：自检里"正常绘制"和"错位两遍"都给 0.000，就是这个原因）。
    """
    if np is None:
        return None
    try:
        img8 = img.convertToFormat(QImage.Format.Format_RGB888)
        w, h = img8.width(), img8.height()
        if w < 4 or h < 4:
            return None
        bpl = int(img8.bytesPerLine())
        ptr = img8.constBits()
        try:
            ptr.setsize(h * bpl)
        except Exception:
            pass
        buf = np.frombuffer(ptr, dtype=np.uint8, count=h * bpl)
        if buf.size < h * bpl:
            return None
        arr = buf.reshape(h, bpl)[:, :w * 3].reshape(h, w, 3)
        return arr.astype(np.float32)
    except Exception:
        return None


def ink_mask(img: QImage, thr: int = 42):
    """把图转成"墨迹掩码"：与图中位亮度的差超过阈值的像素为 1。

    用**图中位亮度**当基准，而不是固定阈值 —— 深浅两套主题都能用。
    """
    arr = qimage_to_rgb(img)
    if arr is None:
        return None
    lum = 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]
    med = float(np.median(lum))
    return (np.abs(lum - med) > thr).astype(np.float32)


def ghost_score(img: QImage, max_lag: int = 26, thr: int = 42, min_lag: int = 6):
    """返回 (孪生率, 对应位移)。

    **孪生率** = 有多大比例的墨迹，在水平距离 L 处**也有**墨迹：
        twin(L) = |m ∩ shift(m, L)| / min(|m_left|, |m_right|)

    为什么用这个量：设 `m = A ∪ shift(A, L)`（同一串字错位画两遍），
    则左半与右半的墨迹**逐笔重合**，孪生率趋近 **1.0**。
    而单次绘制时，汉字笔画宽仅 2~3px，位移 6px 以上就基本对不上了 ——
    实测单次 0.35 左右、错位重绘 0.92 以上，**区分度 0.57**，
    远好于二维自相关（0.467 vs 0.756，只有 0.29）。

    `min_lag=6` 避开笔画自身宽度造成的伪峰。
    """
    m = ink_mask(img, thr)
    if m is None:
        return 0.0, 0
    if float(m.sum()) < 60:
        return 0.0, 0
    best, best_lag = 0.0, 0
    limit = min(max_lag, m.shape[1] - 2)
    for lag in range(min_lag, limit + 1):
        left = m[:, :-lag]
        right = m[:, lag:]
        s1, s2 = float(left.sum()), float(right.sum())
        den = min(s1, s2)
        if den <= 0:
            continue
        twin = float((left * right).sum()) / den
        if twin > best:
            best, best_lag = twin, lag
    return best, best_lag


# ================================================================ A. 溢出检测


def painted_body(w):
    """引擎**实际绘制的面**（比 widget 矩形可能小很多）。

    返回 None 表示该类型不画面 / 没有内缩。
    """
    r = w.rect()
    if isinstance(w, QGroupBox):
        # 见 skeuo_style._groupbox: body = rect.adjusted(0, 10, 0, -1)
        return QRect(r.left(), r.top() + 10, r.width(), max(0, r.height() - 11))
    if isinstance(w, QPushButton):
        # 见 skeuo_style._button: body = rect.adjusted(1, 1, -1, -4)
        return QRect(r.left() + 1, r.top() + 1, max(0, r.width() - 2),
                     max(0, r.height() - 5))
    return None


def audit_overflow(root: QWidget, issues: list, page_name: str, tol: int = 1):
    """子控件越出父容器 / 越出父容器**绘制面**的检查。"""
    stack = [root]
    seen = set()
    while stack:
        p = stack.pop()
        if id(p) in seen:
            continue
        seen.add(id(p))
        if not p.isVisible():
            continue
        prect = p.rect()
        body = painted_body(p)
        for c in p.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
            stack.append(c)
            if not c.isVisible() or c.isWindow():
                continue
            g = c.geometry()
            # (1) 越出父矩形
            if (g.left() < prect.left() - tol or g.top() < prect.top() - tol
                    or g.right() > prect.right() + tol
                    or g.bottom() > prect.bottom() + tol):
                issues.append({
                    "rule": "R10_child_out_of_parent",
                    "page": page_name,
                    "widget": type(c).__name__,
                    "detail": (f"{c.objectName() or '-'} 矩形({g.x()},{g.y()},"
                               f"{g.width()}x{g.height()}) 越出父 "
                               f"{type(p).__name__}({prect.width()}x{prect.height()})"),
                })
            # (2) 越出父**绘制面**（分组框的金属板等）
            if body is not None and body.width() > 4 and body.height() > 4:
                if (g.top() < body.top() - tol or g.bottom() > body.bottom() + tol
                        or g.left() < body.left() - tol
                        or g.right() > body.right() + tol):
                    issues.append({
                        "rule": "R11_child_out_of_painted_body",
                        "page": page_name,
                        "widget": type(c).__name__,
                        "detail": (f"{c.objectName() or '-'} 矩形({g.x()},{g.y()},"
                                   f"{g.width()}x{g.height()}) 越出 "
                                   f"{type(p).__name__} 绘制面({body.x()},{body.y()},"
                                   f"{body.width()}x{body.height()})"),
                    })


# ================================================================ 自检（植入缺陷）


def self_test() -> int:
    """植入"错位重影"与"子控件溢出"，验证两类检测都会报警。"""
    app = QApplication.instance() or QApplication([])
    ok = True

    # --- 重影：同一串字画两遍，水平错开 6px
    img = QImage(QSize(260, 40), QImage.Format.Format_ARGB32)
    img.fill(QColor(24, 32, 48))
    p = QPainter(img)
    f = QFont("Source Han Sans CN" if sys.platform == "win32" else "Arial", 15)
    p.setFont(f)
    p.setPen(QColor(235, 240, 250))
    p.drawText(QRect(8, 0, 244, 40), int(Qt.AlignmentFlag.AlignVCenter), "文本输入")
    p.end()
    base, lag0 = ghost_score(img)

    img2 = QImage(QSize(260, 40), QImage.Format.Format_ARGB32)
    img2.fill(QColor(24, 32, 48))
    p = QPainter(img2)
    p.setFont(f)
    p.setPen(QColor(235, 240, 250))
    p.drawText(QRect(8, 0, 244, 40), int(Qt.AlignmentFlag.AlignVCenter), "文本输入")
    p.setPen(QColor(200, 214, 235, 170))
    p.drawText(QRect(14, 0, 244, 40), int(Qt.AlignmentFlag.AlignVCenter), "文本输入")
    p.end()
    ghost, lag = ghost_score(img2)
    print(f"  自检A 正常单次绘制 : 次峰={base:.3f} (lag={lag0})")
    print(f"  自检A 错位画两遍   : 次峰={ghost:.3f} (lag={lag})")
    if not (ghost > base + 0.06 and ghost >= 0.20):
        print("     !! 重影检测未报警 → 检测器无效")
        ok = False
    else:
        print("     重影检测报警 ✓")

    # --- 溢出：故意把子控件放到父容器外
    host = QWidget()
    host.resize(200, 120)
    child = QLabel("溢出", host)
    child.setGeometry(180, 100, 60, 40)   # 右下越界
    host.show()
    for _ in range(6):
        app.processEvents()
    issues = []
    audit_overflow(host, issues, "自检")
    hit = [i for i in issues if i["rule"] == "R10_child_out_of_parent"]
    print(f"  自检B 子控件越界     : 命中 {len(hit)} 条")
    if not hit:
        print("     !! 溢出检测未报警 → 检测器无效")
        ok = False
    else:
        print("     溢出检测报警 ✓")
    host.close()

    if QGroupBox is not None:
        # 分组框绘制面比 widget 小 11px：把子控件放到绘制面之外，应报 R11
        gb = QGroupBox("组", None)
        gb.resize(240, 100)
        inner = QLabel("内", gb)
        inner.setGeometry(6, 2, 60, 20)   # 落在"面"之上（面从 y=10 开始）
        gb.show()
        for _ in range(6):
            app.processEvents()
        issues2 = []
        audit_overflow(gb, issues2, "自检")
        hit2 = [i for i in issues2 if i["rule"] == "R11_child_out_of_painted_body"]
        print(f"  自检C 子控件越出绘制面: 命中 {len(hit2)} 条")
        if not hit2:
            print("     !! R11 未报警 → 检测器无效")
            ok = False
        else:
            print("     R11 报警 ✓")
        gb.close()

    print("自检:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# ================================================================ 主流程


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--theme", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    if args.theme:
        os.environ["MIMW_THEME"] = args.theme

    if np is None:
        print("numpy 不可用：重影检测将跳过（溢出检测仍可用）")

    app = QApplication.instance() or QApplication([])

    from src.utils import skeuomorphic as sk
    from src.utils import skeuo_style as st
    try:
        from src.utils.theme_manager import ThemeManager
        ThemeManager._current_theme = args.theme or "dark"
    except Exception:
        pass
    sk.apply_global(app)
    st.install(app)

    if args.self_test:
        return self_test()

    from ui.widgets.main_window import MainWindow
    win = MainWindow(remaining_seconds=0, license_exp_ts=0)
    win.resize(1680, 1000)
    win.show()

    def pump(n=12):
        import time
        for _ in range(n):
            app.processEvents()
            time.sleep(0.05)

    pump(16)

    stack = win.stacked_widget
    issues = []
    for i in range(stack.count()):
        stack.setCurrentIndex(i)
        pump(8)
        holder = stack.widget(i)
        page = holder.widget() if isinstance(holder, QScrollArea) else holder
        pname = f"{i}:{type(page).__name__}"
        audit_overflow(page, issues, pname)

    # ---- 重影：改用**结构性**不变量（像素规则对汉字不可靠，见下） ----
    #
    # 曾经尝试的像素规则（本脚本里 ghost_score 仍在，供人工分诊）：
    #   "同一串字错位画两遍 → 墨迹孪生率在错位量处升高"。
    # 实测**不可用**：汉字致密、字形相似，单次绘制的孪生率本底就有 0.56，
    # 真实控件上甚至到 0.92 ——
    #   `TXT` 组合框 0.916（两个 T 是同一字形）
    #   `刷新列表` 按钮 0.918（4 倍放大目视**完全干净**）
    # 与真实重影（下拉框 0.783）**无法区分**。故放弃像素判定，
    # 改用零假阳性的结构性规则：**三维引擎不得手绘任何文字**。
    # 否则就会与 Qt 原生的 label 绘制叠加成重影 —— 下拉框重影的成因正是
    # `_combo` 里 drawText 一遍 + Qt 的 CE_ComboBoxLabel 再画一遍。
    engine = os.path.join(os.path.dirname(__file__), "..", "src", "utils",
                          "skeuo_style.py")
    try:
        with open(engine, encoding="utf-8") as fh:
            src = fh.read()
        code = re.sub(r"#.*", "", src)                 # 去行注释
        code = re.sub(r'"""[\s\S]*?"""', "", code)     # 去文档字符串
        if re.search(r"\.drawText\s*\(", code):
            for m in re.finditer(r"^\s*.*\.drawText\s*\(", code, re.M):
                issues.append({
                    "rule": "R12_engine_draws_text",
                    "page": "-",
                    "widget": "SkeuoPainter",
                    "detail": ("三维引擎里出现手绘文字 → 会与 Qt 原生 label 叠加成重影: "
                               + m.group(0).strip()[:70]),
                })
    except Exception as exc:  # noqa: BLE001
        issues.append({
            "rule": "R12_engine_draws_text",
            "page": "-",
            "widget": "audit",
            "detail": f"结构性检查无法执行: {exc}",
        })

    print("=" * 78)
    print(f"视觉缺陷审计  主题={args.theme or 'dark'}  总命中 {len(issues)}")
    print("=" * 78)
    from collections import Counter
    print("  按规则:", dict(Counter(i["rule"] for i in issues)))
    for i in issues[:40]:
        print(f"   [{i['rule']}] {i['page']} | {i['widget']} | {i['detail'][:96]}")
    print("-" * 78)
    print("RESULT:", "PASS" if not issues else "ISSUES")

    if args.json:
        import json
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(issues, fh, ensure_ascii=False, indent=1)
        print("json ->", args.json)

    win.close()
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
