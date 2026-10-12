import json
import logging
import os
import re
import urllib.parse
from pathlib import Path
from datetime import datetime
from src.ai.agent_skills.ppt_generator import PPTGenerator
from src.core.qt_compat.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QScrollArea, QFrame, QComboBox, QTextEdit, QTextBrowser, QDialog, 
    QTabWidget, QSlider, QSizePolicy, QMessageBox, QCheckBox, QSplitter,
    QFileDialog
)
from src.core.qt_compat.QtCore import Qt, pyqtSignal
from src.core.qt_compat.QtGui import QFont, QColor

from src.utils.logger import get_logger
from src.utils.app_icons import apply_icon, apply_pixmap, icon_pixmap

class DraftCard(QFrame):
    """
    Card widget representing a completed draft.
    """
    clicked = pyqtSignal(dict) # Signal emitting draft data when clicked
    score_submitted = pyqtSignal(str, int) # draft_id, score

    def __init__(self, draft_data, parent=None):
        super().__init__(parent)
        self.draft_data = draft_data
        self.time_lbl = None
        self.preview = None
        self.manual_lbl = None
        self.model_lbl = None
        self.init_ui()
        self._apply_theme()

    # ---------------------------------------------------- 主题
    @staticmethod
    def theme_colors() -> dict:
        """解析当前主题下的卡片配色。

        原实现把 `"#333333" if is_dark else "#FFFFFF"` 直接写在构造期，
        主题热切换后不会更新；现在统一由 `_apply_theme()` 套用，
        `refresh_theme()` 可随时重刷。
        金属皮肤开启时跟随皮肤调色板（避免灰卡/白卡突兀）。
        """
        try:
            from src.utils.skeuomorphic import SKIN_ENABLED, current_palette
            if SKIN_ENABLED:
                p = current_palette()
                dark = p.name == "dark"
                return {
                    "dark": dark,
                    "card_bg": p.s600 if dark else p.s200,
                    "card_border": p.edge_soft,
                    "card_hover_border": p.accent,
                    "card_hover_bg": p.s500 if dark else p.s300,
                    "time": p.text_dim,
                    "preview": p.text_dim,
                    "manual_bg": "#5B3A00" if dark else "#FFF2CC",
                    "manual_fg": "#FFD8A8" if dark else "#8A2D00",
                    "model_bg": p.s500 if dark else p.s400,
                    "model_fg": p.text,
                }
        except Exception:
            pass
        try:
            from src.utils.theme_manager import ThemeManager
            is_dark = ThemeManager.get_current_theme() == "dark"
        except Exception:
            is_dark = False
        return {
            "dark": is_dark,
            "card_bg": "#333333" if is_dark else "#FFFFFF",
            "card_border": "#555555" if is_dark else "#ddd",
            "card_hover_border": "#6A6A6A" if is_dark else "#2E86AB",
            "card_hover_bg": "#3E3E3E" if is_dark else "#f5f9ff",
            "time": "#D8B4FE" if is_dark else "#666",
            "preview": "#E9D5FF" if is_dark else "#444",
            "manual_bg": "#5B3A00" if is_dark else "#FFF2CC",
            "manual_fg": "#FFD8A8" if is_dark else "#8A2D00",
            "model_bg": "#4A4A4A" if is_dark else "#eee",
            "model_fg": "#F5D0FE" if is_dark else "#222",
        }

    def _apply_theme(self):
        """套用 / 重刷主题相关样式（幂等）。"""
        c = self.theme_colors()
        try:
            self.setStyleSheet("""
            DraftCard {
                background-color: %s;
                border: 1px solid %s;
                border-radius: 8px;
                margin-bottom: 10px;
            }
            DraftCard:hover {
                border: 1px solid %s;
                background-color: %s;
            }
        """ % (c["card_bg"], c["card_border"],
               c["card_hover_border"], c["card_hover_bg"]))
        except Exception:
            pass
        for w, key, tpl in (
            (self.time_lbl, "time", "color: %s; font-weight: 500;"),
            (self.preview, "preview", "color: %s; margin: 5px 0;"),
        ):
            if w is None:
                continue
            try:
                w.setStyleSheet(tpl % c[key])
            except Exception:
                pass
        if self.manual_lbl is not None:
            try:
                self.manual_lbl.setStyleSheet(
                    "background: %s; color: %s; padding: 3px 8px; border-radius: 4px;"
                    " font-weight: 700; margin-top: 4px;"
                    % (c["manual_bg"], c["manual_fg"]))
            except Exception:
                pass
        if self.model_lbl is not None:
            try:
                self.model_lbl.setStyleSheet(
                    "background: %s; color: %s; padding: 2px 6px; border-radius: 4px;"
                    " font-weight: 600;" % (c["model_bg"], c["model_fg"]))
            except Exception:
                pass

    def refresh_theme(self):
        """主题热切换协议：MainWindow.apply_theme_live() 会遍历调用。"""
        self._apply_theme()

    def init_ui(self):
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        
        layout = QVBoxLayout(self)
        
        # Header: Title & Time
        header = QHBoxLayout()
        title = QLabel(f"<b>{self.draft_data.get('title', 'Untitled Draft')}</b>")
        title.setFont(QFont("Arial", 12))
        header.addWidget(title)
        
        time_str = self.draft_data.get('timestamp', 'Unknown Time')
        self.time_lbl = QLabel(time_str)
        header.addWidget(self.time_lbl)
        layout.addLayout(header)
        
        # Summary Preview
        preview_text = self.draft_data.get('abstract_preview', 'No abstract available.')
        self.preview = QLabel(preview_text)
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)

        if self.draft_data.get("requires_manual_completion"):
            reason = (self.draft_data.get("manual_completion_reason") or "").strip()
            txt = "⚠️ 需要人工补充内容"
            if reason:
                txt = f"{txt}：{reason}"
            self.manual_lbl = QLabel(txt)
            self.manual_lbl.setWordWrap(True)
            layout.addWidget(self.manual_lbl)
        
        # Footer: Model & Score
        footer = QHBoxLayout()
        self.model_lbl = QLabel(f"🤖 {self.draft_data.get('model', 'Unknown Model')}")
        footer.addWidget(self.model_lbl)
        
        footer.addStretch()
        
        # Score Slider
        score_lbl = QLabel("Score:")
        footer.addWidget(score_lbl)
        
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(1, 10)
        self.slider.setValue(self.draft_data.get('user_score', 0) or 5)
        self.slider.setFixedWidth(100)
        self.slider.valueChanged.connect(self.on_score_change)
        footer.addWidget(self.slider)
        
        self.score_val_lbl = QLabel(str(self.slider.value()))
        footer.addWidget(self.score_val_lbl)
        
        btn_view = QPushButton("View Details")
        apply_icon(btn_view, "eye", "text", 15)
        btn_view.clicked.connect(lambda: self.clicked.emit(self.draft_data))
        footer.addWidget(btn_view)
        
        layout.addLayout(footer)
        
    def on_score_change(self, val):
        self.score_val_lbl.setText(str(val))
        # In a real app, debounce this or save on release
        self.score_submitted.emit(self.draft_data['id'], val)

from src.services.project_service import ProjectService
from src.services.ollama_local_service import OllamaLocalService

class FeedbackOptimizationWidget(QWidget):
    """
    Step 5: Iterative Optimization Dashboard
    Displays draft history and collects user feedback.
    """
    
    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.logger = get_logger(__name__)
        self.config = config
        self.project_service = ProjectService() # Service for DB persistence
        self.draft_history = [] 
        self.current_project_id = None
        from src.kernel.inference_gateway import make_llm_service
        self.llm_service = make_llm_service(OllamaLocalService)
        
        self.init_ui()
        # Initial load (will be empty until project set)
        
    def set_current_project(self, project_id):
        """Set current project and load its drafts"""
        self.current_project_id = project_id
        try:
            if hasattr(self.llm_service, "set_project"):
                self.llm_service.set_project(project_id)
        except Exception:
            pass
        self.load_drafts_from_db()
        
    def on_export_word_clicked(self):
        """导出 Step4 生成的图文 Word 文档（含批注）。"""
        try:
            from src.services.step4_word_service import find_latest_step4_docx, export_docx
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "导出失败", f"Word 服务不可用: {e}")
            return
        src_path = find_latest_step4_docx(str(self.current_project_id or ""))
        if not src_path:
            QMessageBox.warning(self, "未找到 Word 文档",
                                "当前项目尚未生成 Step4 的 Word 文档（请先完成第四步预览）。")
            return
        dest, _ = QFileDialog.getSaveFileName(self, "导出 Word", src_path,
                                              "Word 文档 (*.docx)")
        if not dest:
            return
        if not dest.lower().endswith(".docx"):
            dest += ".docx"
        try:
            export_docx(src_path, dest)
            QMessageBox.information(self, "导出完成", f"已导出（含批注）:\n{dest}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "导出失败", f"{type(e).__name__}: {e}")

    def on_batch_export_drafts_clicked(self):
        """批量导出：一稿一 docx（Step5）。"""
        try:
            from src.services.step4_word_service import export_drafts_batch
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "导出失败", f"Word 服务不可用: {e}")
            return
        if not self.current_project_id:
            QMessageBox.warning(self, "缺少项目", "请先选择项目。")
            return
        default_dir = ""
        try:
            from src.services.project_storage_service import ProjectStorageService
            from src.services.database_service import DatabaseService
            svc = ProjectStorageService(DatabaseService())
            storage = str(svc.get_project_storage_path(str(self.current_project_id)))
            default_dir = os.path.join(storage, "exports", "step5") if storage else ""
        except Exception:
            default_dir = ""
        target = QFileDialog.getExistingDirectory(self, "选择批量导出目录",
                                                  default_dir or "")
        if not target:
            return
        try:
            paths = export_drafts_batch(str(self.current_project_id), dest_dir=target)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "导出失败", f"{type(e).__name__}: {e}")
            return
        if not paths:
            QMessageBox.warning(self, "无稿件", "当前项目没有可导出的草稿（或内容为空）。")
            return
        QMessageBox.information(self, "批量导出完成",
                                f"共导出 {len(paths)} 份 Word（一稿一 docx）:\n{target}")

    def load_drafts_from_db(self):
        """Load drafts from database"""
        if not self.current_project_id:
            return
            
        db_drafts = self.project_service.get_project_drafts(self.current_project_id)
        
        # Convert DB rows to UI format if needed
        self.draft_history = []
        for row in db_drafts:
            logs_text = row.get('logs', '') or ''
            requires_manual_completion = False
            manual_completion_reason = ""
            missing_data_count = 0
            try:
                parsed_logs = json.loads(logs_text) if logs_text.strip().startswith("{") else {}
                if isinstance(parsed_logs, dict):
                    requires_manual_completion = bool(parsed_logs.get("requires_manual_completion", False))
                    manual_completion_reason = str(parsed_logs.get("manual_completion_reason", "") or "")
                    missing_data_count = int(parsed_logs.get("missing_data_count", 0) or 0)
            except Exception:
                pass
            draft = {
                "id": row['id'],
                "project_id": row['project_id'],
                "title": row.get('title') or "Untitled Draft",
                "timestamp": row['updated_at'], # Use updated_at as display time
                "abstract_preview": row['content'][:200] + "...",
                "model": row.get('model', 'unknown'),
                "user_score": row.get('score', 0),
                "final_text": row['content'],
                "logs": logs_text,
                "requires_manual_completion": requires_manual_completion,
                "manual_completion_reason": manual_completion_reason,
                "missing_data_count": missing_data_count,
            }
            self.draft_history.append(draft)
            
        self.refresh_list()
        self.update_stats()
        self.logger.info(f"Loaded {len(self.draft_history)} drafts for project {self.current_project_id}")

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # 1. Top Dashboard (Stats)
        self.stats_frame = QFrame()
        self.stats_frame.setObjectName("fbStatsFrame")
        stats_layout = QHBoxLayout(self.stats_frame)
        
        self.stat_total = QLabel("Total Drafts: 0")
        self.stat_avg_score = QLabel("Avg Score: -")
        
        self.dashboard_title = QLabel("<b>📊 Optimization Dashboard</b>")
        stats_layout.addWidget(self.dashboard_title)
        stats_layout.addStretch()
        stats_layout.addWidget(self.stat_total)
        stats_layout.addSpacing(20)
        stats_layout.addWidget(self.stat_avg_score)
        
        layout.addWidget(self.stats_frame)
        
        # 2. Filters
        filter_layout = QHBoxLayout()
        self.filter_label = QLabel("Filter by:")
        filter_layout.addWidget(self.filter_label)
        self.combo_sort = QComboBox()
        self.combo_sort.addItems(["Newest First", "Highest Score", "Lowest Score"])
        self.combo_sort.currentIndexChanged.connect(lambda _: self.refresh_list())
        filter_layout.addWidget(self.combo_sort)
        self.chk_manual_only = QCheckBox("仅显示需人工补充")
        self.chk_manual_only.stateChanged.connect(lambda _: self.refresh_list())
        filter_layout.addWidget(self.chk_manual_only)
        filter_layout.addStretch()
        self.btn_export_word = QPushButton("导出 Word")
        try:
            apply_icon(self.btn_export_word, "download", "text", 16)
        except Exception:
            pass
        self.btn_export_word.clicked.connect(self.on_export_word_clicked)
        filter_layout.addWidget(self.btn_export_word)
        self.btn_export_drafts = QPushButton("批量导出草稿")
        try:
            apply_icon(self.btn_export_drafts, "folder", "text", 16)
        except Exception:
            pass
        self.btn_export_drafts.clicked.connect(self.on_batch_export_drafts_clicked)
        filter_layout.addWidget(self.btn_export_drafts)
        layout.addLayout(filter_layout)
        
        # 3. Card Stream (Scroll Area)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setAlignment(Qt.AlignTop)
        
        scroll.setWidget(self.cards_container)
        layout.addWidget(scroll)

        self._apply_theme()

    # ---------------------------------------------------- 主题
    @staticmethod
    def theme_colors() -> dict:
        """当前主题下的仪表盘配色（构造期与热切换共用）。"""
        try:
            from src.utils.skeuomorphic import SKIN_ENABLED, current_palette
            if SKIN_ENABLED:
                p = current_palette()
                dark = p.name == "dark"
                return {
                    "dark": dark,
                    "stats_bg": p.s600 if dark else p.s300,
                    "stat_text": p.text if dark else "",
                    "stat_text2": p.text_dim if dark else "",
                    "title": p.chip_text if dark else "",
                }
        except Exception:
            pass
        try:
            from src.utils.theme_manager import ThemeManager
            is_dark = ThemeManager.get_current_theme() == "dark"
        except Exception:
            is_dark = False
        return {
            "dark": is_dark,
            "stats_bg": "#3E3E3E" if is_dark else "#f0f0f0",
            "stat_text": "#F5D0FE" if is_dark else "",
            "stat_text2": "#E9D5FF" if is_dark else "",
            "title": "#F0ABFC" if is_dark else "",
        }

    def _apply_theme(self):
        """套用 / 重刷仪表盘配色（幂等；浅色下置空 → 交给全局皮肤）。"""
        c = self.theme_colors()
        try:
            self.stats_frame.setStyleSheet(
                "background-color: %s; border-radius: 8px;" % c["stats_bg"])
        except Exception:
            pass
        for w, key in ((self.stat_total, "stat_text"),
                       (self.stat_avg_score, "stat_text2")):
            try:
                w.setStyleSheet(("color: %s; font-weight: 600;" % c[key]) if c[key] else "")
            except Exception:
                pass
        try:
            self.dashboard_title.setStyleSheet(
                ("color: %s;" % c["title"]) if c["title"] else "")
        except Exception:
            pass
        try:
            self.filter_label.setStyleSheet(
                ("color: %s; font-weight: 600;" % c["stat_text2"]) if c["stat_text2"] else "")
        except Exception:
            pass

    def refresh_theme(self):
        """主题热切换协议：重刷仪表盘 + 全部卡片。"""
        self._apply_theme()
        try:
            for card in self.cards_container.findChildren(DraftCard):
                card.refresh_theme()
        except Exception:
            pass

    def load_mock_data(self):
        """Load some mock drafts for testing UI"""
        mock_drafts = [
            {
                "id": "draft_001",
                "title": "Deep Learning in CT Angiography",
                "timestamp": "2026-01-01 14:30",
                "abstract_preview": "This study explores the efficacy of deep learning models in detecting coronary stenosis...",
                "model": "llama3",
                "user_score": 8,
                "final_text": "Full text content of draft 001...",
                "logs": "Critic: Good flow.\nRefiner: Fixed typo."
            },
            {
                "id": "draft_002",
                "title": "Automated Segmentation of Liver Tumors",
                "timestamp": "2026-01-01 16:45",
                "abstract_preview": "We present a novel U-Net architecture for precise liver tumor segmentation from CT scans...",
                "model": "qwen3-vl",
                "user_score": 0, # Not rated
                "final_text": "Full text content of draft 002...",
                "logs": "Critic: Methods section unclear.\nRefiner: Added details."
            }
        ]
        for d in mock_drafts:
            self.add_draft(d)
            
    def add_draft(self, draft_data):
        """Add a draft to the list (called from Step 4 or DB load)"""
        # Generate ID if missing
        if 'id' not in draft_data:
            import uuid
            draft_data['id'] = f"draft_{str(uuid.uuid4())[:8]}"
            
        # Default fields
        if 'timestamp' not in draft_data:
            from datetime import datetime
            draft_data['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M")
            
        if 'project_id' not in draft_data:
            draft_data['project_id'] = self.current_project_id or "default"

        # Update Memory
        # Ensure we don't have duplicates by ID
        existing_idx = next((i for i, d in enumerate(self.draft_history) if d.get('id') == draft_data['id']), -1)
        if existing_idx >= 0:
             self.draft_history[existing_idx] = draft_data
        else:
            self.draft_history.insert(0, draft_data) # Prepend
            
        # Persist to DB
        success = self.project_service.save_draft(draft_data)
        if not success:
            self.logger.error(f"Failed to persist draft {draft_data['id']}")
        
        self.refresh_list()
        self.update_stats()

    def load_draft(self, text, source_info=None):
        """
        Receive draft text from Step 4.
        Creates a new draft entry and adds it to the list.
        """
        # Extract title from source_info or text
        title = "Untitled Draft"
        if source_info and 'title' in source_info:
             title = source_info['title']
        else:
            # Fallback extraction
            lines = text.strip().split('\n')
            if lines:
                potential_title = lines[0].strip().replace('#', '').strip()
                if potential_title:
                    title = potential_title[:50] # Limit length

        # Create draft object
        metadata = source_info or {}
        requires_manual_completion = bool(metadata.get("requires_manual_completion", False))
        missing_data_count = int(metadata.get("missing_data_count", 0) or 0)
        manual_completion_reason = str(metadata.get("manual_completion_reason", "") or "")
        logs_payload = {
            "logs": metadata.get("logs", "") if metadata else "",
            "requires_manual_completion": requires_manual_completion,
            "manual_completion_reason": manual_completion_reason,
            "missing_data_count": missing_data_count,
            "missing_data_tokens": metadata.get("missing_data_tokens", []) if metadata else [],
        }
        draft = {
            "title": title,
            "content": text, # Changed from final_text to content for DB compatibility
            "final_text": text, # Keep for UI compatibility if needed
            "abstract_preview": text[:200] + "...", # Simple preview
            "model": metadata.get('model', 'unknown') if metadata else 'unknown',
            "logs": json.dumps(logs_payload, ensure_ascii=False),
            "user_score": 0,
            "project_id": self.current_project_id or "default",
            "requires_manual_completion": requires_manual_completion,
            "manual_completion_reason": manual_completion_reason,
            "missing_data_count": missing_data_count,
        }
        
        self.add_draft(draft)
        self.logger.info(f"Loaded new draft from Step 4: {title}")

    def refresh_list(self):
        # Clear existing
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        drafts = list(self.draft_history)
        if hasattr(self, "chk_manual_only") and self.chk_manual_only.isChecked():
            drafts = [d for d in drafts if bool(d.get("requires_manual_completion", False))]

        # Sort cards
        sort_mode = self.combo_sort.currentText() if hasattr(self, "combo_sort") else "Newest First"
        if sort_mode == "Highest Score":
            drafts.sort(key=lambda d: int(d.get("user_score") or 0), reverse=True)
        elif sort_mode == "Lowest Score":
            drafts.sort(key=lambda d: int(d.get("user_score") or 0))

        # Add cards
        for draft in drafts:
            card = DraftCard(draft)
            card.clicked.connect(self.show_details_dialog)
            card.score_submitted.connect(self.handle_score_submission)
            self.cards_layout.addWidget(card)

        # 空态占位：无草稿时给图标 + 引导文案，避免整页空白
        if not drafts:
            self.cards_layout.addWidget(self._build_empty_state())

    def _build_empty_state(self):
        """构造「暂无草稿」空态卡片（主题自适应）。"""
        panel = QFrame()
        panel.setObjectName("fbEmptyState")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(30, 60, 30, 60)
        lay.setSpacing(14)
        lay.setAlignment(Qt.AlignCenter)

        icon = QLabel()
        icon.setAlignment(Qt.AlignCenter)
        try:
            apply_pixmap(icon, "chart", "muted", 64)
        except Exception:
            icon.setText("📊")
        lay.addWidget(icon)

        title = QLabel("暂无优化草稿")
        title.setAlignment(Qt.AlignCenter)
        f = title.font()
        f.setPointSizeF(15.0)
        f.setBold(True)
        title.setFont(f)
        lay.addWidget(title)

        hint = QLabel(
            "完成「第四步 科学文本预览生成」并确认草稿后，\n"
            "草稿卡片会出现在这里，可评分、反馈与生成汇报 PPT。"
        )
        hint.setAlignment(Qt.AlignCenter)
        try:
            from src.utils.skeuomorphic import ui_font, SIZE_DIM
            hint.setFont(ui_font(SIZE_DIM, 400))
        except Exception:
            pass
        lay.addWidget(hint)
        return panel

    def update_stats(self):
        total = len(self.draft_history)
        scores = [d['user_score'] for d in self.draft_history if d.get('user_score')]
        avg = sum(scores) / len(scores) if scores else 0
        
        self.stat_total.setText(f"Total Drafts: {total}")
        self.stat_avg_score.setText(f"Avg Score: {avg:.1f}")

    def handle_score_submission(self, draft_id, score):
        for d in self.draft_history:
            if d['id'] == draft_id:
                d['user_score'] = score
                self.logger.info(f"Draft {draft_id} scored: {score}")
                self.update_stats()
                break

    def show_details_dialog(self, draft_data):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Details: {draft_data.get('title')}")
        dialog.resize(1200, 760)
        
        layout = QVBoxLayout(dialog)

        try:
            from src.utils.theme_manager import ThemeManager
            is_dark = ThemeManager.get_current_theme() == "dark"
        except Exception:
            is_dark = False

        font_style = """
            QTextEdit, QTextBrowser {
                font-family: 'Consolas', 'Courier New'; 
                font-size: 14px; 
                line-height: 1.5;
                color: %s;
            }
        """ % ("#F5D0FE" if is_dark else "#2E86AB")

        # Step3-like layout: left logs + right final text via splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle{background:#E0E0E0; width:4px;}")

        txt_view = QTextBrowser()
        txt_view.setStyleSheet(font_style)
        txt_view.setReadOnly(True)
        txt_view.setOpenExternalLinks(True)
        final_text = str(draft_data.get('final_text', '') or "")
        # Repair broken file:// image paths so all generated figures can render.
        def _repair_md_images(text: str) -> str:
            pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
            def _to_fs(url: str) -> str:
                u = str(url or "").strip()
                if u.lower().startswith("file:///"):
                    p = urllib.parse.urlparse(u).path
                    p = urllib.parse.unquote(p)
                    if re.match(r"^/[A-Za-z]:/", p):
                        p = p[1:]
                    return p.replace("/", "\\")
                return u
            def _to_uri(fs: str) -> str:
                try:
                    return Path(os.path.abspath(fs)).as_uri()
                except Exception:
                    return "file:///" + os.path.abspath(fs).replace("\\", "/")
            def _fix(m):
                alt, url = m.group(1), m.group(2).strip()
                fs = _to_fs(url)
                if os.path.exists(fs):
                    return m.group(0)
                d, b = os.path.dirname(fs), os.path.basename(fs)
                if not os.path.isdir(d):
                    return m.group(0)
                b2 = b.replace(" ", "")
                cand = os.path.join(d, b2)
                if os.path.exists(cand):
                    return f"![{alt}]({_to_uri(cand)})"
                for fn in os.listdir(d):
                    if fn.replace(" ", "") == b2 and os.path.exists(os.path.join(d, fn)):
                        return f"![{alt}]({_to_uri(os.path.join(d, fn))})"
                return m.group(0)
            return pattern.sub(_fix, text or "")
        final_text = _repair_md_images(final_text)
        # Convert markdown image syntax to HTML img so Qt can render local file:// images.
        # Same approach as Step3 (ai_summary_widget.py): bypasses setMarkdown's image rendering issues.
        def _md_images_to_html(text):
            def _replace(md):
                src = (md.group(1) or "").strip()
                if not src:
                    return ""
                if src.lower().startswith(("http://", "https://", "file://")):
                    return f'<img src="{src}" style="max-width:95%;"/>'
                return f'<img src="file:///{src}" style="max-width:95%;"/>'
            return re.sub(r"!\[[^\]]*\]\(([^)]+)\)", _replace, text)

        # Last-mile guarantee: append missing exported figure links for this project.
        try:
            pid = str(draft_data.get("project_id") or getattr(self, "current_project_id", "") or "").strip()
            if pid:
                export_dir = os.path.join("f:\\RSNA\\medical_imaging_workflow\\project_storage\\projects", pid, "exports")
                if os.path.isdir(export_dir):
                    urls = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", final_text or "")
                    existing_names = set()
                    for u in urls:
                        p = urllib.parse.urlparse(str(u)).path
                        p = urllib.parse.unquote(p)
                        if re.match(r"^/[A-Za-z]:/", p):
                            p = p[1:]
                        existing_names.add(os.path.basename(p.replace("/", "\\")))
                    missing_lines = []
                    for fn in sorted(os.listdir(export_dir)):
                        low = fn.lower()
                        if not low.endswith((".png", ".jpg", ".jpeg", ".webp")):
                            continue
                        if "sklearn" not in low and "figure" not in low:
                            continue
                        if fn in existing_names:
                            continue
                        uri = Path(os.path.join(export_dir, fn)).as_uri()
                        missing_lines.append(f"![Figure]({uri})")
                    if missing_lines:
                        extra = "\n\n### Figure Render Preview (Auto-Completed)\n\n" + "\n\n".join(missing_lines) + "\n"
                        m = re.search(r"(?im)^(#{1,6}\s*results?\s*)$", final_text or "")
                        if m:
                            start = m.end()
                            tail = final_text[start:]
                            if tail.startswith("\n"):
                                start += 1
                            n = re.search(r"(?m)^\s*#{1,6}\s+\S", tail)
                            if n:
                                pos = start + n.start()
                                final_text = final_text[:pos].rstrip() + extra + "\n\n" + final_text[pos:]
                            else:
                                final_text = final_text.rstrip() + extra
                        else:
                            m2 = re.search(r"(?im)^results?\s*$", final_text or "")
                            if m2:
                                start = m2.end()
                                tail = final_text[start:]
                                if tail.startswith("\n"):
                                    start += 1
                                n = re.search(r"(?m)^\s*#{1,6}\s+\S", tail)
                                if n:
                                    pos = start + n.start()
                                    final_text = final_text[:pos].rstrip() + extra + "\n\n" + final_text[pos:]
                                else:
                                    final_text = final_text.rstrip() + extra
                            else:
                                final_text = final_text.rstrip() + extra
        except Exception as e:
            self.logger.error(f"Error appending missing figures: {e}")
            pass
            
        html_content = _md_images_to_html(final_text)
        
        try:
            import markdown
            html_content = markdown.markdown(html_content, extensions=['tables', 'fenced_code'])
        except ImportError:
            pass

        try:
            txt_view.setHtml(html_content)
        except Exception:
            txt_view.setPlainText(final_text)

        # Left panel: logs (align with Step3 console)
        log_view = QTextEdit()
        log_view.setStyleSheet(font_style)
        log_view.setReadOnly(True)
        log_view.setLineWrapMode(QTextEdit.NoWrap)
        log_view.setPlainText(draft_data.get('logs', 'No logs available.'))

        splitter.addWidget(log_view)
        splitter.addWidget(txt_view)
        splitter.setSizes([400, 1000])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        
        # We will use an outer vertical splitter to give the draft view more space and shrink the tabs
        main_v_splitter = QSplitter(Qt.Vertical)
        main_v_splitter.addWidget(splitter)

        # Keep interaction actions in tabs below (feedback/ppt)
        tabs = QTabWidget()

        # Tab 1: Qualitative Feedback
        feedback_widget = QWidget()
        f_layout = QVBoxLayout(feedback_widget)
        f_layout.addWidget(QLabel("Please provide qualitative feedback to improve the Agent:"))
        f_input = QTextEdit()
        f_input.setPlaceholderText("E.g., The methods section was too brief...")
        submit_btn = QPushButton("Submit Feedback")
        apply_icon(submit_btn, "send", "text", 15)
        
        def save_feedback():
            draft_data['qualitative_feedback'] = f_input.toPlainText()
            self.logger.info(f"Feedback saved for {draft_data['id']}")
            dialog.accept()
            
        submit_btn.clicked.connect(save_feedback)
        f_layout.addWidget(f_input)
        f_layout.addWidget(submit_btn)
        tabs.addTab(feedback_widget, "Feedback")
        
        # Tab 2: PPT Generation
        ppt_widget = QWidget()
        ppt_layout = QVBoxLayout(ppt_widget)
        ppt_layout.addWidget(QLabel("<b>Generate Presentation (Beta)</b>"))
        ppt_layout.addWidget(QLabel("Automatically convert this draft into a scientific PPTX slide deck."))
        
        ppt_btn = QPushButton("Generate PPT")
        apply_icon(ppt_btn, "wand", "text", 15)
        ppt_status = QLabel("Ready")
        
        def do_ppt_gen():
            ppt_btn.setEnabled(False)
            ppt_status.setText("Analyzing structure and generating slides... (This may take a minute)")
            
            # Use draft text
            text = draft_data.get('final_text', '')
            if not text:
                ppt_status.setText("Error: No text in draft.")
                ppt_btn.setEnabled(True)
                return
                
            try:
                # Use shared LLM service
                model = draft_data.get('model', 'llama3') # Use same model or default
                ppt_gen = PPTGenerator(self.llm_service, model)
                
                # Mock async execution for UI responsiveness (In prod use QThread)
                from src.core.qt_compat.QtWidgets import QApplication
                QApplication.processEvents()
                
                res = ppt_gen.generate_ppt(text)
                
                if res['status'] == 'success':
                    ppt_status.setText(f"Success! Saved to:\n{res['file_path']}")
                    # Optional: Open file explorer
                else:
                    ppt_status.setText(f"Failed: {res.get('error')}")
                    
            except Exception as e:
                ppt_status.setText(f"Error: {e}")
            finally:
                ppt_btn.setEnabled(True)
        
        ppt_btn.clicked.connect(do_ppt_gen)
        ppt_layout.addWidget(ppt_btn)
        ppt_layout.addWidget(ppt_status)
        ppt_layout.addStretch()
        
        tabs.addTab(ppt_widget, "PPT Generator")
        
        main_v_splitter.addWidget(tabs)
        main_v_splitter.setSizes([850, 150]) # Give 85% height to draft, 15% to tabs
        main_v_splitter.setStretchFactor(0, 4)
        main_v_splitter.setStretchFactor(1, 1)

        layout.addWidget(main_v_splitter)
        dialog.exec_()
