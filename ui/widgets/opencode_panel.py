#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""opencode_panel —— MainWindow 底部「OPENCODE 智能体」栏（PyQt5）。

设计约束（playbook + Qt 铁律）：
  * MCP 工具 / 内核回调运行在后台线程 —— 一切跨线程通信都走 pyqtSignal。
  * 面板不直接碰领域服务，只通过 KernelBoot 投递任务。
  * 状态显示**脱敏**（不出现内核 HTTP 密码 / api_key）。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.core.qt_compat.QtCore import Qt, pyqtSignal
from src.core.qt_compat.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit,
    QVBoxLayout, QWidget, QFrame,
)

# ================================================================ 配色
#
# 沿用 **PyCt6 的双色元组** 思路：每个颜色都定义成 (light, dark) 成对，
# 运行时按键选一侧 —— 换主题不必重写样式表，也不会出现"暗色孤岛"。
#
# ⚠️ 原实现是**硬编码的 DARK 常量**，在浅色主题下：
#     · 标题亮绿 #7FD1AE 压在浅蓝灰底上 → 实测 **1.09:1**（几乎不可见）
#     · 而且 `QWidget` 用 QSS 设背景**必须 setAttribute(WA_StyledBackground)**，
#       否则 `QWidget#ocPanel { background:#1E1E1E }` 根本不画 ——
#       实测面板底色是应用主题底色，而不是声明的 #1E1E1E。
# 下面每组都按 WCAG 正文门槛（>=4.5:1）挑过，并在 probe 里逐项实测。
_PAIRS: Dict[str, tuple] = {
    "panel_bg":     ("#F2F5F9", "#12161C"),   # 面板底
    "panel_edge":   ("#C8D2DE", "#2A313B"),   # 顶部分隔线
    "title":        ("#0F6B4A", "#7FD1AE"),   # 深绿 / 亮绿
    "status":       ("#3A4653", "#C2CBD6"),
    "log_bg":       ("#FFFFFF", "#0B0F14"),
    "log_fg":       ("#1B2430", "#DCE3EC"),
    "log_edge":     ("#C8D2DE", "#2A313B"),
    "input_bg":     ("#FFFFFF", "#0B0F14"),
    "input_fg":     ("#1B2430", "#E8EEF6"),
    "input_edge":   ("#B9C4D2", "#39424E"),
    "input_ph":     ("#6B7684", "#8B95A3"),   # 占位符也保证可读
    "btn_bg":       ("#E3E9F1", "#262D37"),
    "btn_fg":       ("#1B2430", "#E6ECF4"),
    "btn_edge":     ("#B9C4D2", "#39424E"),
    "btn_hover":    ("#D5DEE9", "#333C48"),
    "btn_dis_bg":   ("#EDF1F6", "#1B2129"),
    # 原 #666 在 #242424 上只有 2.70:1 —— 禁用态虽可低于正文门槛，
    # 但 2.70:1 连"能看清写的是什么"都做不到。浅色侧也从 #6B7684(4.07) 压深到 #5C6672。
    "btn_dis_fg":   ("#5C6672", "#98A2B0"),
}


def _is_dark() -> bool:
    """当前是否暗色主题（跟随皮肤）。

    ⚠️ `MetalPalette` **没有** `.dark` 属性。原实现写 `bool(pal.dark)` 会抛
    AttributeError → 被 except 吞掉 → **恒返回 True** → 浅色主题下也生成暗色面板
    （实测：`MIMW_THEME=light` 时 `panel_bg` 仍是 #12161C，修复等于没生效）。
    必须用 `.name` 判断。
    """
    try:
        from src.utils.skeuomorphic import current_palette
        return str(getattr(current_palette(), "name", "")).strip().lower() == "dark"
    except Exception:
        return True


def theme_colors() -> Dict[str, str]:
    """按当前主题把 (light, dark) 元组解析成单值。"""
    dark = _is_dark()
    return {k: (v[1] if dark else v[0]) for k, v in _PAIRS.items()}


def build_qss() -> str:
    """生成当前主题下的面板样式表。

    字体用皮肤已实测可用的字体栈（`Source Han Sans CN` / `Cascadia Mono`），
    不再写 `'Microsoft YaHei'` —— 本机**并未安装**该字体，写了只会静默回落。
    """
    c = theme_colors()
    try:
        from src.utils.skeuomorphic import FONT_MONO, FONT_UI
    except Exception:
        FONT_UI, FONT_MONO = "Source Han Sans CN", "Cascadia Mono"
    return f"""
QWidget#ocPanel {{ background:{c['panel_bg']}; border-top:1px solid {c['panel_edge']}; }}
QLabel#ocTitle {{ color:{c['title']}; font-weight:bold;
                  font-family:'{FONT_UI}'; font-size:12px; }}
QLabel#ocStatus {{ color:{c['status']}; font-family:'{FONT_MONO}'; font-size:11px; }}
QTextEdit#ocLog {{
    background:{c['log_bg']}; color:{c['log_fg']}; border:1px solid {c['log_edge']};
    font-family:'{FONT_MONO}'; font-size:11px;
}}
QLineEdit#ocInput {{
    background:{c['input_bg']}; color:{c['input_fg']}; border:1px solid {c['input_edge']};
    border-radius:3px; padding:4px 6px; font-size:11px;
}}
QPushButton {{
    background:{c['btn_bg']}; color:{c['btn_fg']}; border:1px solid {c['btn_edge']};
    border-radius:3px; padding:4px 10px; font-size:11px;
}}
QPushButton:hover {{ background:{c['btn_hover']}; }}
QPushButton:disabled {{ background:{c['btn_dis_bg']}; color:{c['btn_dis_fg']}; }}
"""


class OpenCodePanel(QWidget):
    """底部智能体栏：可折叠，含日志流、输入框、启停与状态。"""

    eventReceived = pyqtSignal(dict)   # 后台线程 -> 主线程

    def __init__(self, boot=None, parent=None):
        super().__init__(parent)
        self.setObjectName("ocPanel")
        # ★ 必须：普通 QWidget 用 QSS 设 background 时，**默认不会绘制**。
        #   没有这一行，`QWidget#ocPanel { background:… }` 是空话 ——
        #   实测面板底色显示为应用主题底色而非声明值。
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        except Exception:
            pass
        try:
            # 显式声明"我自己管主题"，让皮肤清理逻辑豁免本控件
            self.setProperty("skin_self_themed", True)
        except Exception:
            pass
        self.boot = boot
        self.project_id = ""
        self._expanded = False
        self._thread = None
        self._init_ui()
        self.eventReceived.connect(self._on_event)

    def refresh_theme(self):
        """主题热切换协议：MainWindow.apply_theme_live() 会遍历调用。"""
        self._apply_theme()

    def _apply_theme(self):
        """把当前主题的面板样式套上去（幂等）。"""
        try:
            self.setStyleSheet(build_qss())
        except Exception:
            pass

    # ------------------------------------------------------------ UI

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 2, 6, 4)
        root.setSpacing(3)

        # 折叠头
        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = QLabel("🤖 OPENCODE 智能体")
        self.title.setObjectName("ocTitle")
        self.status = QLabel("未启动")
        self.status.setObjectName("ocStatus")
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.btn_toggle = QPushButton("展开")
        self.btn_toggle.setFixedWidth(64)
        try:
            from src.utils.app_icons import apply_icon
            apply_icon(self.btn_toggle, "chevron-up", "text", 14)
        except Exception:
            pass
        self.btn_toggle.clicked.connect(self.toggle)

        self.btn_start = QPushButton("启动内核")
        self.btn_start.setFixedWidth(92)
        try:
            from src.utils.app_icons import apply_icon
            apply_icon(self.btn_start, "play", "text", 14)
        except Exception:
            pass
        self.btn_start.clicked.connect(self.start_kernel)

        self.btn_stop = QPushButton("停止")
        self.btn_stop.setFixedWidth(72)
        try:
            from src.utils.app_icons import apply_icon
            apply_icon(self.btn_stop, "stop", "text", 14)
        except Exception:
            pass
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_kernel)

        self.btn_console = QPushButton("终端")
        self.btn_console.setFixedWidth(64)
        try:
            apply_icon(self.btn_console, "eye", "text", 14)
        except Exception:
            pass
        self.btn_console.clicked.connect(self.open_console)

        head.addWidget(self.title)
        head.addWidget(self.status, 1)
        head.addWidget(self.btn_start)
        head.addWidget(self.btn_stop)
        head.addWidget(self.btn_console)
        head.addWidget(self.btn_toggle)
        root.addLayout(head)

        # 展开体
        self.body = QFrame()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 2, 0, 0)
        body_layout.setSpacing(3)

        self.log = QTextEdit()
        self.log.setObjectName("ocLog")
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(120)
        self.log.setMaximumHeight(240)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setObjectName("ocInput")
        self.input.setPlaceholderText("给智能体下达任务，例如：总结当前项目的样本构成并给出证据来源")
        self.input.returnPressed.connect(self.send)
        self.input.returnPressed.connect(self.send)
        self.btn_send = QPushButton("发送")
        self.btn_send.setFixedWidth(72)
        try:
            from src.utils.app_icons import apply_icon
            apply_icon(self.btn_send, "send", "text", 14)
        except Exception:
            pass
        self.btn_send.clicked.connect(self.send)
        row.addWidget(self.input, 1)
        row.addWidget(self.btn_send)

        body_layout.addWidget(self.log)
        body_layout.addLayout(row)

        self.body.setVisible(False)
        root.addWidget(self.body)

        # 样式表由 _apply_theme() 按当前主题生成（原实现是硬编码 DARK）
        self._apply_theme()

    # ------------------------------------------------------------ 行为

    def toggle(self):
        self._expanded = not self._expanded
        self.body.setVisible(self._expanded)
        self.btn_toggle.setText("收起" if self._expanded else "展开")
        try:
            from src.utils.app_icons import apply_icon
            apply_icon(self.btn_toggle,
                       "chevron-down" if self._expanded else "chevron-up",
                       "text", 14)
        except Exception:
            pass

    def expand_for_output(self):
        if not self._expanded:
            self.toggle()

    def append(self, text: str):
        self.log.append(str(text))
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_status_text(self, text: str):
        self.status.setText(str(text))

    def set_project(self, project_id: str, name: str = ""):
        self.project_id = str(project_id or "")
        label = name or self.project_id or "-"
        self.title.setText(f"🤖 OPENCODE 智能体 · {label}")

    # ------------------------------------------------------------ 内核启停

    def attach(self, boot):
        self.boot = boot
        self.refresh_status()

    def refresh_status(self):
        if self.boot is None:
            self.set_status_text("未接入")
            return
        st = self.boot.status() or {}
        k = st.get("kernel") or {}
        if k.get("running"):
            self.set_status_text(
                f"运行中 {k.get('version', '')} pid={k.get('pid')} port={k.get('port')} "
                f"mcp={st.get('mcp_name', '')}"
            )
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
        else:
            err = st.get("last_error") or ""
            self.set_status_text(f"未启动{(' · ' + err) if err else ''}")
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)

    def start_kernel(self):
        import logging as _lg
        _lg.getLogger("ui.opencode_panel").info(
            "start_kernel invoked; boot=%s running=%s",
            self.boot is not None, bool(self.boot and self.boot.is_running()))
        if self.boot is None:
            self.append("[panel] 未接入 KernelBoot")
            return
        self.set_status_text("启动中…（MCP 注册 → 内核 → 健康检查）")
        self.btn_start.setEnabled(False)
        self.append("[panel] 正在启动 opencode 内核…")

        def _diag(msg: str):
            """必落盘诊断（不受 logging 配置影响）。"""
            try:
                import os as _os, time as _t
                with open(_os.path.join(_os.getcwd(), "boot_trace.log"),
                          "a", encoding="utf-8") as f:
                    f.write(f"panel:{_t.strftime('%H:%M:%S')} {msg}\n")
            except Exception:
                pass

        def _worker():
            _diag("worker start -> boot.start()")
            try:
                res = self.boot.start()
            except Exception as e:  # noqa: BLE001
                _diag(f"boot.start EXC {type(e).__name__}: {e}")
                _lg.getLogger("ui.opencode_panel").warning(
                    "kernel start exception: %s", e, exc_info=True)
                res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            _diag("boot.start -> " + str({k: (res or {}).get(k) for k in ("ok", "error")}
                                          if isinstance(res, dict) else res)[:400])
            # 启动成功后：让 TUI 控制台指向当前项目会话
            try:
                if isinstance(res, dict) and res.get("ok") and self.project_id:
                    self.boot.follow_project(str(self.project_id))
            except Exception:
                pass
            self.eventReceived.emit({"kind": "__kernel__", "data": res})

        import threading
        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def stop_kernel(self):
        if self.boot is None:
            return
        try:
            self.boot.stop()
        except Exception as e:  # noqa: BLE001
            self.append(f"[panel] 停止失败: {e}")
        self.refresh_status()
        self.append("[panel] 内核已停止")

    # ------------------------------------------------------------ 任务

    def open_console(self):
        """打开/聚焦独立 shell 的 opencode TUI 控制台（跟随当前会话）。"""
        if self.boot is None:
            self.append("[panel] 未接入 KernelBoot")
            return
        if not self.boot.is_running():
            self.append("[panel] 内核未运行，请先点击「启动内核」")
            return
        try:
            res = self.boot.open_console()
            self.append(f"[panel] 控制台: ok={res.get('ok')} spawned={res.get('spawned')} "
                        f"pid={res.get('pid')}")
        except Exception as e:  # noqa: BLE001
            self.append(f"[panel] 打开控制台失败: {e}")

    def send(self):
        text = self.input.text().strip()
        if not text:
            return
        if self.boot is None or not self.boot.is_running():
            self.append("[panel] 内核未运行，请先点击「启动内核」")
            return
        if not self.project_id:
            self.append("[panel] 未选择项目（请先在项目管理中选择）")
            return
        self.input.clear()
        self.expand_for_output()
        self.append(f"\n> {text}")
        try:
            self.boot.run_task_async(self.project_id, text, on_event=self._emit_event)
        except Exception as e:  # noqa: BLE001
            self.append(f"[panel] 投递失败: {e}")

    def _emit_event(self, ev: Dict[str, Any]):
        try:
            self.eventReceived.emit(ev)
        except Exception:
            pass

    def _on_event(self, ev: Dict[str, Any]):
        kind = str((ev or {}).get("kind") or "")
        if kind == "__kernel__":
            res = (ev or {}).get("data") or {}
            if res.get("ok"):
                self.append("[panel] 内核已就绪")
            else:
                self.append(f"[panel] 启动失败: {res.get('error')}")
            self.refresh_status()
            return
        if kind == "tool":
            self.append(f"  🔧 {ev.get('text', '')}")
        elif kind == "question":
            self.append(f"  ❓ {ev.get('text', '')}")
        elif kind == "permission":
            self.append(f"  🛡️ {ev.get('text', '')}")
        elif kind == "step":
            return
        elif kind == "text":
            self.append(str(ev.get("text") or ""))
        else:
            t = str(ev.get("text") or "").strip()
            if t:
                self.append(t)
