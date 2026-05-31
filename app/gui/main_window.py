from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QAbstractItemView,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.audio_utils import extract_audio
from app.core.cutter import (
    ClipItem,
    export_clips,
    export_timeline_video,
    extract_clip_thumbnail,
    extract_video_frame,
)
from app.core.database import TranscriptDatabase
from app.core.montage import (
    ROUGH_CUT_COLOR_GRADES,
    RoughCutConfig,
    build_rough_cut_plan,
    build_conflict_hook,
    combine_rough_cut_parts,
    detect_conflict_hook_segment,
    export_story_rough_cut,
)
from app.core.ocr_subtitle import ocr_burned_subtitles
from app.core.project_manager import PROJECT_EXTENSION, ProjectData, ProjectManager
from app.core.scene_utils import extract_scene_frames, format_scene_note_for_script
from app.core.script_generator import (
    RuleBasedScriptGenerator,
    SUPPORTED_SCRIPT_LANGUAGES,
    SUPPORTED_SCRIPT_STYLES,
)
from app.core.subtitle_utils import (
    extract_best_subtitle_segments,
    prepare_subtitle_segments,
    subtitle_file_to_segments,
    write_srt_file,
)
from app.core.text_importer import read_text_file, text_to_transcript_segments
from app.core.transcriber import WhisperTranscriber
from app.core.translator import LocalIndonesianTranslator
from app.core.video_utils import VideoMetadata, format_duration, metadata_to_text, read_video_metadata
from app.core.vision_captioner import auto_caption_scene_notes
from app.gui.widgets import (
    ChecklistWidget,
    CutListTable,
    LogPanel,
    ManualClipTable,
    RoughCutRangeSelector,
    SceneNotesTable,
    TimelineClipTable,
    TranscriptTable,
    VideoPreviewPanel,
    VideoCutEditorWidget,
)
from app.gui.tasking import TaskFunction, TaskProgressDialog, TaskWorker
from app.viewmodels import (
    EditorViewModel,
    TimelineDurationConfig,
    safe_project_filename,
    time_for_filename,
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("StoryCut AI")
        self.resize(1240, 820)

        self.app_root = Path(__file__).resolve().parents[2]
        self.project_manager = ProjectManager(self.app_root / "app" / "projects")
        self.project: ProjectData | None = None
        self.database: TranscriptDatabase | None = None
        self.rough_cut_parts: list[dict[str, Any]] = []
        self.editor_vm = EditorViewModel(history_limit=80)
        self._workers: list[TaskWorker] = []
        self._task_dialogs: dict[TaskWorker, TaskProgressDialog] = {}
        self._busy_count = 0

        self._build_ui()
        self.refresh_shortcut = QShortcut(QKeySequence("F5"), self)
        self.refresh_shortcut.activated.connect(self.refresh_project)
        self.undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self.undo_shortcut.activated.connect(self.undo_editor_change)
        self.redo_shortcut = QShortcut(QKeySequence.StandardKey.Redo, self)
        self.redo_shortcut.activated.connect(self.redo_editor_change)
        self._reset_editor_history()
        self._set_project_label()
        self.statusBar().showMessage("Ready")

    def _build_ui(self) -> None:
        self._apply_modern_theme()
        self._build_file_menu()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.project_group = self._build_project_group()
        self.project_group.hide()
        self.media_group = self._build_media_group()
        self.media_group.hide()
        self.project_status_label = QLabel("No project loaded")
        self.statusBar().addPermanentWidget(self.project_status_label, 1)

        self.tabs = QTabWidget()
        self.cuts_tab = self._build_cuts_tab()
        self.rough_cut_tab = self._build_rough_cut_tab()
        self.subtitle_tab = self._build_indonesian_subtitle_tab()
        self.transcript_tab = self._build_transcript_tab()
        self.scenes_tab = self._build_scenes_tab()
        self.script_tab = self._build_script_tab()
        self.checklist_tab = self._build_checklist_tab()
        self.logs_tab = self._build_logs_tab()

        self.tabs.addTab(self.cuts_tab, "Editor")
        self.tabs.addTab(self.rough_cut_tab, "Rough Cut")
        self.tabs.addTab(self.subtitle_tab, "Subtitle Indonesia")
        self._hidden_pages = [
            self.transcript_tab,
            self.scenes_tab,
            self.script_tab,
            self.checklist_tab,
            self.logs_tab,
        ]
        layout.addWidget(self.tabs, 1)

        self.long_task_buttons = [
            self.metadata_button,
            self.extract_audio_button,
            self.transcribe_button,
            self.voice_to_id_script_button,
            self.extract_scene_frames_button,
            self.auto_scene_notes_button,
            self.extract_subtitle_button,
            self.ocr_subtitle_button,
            self.export_button,
            self.export_manual_clips_button,
            self.preview_all_timeline_button,
            self.build_timeline_rough_cut_button,
            self.build_rough_timeline_button,
            self.export_rough_cut_button,
            self.combine_rough_parts_button,
            self.generate_id_subtitle_button,
            self.refresh_project_button,
        ]

    def _build_file_menu(self) -> None:
        self.menuBar().clear()
        file_menu = self.menuBar().addMenu("File")

        self.new_project_action = QAction("New Project", self)
        self.open_project_action = QAction("Open Project", self)
        self.save_project_action = QAction("Save Project", self)
        self.import_video_ori_action = QAction("Import Video Ori", self)
        self.read_metadata_action = QAction("Read Video Ori Metadata", self)
        self.refresh_project_action = QAction("Refresh Project", self)
        self.export_video_action = QAction("Export Video", self)

        self.new_project_action.triggered.connect(self.new_project)
        self.open_project_action.triggered.connect(self.load_project)
        self.save_project_action.triggered.connect(lambda: self.save_project(show_message=True))
        self.import_video_ori_action.triggered.connect(self.import_video)
        self.read_metadata_action.triggered.connect(self.read_metadata)
        self.refresh_project_action.triggered.connect(self.refresh_project)
        self.export_video_action.triggered.connect(self.export_final_video)

        file_menu.addAction(self.new_project_action)
        file_menu.addAction(self.open_project_action)
        file_menu.addAction(self.save_project_action)
        file_menu.addAction(self.refresh_project_action)
        file_menu.addSeparator()
        file_menu.addAction(self.import_video_ori_action)
        file_menu.addAction(self.read_metadata_action)
        file_menu.addSeparator()
        file_menu.addAction(self.export_video_action)

    def _apply_modern_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #0b1018;
                color: #e5e7eb;
                font-family: "Segoe UI";
                font-size: 10pt;
            }
            QGroupBox {
                background: #141b26;
                border: 1px solid #263244;
                border-radius: 8px;
                margin-top: 12px;
                padding: 14px 12px 12px 12px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
                background: #0b1018;
                color: #cbd5e1;
            }
            QFrame#EditorPanel {
                background: #111827;
                border: 1px solid #263244;
                border-radius: 8px;
            }
            QVideoWidget#VideoPreview {
                background: #030712;
                border: 1px solid #263244;
                border-radius: 8px;
            }
            QLabel#PanelTitle {
                color: #f8fafc;
                font-size: 12pt;
                font-weight: 700;
            }
            QPushButton, QToolButton {
                background: #1f2937;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #e5e7eb;
                padding: 7px 12px;
                min-height: 28px;
            }
            QToolButton#TransportButton {
                padding: 4px;
                min-width: 34px;
                min-height: 32px;
            }
            QPushButton:hover, QToolButton:hover {
                background: #263244;
                border-color: #60a5fa;
            }
            QPushButton:pressed, QToolButton:pressed {
                background: #172033;
            }
            QPushButton#PrimaryButton {
                background: #2563eb;
                border-color: #3b82f6;
                color: #f8fafc;
                font-weight: 700;
            }
            QPushButton#PrimaryButton:hover {
                background: #1d4ed8;
            }
            QPushButton:disabled, QToolButton:disabled {
                color: #64748b;
                background: #111827;
                border-color: #263244;
            }
            QDialog {
                background: #0b1018;
            }
            QMenuBar {
                background: #0b1018;
                color: #e5e7eb;
                border-bottom: 1px solid #263244;
            }
            QMenuBar::item {
                background: transparent;
                padding: 6px 12px;
            }
            QMenuBar::item:selected {
                background: #172033;
                border-radius: 4px;
            }
            QMenu {
                background: #111827;
                border: 1px solid #263244;
                color: #e5e7eb;
                padding: 6px;
            }
            QMenu::item {
                padding: 7px 28px 7px 14px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: #2563eb;
            }
            QProgressBar {
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 6px;
                min-height: 12px;
            }
            QProgressBar::chunk {
                background: #2563eb;
                border-radius: 5px;
            }
            QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #e5e7eb;
                padding: 5px 8px;
                selection-background-color: #1d4ed8;
                selection-color: #f8fafc;
            }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus,
            QSpinBox:focus, QDoubleSpinBox:focus {
                border-color: #60a5fa;
            }
            QComboBox QAbstractItemView {
                background: #111827;
                border: 1px solid #334155;
                color: #e5e7eb;
                selection-background-color: #2563eb;
                selection-color: #f8fafc;
            }
            QCheckBox {
                color: #dbe4ef;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #475569;
                background: #0f172a;
            }
            QCheckBox::indicator:checked {
                background: #2563eb;
                border-color: #60a5fa;
            }
            QTabWidget::pane {
                border: 1px solid #263244;
                border-radius: 8px;
                background: #111827;
                top: -1px;
            }
            QTabBar::tab {
                background: #151f2e;
                border: 1px solid #263244;
                border-bottom-color: #263244;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                color: #94a3b8;
                padding: 9px 14px;
                margin-right: 2px;
            }
            QTabBar::tab:hover {
                background: #1f2937;
                color: #dbe4ef;
            }
            QTabBar::tab:selected {
                background: #111827;
                border-bottom-color: #111827;
                color: #f8fafc;
                font-weight: 700;
            }
            QTableWidget {
                background: #0f172a;
                alternate-background-color: #111827;
                border: 1px solid #263244;
                border-radius: 8px;
                gridline-color: #263244;
                color: #e5e7eb;
                selection-background-color: #1d4ed8;
                selection-color: #f8fafc;
            }
            QHeaderView::section {
                background: #172033;
                border: 0;
                border-right: 1px solid #263244;
                border-bottom: 1px solid #263244;
                color: #cbd5e1;
                font-weight: 700;
                padding: 7px 8px;
            }
            QTableCornerButton::section {
                background: #172033;
                border: 0;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #2f3b4e;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #f97316;
                border: 1px solid #ea580c;
                width: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
            QScrollArea {
                border: 0;
                background: transparent;
            }
            QScrollBar:vertical, QScrollBar:horizontal {
                background: #0b1018;
                border: 0;
                margin: 0;
            }
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
                background: #334155;
                border-radius: 6px;
                min-height: 24px;
                min-width: 24px;
            }
            QScrollBar::handle:hover {
                background: #475569;
            }
            QScrollBar::add-line, QScrollBar::sub-line {
                width: 0;
                height: 0;
            }
            QStatusBar {
                background: #111827;
                color: #94a3b8;
                border-top: 1px solid #263244;
            }
            """
        )

    def _build_project_group(self) -> QGroupBox:
        group = QGroupBox("Project")
        layout = QHBoxLayout(group)

        self.project_label = QLabel()
        self.new_project_button = QPushButton("New Project")
        self.load_project_button = QPushButton("Open Project")
        self.refresh_project_button = QPushButton("Refresh Project")
        self.refresh_project_button.setToolTip("Reload current project from disk (F5)")
        self.save_project_button = QPushButton("Save Project")

        self.new_project_button.clicked.connect(self.new_project)
        self.load_project_button.clicked.connect(self.load_project)
        self.refresh_project_button.clicked.connect(self.refresh_project)
        self.save_project_button.clicked.connect(lambda: self.save_project(show_message=True))

        layout.addWidget(self.project_label, 1)
        layout.addWidget(self.new_project_button)
        layout.addWidget(self.load_project_button)
        layout.addWidget(self.refresh_project_button)
        layout.addWidget(self.save_project_button)
        return group

    def _build_media_group(self) -> QGroupBox:
        group = QGroupBox("Video Ori")
        outer = QHBoxLayout(group)

        controls = QWidget()
        controls_layout = QFormLayout(controls)

        self.import_video_button = QPushButton("Import Video Ori")
        self.metadata_button = QPushButton("Read Metadata")
        self.extract_audio_button = QPushButton("Extract Audio")
        self.transcribe_button = QPushButton("Transcribe")
        self.voice_to_id_script_button = QPushButton("Voice -> ID Script")

        self.import_video_button.clicked.connect(self.import_video)
        self.metadata_button.clicked.connect(self.read_metadata)
        self.extract_audio_button.clicked.connect(self.extract_audio)
        self.transcribe_button.clicked.connect(self.transcribe_audio)
        self.voice_to_id_script_button.clicked.connect(self.voice_to_indonesian_script)

        button_row = QHBoxLayout()
        button_row.addWidget(self.import_video_button)
        button_row.addWidget(self.metadata_button)
        controls_layout.addRow(button_row)

        self.extract_audio_button.hide()
        self.transcribe_button.hide()
        self.voice_to_id_script_button.hide()

        self.model_combo = QComboBox()
        self.model_combo.addItems(["base", "small", "medium", "large-v3"])
        self.model_combo.setEditable(True)
        self.model_combo.setCurrentText("small")
        self.device_combo = QComboBox()
        self.device_combo.addItems(["cpu", "cuda"])
        self.compute_combo = QComboBox()
        self.compute_combo.addItems(["int8", "float16", "float32"])
        self.language_input = QLineEdit()
        self.language_input.setPlaceholderText("Optional, e.g. en or id")

        self.metadata_view = QTextEdit()
        self.metadata_view.setReadOnly(True)
        self.metadata_view.setMinimumHeight(120)
        self.metadata_view.setText(metadata_to_text(None))

        outer.addWidget(controls, 0)
        outer.addWidget(self.metadata_view, 1)
        return group

    def _build_scenes_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        row = QHBoxLayout()
        self.scene_interval_spin = QSpinBox()
        self.scene_interval_spin.setRange(2, 120)
        self.scene_interval_spin.setValue(10)
        self.scene_interval_spin.setSuffix(" sec")
        self.scene_max_frames_spin = QSpinBox()
        self.scene_max_frames_spin.setRange(5, 500)
        self.scene_max_frames_spin.setValue(120)
        self.extract_scene_frames_button = QPushButton("Extract Scene Frames")
        self.auto_scene_notes_button = QPushButton("Auto Describe Empty Notes")
        self.save_scene_notes_button = QPushButton("Save Scene Notes")

        self.extract_scene_frames_button.clicked.connect(self.extract_scene_frames_for_notes)
        self.auto_scene_notes_button.clicked.connect(self.auto_describe_scene_notes)
        self.save_scene_notes_button.clicked.connect(lambda: self.save_project(show_message=True))

        row.addWidget(QLabel("Interval"))
        row.addWidget(self.scene_interval_spin)
        row.addWidget(QLabel("Max frames"))
        row.addWidget(self.scene_max_frames_spin)
        row.addStretch(1)
        row.addWidget(self.extract_scene_frames_button)
        row.addWidget(self.auto_scene_notes_button)
        row.addWidget(self.save_scene_notes_button)
        layout.addLayout(row)

        self.scene_table = SceneNotesTable()
        layout.addWidget(self.scene_table, 1)
        return page

    def _build_transcript_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search transcript text")
        self.search_button = QPushButton("Search")
        self.show_all_button = QPushButton("Show All")
        self.import_text_button = QPushButton("Import TXT Transcript")
        self.import_subtitle_button = QPushButton("Import Subtitle File")
        self.extract_subtitle_button = QPushButton("Extract ID Subtitles")
        self.ocr_subtitle_button = QPushButton("OCR Burned Subtitles")
        self.add_to_cut_button = QPushButton("Add Selected to Manual Clips")

        self.search_button.clicked.connect(self.search_transcript)
        self.show_all_button.clicked.connect(self.show_all_transcript)
        self.import_text_button.clicked.connect(self.import_text_transcript)
        self.import_subtitle_button.clicked.connect(self.import_subtitle_file)
        self.extract_subtitle_button.clicked.connect(self.extract_indonesian_subtitles)
        self.ocr_subtitle_button.clicked.connect(self.ocr_burned_subtitles)
        self.add_to_cut_button.clicked.connect(self.add_selected_to_cut_list)
        self.search_input.returnPressed.connect(self.search_transcript)

        row.addWidget(self.search_input, 1)
        row.addWidget(self.search_button)
        row.addWidget(self.show_all_button)
        row.addWidget(self.import_text_button)
        row.addWidget(self.import_subtitle_button)
        row.addWidget(self.extract_subtitle_button)
        row.addWidget(self.ocr_subtitle_button)
        row.addWidget(self.add_to_cut_button)
        layout.addLayout(row)

        self.transcript_table = TranscriptTable()
        layout.addWidget(self.transcript_table, 1)
        return page

    def _build_cuts_tab(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page_layout.addWidget(scroll_area, 1)

        content = QWidget()
        content.setMinimumHeight(2300)
        scroll_area.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 26, 28)
        layout.setSpacing(8)

        video_ori_group = QGroupBox("Video Ori Preview")
        video_ori_group.setMinimumHeight(690)
        video_ori_layout = QVBoxLayout(video_ori_group)
        video_ori_layout.setContentsMargins(10, 18, 10, 10)
        video_ori_layout.setSpacing(8)
        self.visual_cut_editor = VideoCutEditorWidget()
        self.visual_cut_editor.setMinimumHeight(650)
        self.visual_cut_editor.video_widget.setMinimumHeight(300)
        self.visual_cut_editor.video_widget.setMaximumHeight(360)
        self.visual_cut_editor.add_clip_button.setText("Save Manual Clip")
        self.visual_cut_editor.add_photo_button.setText("Save Photo")
        self.visual_cut_editor.apply_clip_button.setText("Update Manual")
        self.visual_cut_editor.addClipRequested.connect(self.add_visual_cut_to_list)
        self.visual_cut_editor.addPhotoRequested.connect(self.add_visual_photo_to_list)
        self.visual_cut_editor.updateClipRequested.connect(self.apply_visual_range_to_selected_cut)
        video_ori_layout.addWidget(self.visual_cut_editor, 1)
        layout.addWidget(video_ori_group, 0)

        editor_split = QSplitter(Qt.Orientation.Horizontal)
        editor_split.setChildrenCollapsible(False)
        editor_split.setMinimumHeight(1380)
        editor_split.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.MinimumExpanding,
        )

        manual_panel = QGroupBox("Manual Clips")
        manual_panel.setMinimumHeight(1360)
        manual_panel.setMinimumWidth(520)
        manual_layout = QVBoxLayout(manual_panel)
        manual_layout.setContentsMargins(10, 18, 10, 10)
        manual_layout.setSpacing(8)
        manual_toolbar = QVBoxLayout()
        manual_toolbar.setContentsMargins(0, 0, 0, 0)
        manual_toolbar.setSpacing(6)
        manual_add_toolbar = QHBoxLayout()
        manual_add_toolbar.setContentsMargins(0, 0, 0, 0)
        manual_add_toolbar.setSpacing(6)
        manual_edit_toolbar = QHBoxLayout()
        manual_edit_toolbar.setContentsMargins(0, 0, 0, 0)
        manual_edit_toolbar.setSpacing(6)
        self.add_manual_to_timeline_button = QPushButton("Add Selected")
        self.add_manual_to_timeline_button.setToolTip("Add selected Manual Clips to Main Timeline")
        self.add_all_manual_to_timeline_button = QPushButton("Add All")
        self.add_all_manual_to_timeline_button.setToolTip("Add all Manual Clips to Main Timeline")
        self.remove_cut_button = QPushButton("Remove")
        self.remove_cut_button.setToolTip("Remove selected Manual Clips")
        self.export_manual_clips_button = QPushButton("Export Clips")
        self.export_manual_clips_button.setToolTip("Export selected Manual Clips")
        self.add_manual_to_timeline_button.clicked.connect(self.add_selected_manual_clips_to_timeline)
        self.add_all_manual_to_timeline_button.clicked.connect(self.add_all_manual_clips_to_timeline)
        self.remove_cut_button.clicked.connect(self.remove_selected_cuts)
        self.export_manual_clips_button.clicked.connect(self.export_selected_clips)
        manual_add_toolbar.addWidget(self.add_manual_to_timeline_button)
        manual_add_toolbar.addWidget(self.add_all_manual_to_timeline_button)
        manual_add_toolbar.addStretch(1)
        manual_edit_toolbar.addWidget(self.remove_cut_button)
        manual_edit_toolbar.addStretch(1)
        manual_edit_toolbar.addWidget(self.export_manual_clips_button)
        manual_toolbar.addLayout(manual_add_toolbar)
        manual_toolbar.addLayout(manual_edit_toolbar)
        manual_layout.addLayout(manual_toolbar)
        self.cut_table = ManualClipTable()
        self.cut_table.setMinimumWidth(500)
        self.cut_table.itemSelectionChanged.connect(self.preview_selected_cut_range)
        self.cut_table.itemChanged.connect(self._on_editor_manual_changed)
        self.cut_table.itemDoubleClicked.connect(self.add_manual_clip_from_double_click)
        manual_layout.addWidget(self.cut_table, 1)

        timeline_panel = QGroupBox("Main Timeline - Rough Cut")
        timeline_panel.setMinimumHeight(1360)
        timeline_layout = QVBoxLayout(timeline_panel)
        timeline_layout.setContentsMargins(10, 18, 10, 10)
        timeline_layout.setSpacing(8)

        timeline_toolbar = QVBoxLayout()
        timeline_toolbar.setContentsMargins(0, 0, 0, 0)
        timeline_toolbar.setSpacing(6)
        timeline_primary_toolbar = QHBoxLayout()
        timeline_primary_toolbar.setContentsMargins(0, 0, 0, 0)
        timeline_primary_toolbar.setSpacing(6)
        timeline_edit_toolbar = QHBoxLayout()
        timeline_edit_toolbar.setContentsMargins(0, 0, 0, 0)
        timeline_edit_toolbar.setSpacing(6)
        self.build_timeline_rough_cut_button = QPushButton("Build")
        self.build_timeline_rough_cut_button.setToolTip("Build Rough Cut Timeline")
        self.preview_all_timeline_button = QPushButton("Preview All")
        self.preview_all_timeline_button.setToolTip("Preview all clips in Main Timeline")
        self.trim_timeline_clip_button = QPushButton("Trim")
        self.trim_timeline_clip_button.setToolTip("Trim selected timeline clip to Video Ori selection")
        self.split_timeline_clip_button = QPushButton("Split")
        self.timeline_zoom_out_button = QPushButton("Zoom -")
        self.timeline_zoom_in_button = QPushButton("Zoom +")
        self.undo_editor_button = QPushButton("Undo")
        self.redo_editor_button = QPushButton("Redo")
        self.export_button = QPushButton("Export")
        self.export_button.setToolTip("Export full Main Timeline video")
        self.export_button.setObjectName("PrimaryButton")
        self.build_timeline_rough_cut_button.clicked.connect(self.build_rough_cut_timeline)
        self.preview_all_timeline_button.clicked.connect(self.preview_full_timeline_video)
        self.trim_timeline_clip_button.clicked.connect(self.trim_selected_timeline_to_video_ori_selection)
        self.split_timeline_clip_button.clicked.connect(self.split_selected_timeline_clip)
        self.timeline_zoom_out_button.clicked.connect(lambda: self.adjust_timeline_zoom(-0.2))
        self.timeline_zoom_in_button.clicked.connect(lambda: self.adjust_timeline_zoom(0.2))
        self.undo_editor_button.clicked.connect(self.undo_editor_change)
        self.redo_editor_button.clicked.connect(self.redo_editor_change)
        self.export_button.clicked.connect(self.export_final_video)
        for button in (
            self.build_timeline_rough_cut_button,
            self.preview_all_timeline_button,
            self.trim_timeline_clip_button,
        ):
            timeline_primary_toolbar.addWidget(button)
        timeline_primary_toolbar.addStretch(1)
        timeline_primary_toolbar.addWidget(self.export_button)
        for button in (
            self.split_timeline_clip_button,
            self.timeline_zoom_out_button,
            self.timeline_zoom_in_button,
            self.undo_editor_button,
            self.redo_editor_button,
        ):
            timeline_edit_toolbar.addWidget(button)
        timeline_edit_toolbar.addStretch(1)
        timeline_toolbar.addLayout(timeline_primary_toolbar)
        timeline_toolbar.addLayout(timeline_edit_toolbar)
        timeline_layout.addLayout(timeline_toolbar)

        export_row = QWidget()
        export_layout = QVBoxLayout(export_row)
        export_layout.setContentsMargins(0, 0, 0, 0)
        export_layout.setSpacing(6)
        export_format_layout = QHBoxLayout()
        export_format_layout.setContentsMargins(0, 0, 0, 0)
        export_format_layout.setSpacing(8)
        export_quality_layout = QHBoxLayout()
        export_quality_layout.setContentsMargins(0, 0, 0, 0)
        export_quality_layout.setSpacing(8)
        export_output_layout = QHBoxLayout()
        export_output_layout.setContentsMargins(0, 0, 0, 0)
        export_output_layout.setSpacing(8)
        self.export_resolution_combo = QComboBox()
        self.export_resolution_combo.addItems(["1280x720", "1920x1080", "854x480", "Original"])
        self.export_fps_spin = QDoubleSpinBox()
        self.export_fps_spin.setRange(0.0, 120.0)
        self.export_fps_spin.setDecimals(3)
        self.export_fps_spin.setSingleStep(1.0)
        self.export_fps_spin.setSpecialValueText("Original")
        self.export_fps_spin.setValue(30.0)
        self.export_bitrate_input = QLineEdit("4500k")
        self.export_bitrate_input.setPlaceholderText("e.g. 4500k")
        self.export_output_input = QLineEdit()
        self.export_output_input.setPlaceholderText("Choose final MP4 output path")
        self.export_output_browse_button = QPushButton("Browse")
        self.export_output_browse_button.clicked.connect(self.choose_export_output_file)
        self.timeline_total_label = QLabel("Timeline total: 00:00.000")
        self.timeline_total_label.setMinimumWidth(190)
        export_format_layout.addWidget(QLabel("Resolution"))
        export_format_layout.addWidget(self.export_resolution_combo)
        export_format_layout.addWidget(QLabel("FPS"))
        export_format_layout.addWidget(self.export_fps_spin)
        export_format_layout.addStretch(1)
        export_quality_layout.addWidget(QLabel("Bitrate"))
        export_quality_layout.addWidget(self.export_bitrate_input)
        export_quality_layout.addStretch(1)
        export_quality_layout.addWidget(self.timeline_total_label)
        export_output_layout.addWidget(QLabel("Output"))
        export_output_layout.addWidget(self.export_output_input, 1)
        export_output_layout.addWidget(self.export_output_browse_button)
        export_layout.addLayout(export_format_layout)
        export_layout.addLayout(export_quality_layout)
        export_layout.addLayout(export_output_layout)
        timeline_layout.addWidget(export_row, 0)

        self.timeline_preview_panel = VideoPreviewPanel("Main Timeline Preview")
        self.timeline_preview_panel.setMinimumHeight(650)
        self.timeline_preview_panel.video_widget.setMinimumHeight(450)
        self.timeline_preview_panel.video_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        timeline_layout.addWidget(self.timeline_preview_panel, 0)
        timeline_layout.addSpacing(42)

        self.timeline_table = TimelineClipTable()
        self.timeline_table.setMinimumHeight(340)
        self.timeline_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.timeline_table.customContextMenuRequested.connect(self.show_timeline_context_menu)
        self.timeline_table.timelineChanged.connect(self._on_editor_timeline_changed)
        self.timeline_table.clipActivated.connect(self.preview_timeline_clip)
        timeline_layout.addWidget(self.timeline_table, 1)

        editor_split.addWidget(manual_panel)
        editor_split.addWidget(timeline_panel)
        editor_split.setSizes([560, 760])
        layout.addWidget(editor_split, 2)
        return page

    def _build_rough_cut_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        layout.addWidget(scroll_area, 1)

        content = QWidget()
        scroll_area.setWidget(content)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(14, 14, 14, 14)
        content_layout.setSpacing(10)

        settings = QGroupBox("Transformative Review Rough Cut")
        settings.setMinimumHeight(430)
        settings_layout = QHBoxLayout(settings)
        settings_layout.setContentsMargins(12, 22, 12, 14)
        settings_layout.setSpacing(12)

        self.rough_clip_seconds_spin = QSpinBox()
        self.rough_clip_seconds_spin.setRange(1, 5)
        self.rough_clip_seconds_spin.setValue(5)
        self.rough_clip_seconds_spin.setSuffix(" sec")

        self.rough_sample_every_spin = QSpinBox()
        self.rough_sample_every_spin.setRange(5, 600)
        self.rough_sample_every_spin.setValue(30)
        self.rough_sample_every_spin.setSuffix(" sec")

        self.rough_max_clips_spin = QSpinBox()
        self.rough_max_clips_spin.setRange(1, 300)
        self.rough_max_clips_spin.setValue(60)

        self.rough_scene_output_seconds_spin = QSpinBox()
        self.rough_scene_output_seconds_spin.setRange(5, 60)
        self.rough_scene_output_seconds_spin.setValue(12)
        self.rough_scene_output_seconds_spin.setSuffix(" sec")

        self.rough_target_final_minutes_spin = QDoubleSpinBox()
        self.rough_target_final_minutes_spin.setRange(0.0, 180.0)
        self.rough_target_final_minutes_spin.setDecimals(1)
        self.rough_target_final_minutes_spin.setSingleStep(0.5)
        self.rough_target_final_minutes_spin.setValue(12.0)
        self.rough_target_final_minutes_spin.setSuffix(" min")
        self.rough_target_final_minutes_spin.setReadOnly(True)
        self.rough_target_final_minutes_spin.setToolTip(
            "Calculated from Target % and the selected Video Ori range."
        )
        self.rough_target_percent_spin = QDoubleSpinBox()
        self.rough_target_percent_spin.setRange(0.0, 100.0)
        self.rough_target_percent_spin.setDecimals(1)
        self.rough_target_percent_spin.setSingleStep(0.5)
        self.rough_target_percent_spin.setValue(12.0)
        self.rough_target_percent_spin.setSuffix(" %")
        self.rough_target_percent_spin.setToolTip(
            "Final rough-cut length as a percentage of the selected Video Ori range."
        )
        self.rough_target_percent_spin.valueChanged.connect(self._sync_rough_target_from_percent)

        self.rough_slow_every_spin = QSpinBox()
        self.rough_slow_every_spin.setRange(0, 20)
        self.rough_slow_every_spin.setSpecialValueText("Off")
        self.rough_slow_every_spin.setValue(0)

        self.rough_slow_factor_spin = QDoubleSpinBox()
        self.rough_slow_factor_spin.setRange(1.0, 3.0)
        self.rough_slow_factor_spin.setSingleStep(0.1)
        self.rough_slow_factor_spin.setValue(1.2)
        self.rough_slow_factor_spin.setDecimals(1)

        self.rough_hook_seconds_spin = QSpinBox()
        self.rough_hook_seconds_spin.setRange(2, 5)
        self.rough_hook_seconds_spin.setValue(5)
        self.rough_hook_seconds_spin.setSuffix(" sec")

        self.rough_zoom_spin = QSpinBox()
        self.rough_zoom_spin.setRange(0, 20)
        self.rough_zoom_spin.setValue(4)
        self.rough_zoom_spin.setSuffix(" %")

        self.rough_mirror_every_spin = QSpinBox()
        self.rough_mirror_every_spin.setRange(0, 20)
        self.rough_mirror_every_spin.setSpecialValueText("Off")
        self.rough_mirror_every_spin.setValue(2)

        self.rough_transition_spin = QDoubleSpinBox()
        self.rough_transition_spin.setRange(0.0, 1.0)
        self.rough_transition_spin.setSingleStep(0.05)
        self.rough_transition_spin.setDecimals(2)
        self.rough_transition_spin.setValue(0.15)
        self.rough_transition_spin.setSuffix(" sec")

        self.rough_color_grade_combo = QComboBox()
        for code, label in ROUGH_CUT_COLOR_GRADES.items():
            self.rough_color_grade_combo.addItem(label, code)
        self.rough_color_grade_combo.setCurrentIndex(
            self.rough_color_grade_combo.findData("review_warm")
        )

        self.rough_video_hook_check = QCheckBox("Use short conflict video clip as hook")
        self.rough_video_hook_check.setChecked(True)
        self.rough_neighbor_fill_check = QCheckBox("Fill each scene with nearby clips")
        self.rough_neighbor_fill_check.setChecked(True)
        self.rough_keep_audio_check = QCheckBox("Keep Video Ori audio/dialogue")
        self.rough_keep_audio_check.setChecked(False)

        self.rough_music_path_input = QLineEdit()
        self.rough_music_path_input.setReadOnly(True)
        self.rough_music_path_input.setPlaceholderText("Optional royalty-free music file")
        self.rough_music_browse_button = QPushButton("Choose Music")
        self.rough_music_clear_button = QPushButton("Clear")
        self.rough_music_browse_button.clicked.connect(self.choose_rough_music_file)
        self.rough_music_clear_button.clicked.connect(self.clear_rough_music_file)
        music_row = QWidget()
        music_layout = QHBoxLayout(music_row)
        music_layout.setContentsMargins(0, 0, 0, 0)
        music_layout.addWidget(self.rough_music_path_input, 1)
        music_layout.addWidget(self.rough_music_browse_button)
        music_layout.addWidget(self.rough_music_clear_button)

        self.rough_music_volume_spin = QDoubleSpinBox()
        self.rough_music_volume_spin.setRange(0.0, 1.0)
        self.rough_music_volume_spin.setSingleStep(0.05)
        self.rough_music_volume_spin.setDecimals(2)
        self.rough_music_volume_spin.setValue(0.22)
        self.rough_music_volume_spin.setSuffix(" vol")

        self._polish_rough_cut_controls()

        range_group = QGroupBox("Video Ori Range")
        range_layout = QVBoxLayout(range_group)
        range_layout.setContentsMargins(14, 24, 14, 14)
        range_layout.setSpacing(10)
        self.rough_range_selector = RoughCutRangeSelector()
        self.rough_range_selector.rangeChanged.connect(self._rough_range_changed)
        self.rough_range_label = QLabel("Import Video Ori to choose the rough cut range.")
        self.rough_range_full_button = QPushButton("Use Full Video")
        self.rough_range_full_button.clicked.connect(self.use_full_rough_range)
        range_button_row = QHBoxLayout()
        range_button_row.addWidget(self.rough_range_label, 1)
        range_button_row.addWidget(self.rough_range_full_button)
        range_layout.addWidget(self.rough_range_selector)
        range_layout.addLayout(range_button_row)

        timing_group = QGroupBox("Timing")
        timing_group.setMinimumHeight(382)
        timing_layout = QFormLayout(timing_group)
        timing_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        timing_layout.setHorizontalSpacing(14)
        timing_layout.setVerticalSpacing(12)
        timing_layout.setContentsMargins(14, 24, 14, 14)
        timing_layout.addRow("Clip length", self.rough_clip_seconds_spin)
        timing_layout.addRow("Sample every", self.rough_sample_every_spin)
        timing_layout.addRow("Hook clip", self.rough_hook_seconds_spin)
        timing_layout.addRow("Scene duration", self.rough_scene_output_seconds_spin)
        timing_layout.addRow("Target %", self.rough_target_percent_spin)
        timing_layout.addRow("Target duration", self.rough_target_final_minutes_spin)
        timing_layout.addRow("Max clips", self.rough_max_clips_spin)
        timing_layout.addRow("Slowmo every", self.rough_slow_every_spin)
        timing_layout.addRow("Slowmo factor", self.rough_slow_factor_spin)

        visual_group = QGroupBox("Visual Style")
        visual_group.setMinimumHeight(382)
        visual_layout = QFormLayout(visual_group)
        visual_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        visual_layout.setHorizontalSpacing(14)
        visual_layout.setVerticalSpacing(12)
        visual_layout.setContentsMargins(14, 24, 14, 14)
        visual_layout.addRow("Subtle zoom", self.rough_zoom_spin)
        visual_layout.addRow("Mirror every", self.rough_mirror_every_spin)
        visual_layout.addRow("Fade", self.rough_transition_spin)
        visual_layout.addRow("Color grade", self.rough_color_grade_combo)
        visual_layout.addRow("", self.rough_video_hook_check)
        visual_layout.addRow("", self.rough_neighbor_fill_check)

        audio_group = QGroupBox("Audio")
        audio_group.setMinimumHeight(382)
        audio_layout = QFormLayout(audio_group)
        audio_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        audio_layout.setHorizontalSpacing(14)
        audio_layout.setVerticalSpacing(12)
        audio_layout.setContentsMargins(14, 24, 14, 14)
        audio_layout.addRow("", self.rough_keep_audio_check)
        audio_layout.addRow("Royalty-free music", music_row)
        audio_layout.addRow("Music volume", self.rough_music_volume_spin)

        settings_layout.addWidget(timing_group, 1)
        settings_layout.addWidget(visual_group, 1)
        settings_layout.addWidget(audio_group, 2)
        settings.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.rough_hook_edit = QTextEdit()
        self.rough_hook_edit.setMinimumHeight(140)
        self.rough_hook_edit.setPlaceholderText(
            "Short hook notes for an original recap/review opening. The export uses a short conflict clip when enabled."
        )

        button_row = QHBoxLayout()
        self.suggest_hook_button = QPushButton("Suggest Conflict Hook")
        self.build_rough_timeline_button = QPushButton("Build Timeline")
        self.export_rough_cut_button = QPushButton("Export Rough Cut Video")
        self.suggest_hook_button.clicked.connect(self.suggest_conflict_hook)
        self.build_rough_timeline_button.clicked.connect(self.build_rough_cut_timeline)
        self.export_rough_cut_button.clicked.connect(self.export_rough_cut_video)
        button_row.addStretch(1)
        button_row.addWidget(self.suggest_hook_button)
        button_row.addWidget(self.build_rough_timeline_button)
        button_row.addWidget(self.export_rough_cut_button)

        parts_group = QGroupBox("Rough Cut Parts")
        parts_layout = QVBoxLayout(parts_group)
        parts_layout.setContentsMargins(12, 22, 12, 12)
        parts_layout.setSpacing(10)
        parts_button_row = QHBoxLayout()
        self.remove_rough_part_button = QPushButton("Remove Selected Part")
        self.combine_rough_parts_button = QPushButton("Combine Parts")
        self.combine_rough_parts_button.setObjectName("PrimaryButton")
        self.remove_rough_part_button.clicked.connect(self.remove_selected_rough_part)
        self.combine_rough_parts_button.clicked.connect(self.combine_rough_cut_part_videos)
        parts_button_row.addStretch(1)
        parts_button_row.addWidget(self.remove_rough_part_button)
        parts_button_row.addWidget(self.combine_rough_parts_button)

        self.rough_parts_table = QTableWidget()
        self.rough_parts_table.setColumnCount(3)
        self.rough_parts_table.setHorizontalHeaderLabels(["Range", "File", "Status"])
        self.rough_parts_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.rough_parts_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.rough_parts_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rough_parts_table.verticalHeader().setVisible(False)
        self.rough_parts_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.rough_parts_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.rough_parts_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.rough_parts_table.setMinimumHeight(170)
        parts_layout.addLayout(parts_button_row)
        parts_layout.addWidget(self.rough_parts_table)

        content_layout.addWidget(range_group, 0)
        content_layout.addWidget(settings, 0)
        content_layout.addWidget(QLabel("Conflict hook notes"))
        content_layout.addWidget(self.rough_hook_edit, 0)
        content_layout.addLayout(button_row)
        content_layout.addWidget(parts_group, 0)
        content_layout.addStretch(1)
        return page

    def _polish_rough_cut_controls(self) -> None:
        controls = [
            self.rough_clip_seconds_spin,
            self.rough_sample_every_spin,
            self.rough_max_clips_spin,
            self.rough_scene_output_seconds_spin,
            self.rough_target_final_minutes_spin,
            self.rough_target_percent_spin,
            self.rough_slow_every_spin,
            self.rough_slow_factor_spin,
            self.rough_hook_seconds_spin,
            self.rough_zoom_spin,
            self.rough_mirror_every_spin,
            self.rough_transition_spin,
            self.rough_color_grade_combo,
            self.rough_music_path_input,
            self.rough_music_volume_spin,
        ]
        for control in controls:
            control.setMinimumHeight(32)
            control.setMinimumWidth(120)

        for button in [self.rough_music_browse_button, self.rough_music_clear_button]:
            button.setMinimumHeight(32)

        field_style = """
            QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit {
                min-height: 30px;
                padding: 4px 8px;
            }
            QSpinBox::up-button, QSpinBox::down-button,
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                width: 20px;
            }
        """
        for control in controls:
            control.setStyleSheet(field_style)

    def _build_indonesian_subtitle_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(scroll_area, 1)

        content = QWidget()
        scroll_area.setWidget(content)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(14, 14, 14, 24)
        content_layout.setSpacing(12)

        settings = QGroupBox("Generate Subtitle Indonesia from Video Audio")
        settings.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        settings_layout = QFormLayout(settings)
        settings_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        settings_layout.setHorizontalSpacing(14)
        settings_layout.setVerticalSpacing(10)
        settings_layout.setContentsMargins(14, 24, 14, 14)

        self.subtitle_source_combo = QComboBox()
        self.subtitle_source_combo.addItem("Foreign audio -> translate to Indonesian", "foreign")
        self.subtitle_source_combo.addItem("Audio already Bahasa Indonesia", "id")

        self.subtitle_language_combo = QComboBox()
        self.subtitle_language_combo.addItem("Auto detect", "")
        self.subtitle_language_combo.addItem("Japanese", "ja")
        self.subtitle_language_combo.addItem("English", "en")
        self.subtitle_language_combo.addItem("Hindi / India", "hi")
        self.subtitle_language_combo.addItem("Tamil / India", "ta")
        self.subtitle_language_combo.addItem("Telugu / India", "te")
        self.subtitle_language_combo.addItem("Malayalam / India", "ml")
        self.subtitle_language_combo.addItem("Kannada / India", "kn")
        self.subtitle_language_combo.addItem("Bengali / India", "bn")
        self.subtitle_language_combo.addItem("Marathi / India", "mr")
        self.subtitle_language_combo.addItem("Urdu / India", "ur")
        self.subtitle_language_combo.addItem("Korean", "ko")
        self.subtitle_language_combo.addItem("Chinese", "zh")
        self.subtitle_language_combo.addItem("Bahasa Indonesia", "id")

        self.subtitle_output_input = QLineEdit()
        self.subtitle_output_input.setReadOnly(True)
        self.subtitle_output_input.setPlaceholderText("Auto: project/subtitles/indonesian_audio_subtitles.srt")
        self.subtitle_output_button = QPushButton("Choose Output")
        self.subtitle_output_button.clicked.connect(self.choose_subtitle_output_file)
        output_row = QWidget()
        output_layout = QHBoxLayout(output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.addWidget(self.subtitle_output_input, 1)
        output_layout.addWidget(self.subtitle_output_button)

        self.generate_id_subtitle_button = QPushButton("Generate Indonesian SRT")
        self.generate_id_subtitle_button.clicked.connect(self.generate_indonesian_subtitles)

        self.subtitle_status_view = QTextEdit()
        self.subtitle_status_view.setReadOnly(True)
        self.subtitle_status_view.setMinimumHeight(260)
        self.subtitle_status_view.setPlaceholderText(
            "Subtitle status and output path will appear here."
        )

        for control in [
            self.model_combo,
            self.device_combo,
            self.compute_combo,
            self.subtitle_source_combo,
            self.subtitle_language_combo,
            self.subtitle_output_input,
        ]:
            control.setMinimumHeight(32)

        settings_layout.addRow("Audio mode", self.subtitle_source_combo)
        settings_layout.addRow("Source language", self.subtitle_language_combo)
        settings_layout.addRow("Whisper model", self.model_combo)
        settings_layout.addRow("Device", self.device_combo)
        settings_layout.addRow("Compute type", self.compute_combo)
        settings_layout.addRow("SRT output", output_row)
        settings_layout.addRow("", self.generate_id_subtitle_button)

        content_layout.addWidget(settings, 0)
        content_layout.addWidget(QLabel("Status"))
        content_layout.addWidget(self.subtitle_status_view, 0)
        bottom_safe_space = QWidget()
        bottom_safe_space.setFixedHeight(96)
        content_layout.addWidget(bottom_safe_space, 0)
        return page

    def _build_script_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        row = QHBoxLayout()
        self.generate_script_button = QPushButton("Generate Draft Script")
        self.save_script_button = QPushButton("Save Script TXT")
        self.generate_script_button.clicked.connect(self.generate_script)
        self.save_script_button.clicked.connect(self.save_script_text)
        self.script_style_combo = QComboBox()
        for code, label in SUPPORTED_SCRIPT_STYLES.items():
            self.script_style_combo.addItem(label, code)
        self.script_style_combo.setCurrentIndex(self.script_style_combo.findData("recap"))

        self.script_language_combo = QComboBox()
        for code, label in SUPPORTED_SCRIPT_LANGUAGES.items():
            self.script_language_combo.addItem(label, code)
        self.script_language_combo.setCurrentIndex(self.script_language_combo.findData("id"))

        row.addWidget(QLabel("Local script generator"))
        row.addStretch(1)
        row.addWidget(QLabel("Script type"))
        row.addWidget(self.script_style_combo)
        row.addWidget(QLabel("Script language"))
        row.addWidget(self.script_language_combo)
        row.addWidget(self.generate_script_button)
        row.addWidget(self.save_script_button)
        layout.addLayout(row)

        self.script_edit = QTextEdit()
        self.script_edit.setPlaceholderText("Generated narration script draft will appear here.")
        layout.addWidget(self.script_edit, 1)
        return page

    def _build_checklist_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.checklist_widget = ChecklistWidget()
        layout.addWidget(self.checklist_widget)
        return page

    def _build_logs_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.log_panel = LogPanel()
        layout.addWidget(self.log_panel, 1)
        return page

    def new_project(self) -> None:
        name, ok = QInputDialog.getText(self, "New Project", "Project name:")
        if not ok:
            return
        if not name.strip():
            self._show_warning("Project name cannot be empty.")
            return

        default_path = self.project_manager.projects_root / f"{self._safe_project_filename(name)}{PROJECT_EXTENSION}"
        project_file, _ = QFileDialog.getSaveFileName(
            self,
            "Save New StoryCut Project",
            str(default_path),
            f"StoryCut Project (*{PROJECT_EXTENSION});;JSON Files (*.json);;All Files (*)",
        )
        if not project_file:
            return

        try:
            data = self.project_manager.create_project_at(name, project_file)
            self._load_project_data(data)
            self._log(f"Created project: {data.name} at {data.project_file}")
        except Exception as exc:
            self._show_error(str(exc))

    def _safe_project_filename(self, name: str) -> str:
        return safe_project_filename(name)

    def load_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load StoryCut Project",
            str(self.project_manager.projects_root),
            f"StoryCut Project (*{PROJECT_EXTENSION});;JSON Files (*.json)",
        )
        if not path:
            return

        try:
            data = self.project_manager.load_project(path)
            self._load_project_data(data)
            self._log(f"Loaded project: {data.name}")
        except Exception as exc:
            self._show_error(str(exc))

    def refresh_project(self) -> None:
        if not self._require_project():
            return
        if self._busy_count > 0:
            self._show_warning("Wait for the current task to finish before refreshing the project.")
            return

        assert self.project is not None
        project_file = Path(self.project.project_file)
        if not project_file.exists():
            self._show_warning(f"Project file was not found:\n{project_file}")
            return

        try:
            current_tab = self.tabs.currentIndex()
            data = self.project_manager.load_project(project_file)
            self._load_project_data(data)
            self.tabs.setCurrentIndex(min(current_tab, self.tabs.count() - 1))
            self._log(f"Refreshed project from disk: {project_file}")
            self.statusBar().showMessage("Project refreshed", 4000)
        except Exception as exc:
            self._show_error(str(exc))

    def save_project(self, show_message: bool = False) -> None:
        if not self.project:
            self._show_warning("Create or load a project first.")
            return

        try:
            self._sync_project_from_ui()
            saved_path = self.project_manager.save_project(self.project)
            if show_message:
                self._log(f"Saved project: {saved_path}")
                self.statusBar().showMessage("Project saved", 4000)
        except Exception as exc:
            self._show_error(str(exc))

    def import_video(self) -> None:
        if not self._require_project():
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Video Ori",
            str(Path.home()),
            "Video Files (*.mp4 *.mov *.mkv *.avi *.webm *.m4v);;All Files (*)",
        )
        if not path:
            return

        assert self.project is not None
        self.project.video_path = path
        self.project.metadata = None
        self.project.manual_clips = []
        self.project.timeline_clips = []
        self.project.cut_list = []
        self.cut_table.set_cut_items([])
        self.timeline_table.set_timeline_clips([])
        self.timeline_preview_panel.set_video("", 0.0)
        self._reset_editor_history()
        self.metadata_view.setText(metadata_to_text(None))
        self._refresh_visual_editor_video(0.0)
        self._refresh_rough_range_selector(0.0)
        self._log(f"Imported Video Ori: {path}")
        self.save_project()
        self.read_metadata()

    def read_metadata(self) -> None:
        if not self._require_video():
            return

        assert self.project is not None
        video_path = self.project.video_path

        def task(progress: Callable[[str], None]) -> VideoMetadata:
            progress("Reading video metadata with ffprobe...")
            return read_video_metadata(video_path)

        def done(metadata: VideoMetadata) -> None:
            assert self.project is not None
            self.project.set_metadata(metadata)
            self.metadata_view.setText(metadata_to_text(metadata))
            self._refresh_visual_editor_video(metadata.duration)
            self._refresh_rough_range_selector(metadata.duration)
            self._log("Metadata loaded.")
            if not metadata.has_audio:
                self._show_warning("No audio stream was detected in this video.")
            self.save_project()

        self._start_task("Reading metadata", task, done)

    def extract_scene_frames_for_notes(self) -> None:
        if not self._require_video():
            return

        assert self.project is not None
        video_path = self.project.video_path
        output_dir = Path(self.project.project_dir) / "scene_frames"
        interval = self.scene_interval_spin.value()
        max_frames = self.scene_max_frames_spin.value()

        existing_notes = self.scene_table.to_scene_notes()
        existing_by_time = {
            round(float(note.get("timestamp", 0.0) or 0.0), 1): str(note.get("note") or "")
            for note in existing_notes
            if str(note.get("note") or "").strip()
        }

        def task(progress: Callable[[str], None]) -> list[dict[str, Any]]:
            frames = extract_scene_frames(
                video_path,
                output_dir,
                interval_seconds=interval,
                max_frames=max_frames,
                progress_callback=progress,
            )
            return [frame.to_dict() for frame in frames]

        def done(frames: list[dict[str, Any]]) -> None:
            notes: list[dict[str, Any]] = []
            for frame in frames:
                timestamp = round(float(frame.get("timestamp", 0.0) or 0.0), 1)
                item = dict(frame)
                item["note"] = existing_by_time.get(timestamp, "")
                notes.append(item)

            assert self.project is not None
            self.scene_table.set_scene_notes(notes)
            self.project.scene_notes = self.scene_table.to_scene_notes()
            self._log(f"Extracted {len(notes)} visual scene frame(s).")
            self.tabs.setCurrentWidget(self.scene_table.parentWidget())
            self.save_project()

        self._start_task("Extracting scene frames", task, done)

    def auto_describe_scene_notes(self) -> None:
        if not self._require_project():
            return

        notes = self.scene_table.to_scene_notes()
        if not notes:
            self._show_warning("Extract scene frames first, then run Auto Describe Empty Notes.")
            return

        empty_notes = [note for note in notes if not str(note.get("note") or "").strip()]
        if not empty_notes:
            self._show_warning(
                "All scene notes already contain text. Clear a note first if you want it regenerated."
            )
            return

        def task(progress: Callable[[str], None]) -> list[dict[str, Any]]:
            return auto_caption_scene_notes(notes, progress_callback=progress)

        def done(updated_notes: list[dict[str, Any]]) -> None:
            assert self.project is not None
            self.scene_table.set_scene_notes(updated_notes)
            self.project.scene_notes = self.scene_table.to_scene_notes()
            self._log("Auto visual scene notes generated.")
            self.tabs.setCurrentWidget(self.scene_table.parentWidget())
            self.save_project()

        self._start_task("Auto describing scene frames", task, done)

    def extract_audio(self) -> None:
        if not self._require_video():
            return

        assert self.project is not None
        audio_path = Path(self.project.project_dir) / "audio" / "transcription_audio.wav"
        video_path = self.project.video_path

        def task(progress: Callable[[str], None]) -> str:
            output = extract_audio(video_path, audio_path, progress_callback=progress)
            return str(output)

        def done(output_path: str) -> None:
            assert self.project is not None
            self.project.audio_path = output_path
            self._log(f"Audio ready: {output_path}")
            self.save_project()

        self._start_task("Extracting audio", task, done)

    def transcribe_audio(self) -> None:
        if not self._require_project():
            return

        assert self.project is not None
        if not self.project.audio_path:
            self._show_warning("Extract audio before transcription.")
            return

        audio_path = self.project.audio_path
        model_size = self.model_combo.currentText()
        device = self.device_combo.currentText()
        compute_type = self.compute_combo.currentText()
        language = self.language_input.text().strip() or None
        database_path = self.project.database_path

        def task(progress: Callable[[str], None]) -> list[Any]:
            transcriber = WhisperTranscriber(
                model_size=model_size,
                device=device,
                compute_type=compute_type,
            )
            segments = transcriber.transcribe(
                audio_path,
                language=language,
                progress_callback=progress,
            )
            db = TranscriptDatabase(database_path)
            db.replace_segments(segments)
            return db.fetch_segments()

        def done(records: list[Any]) -> None:
            self.transcript_table.set_segments(records)
            self.tabs.setCurrentWidget(self.transcript_table.parentWidget())
            self._log(f"Saved transcript: {len(records)} segments.")
            self.save_project()

        self._start_task("Transcribing audio", task, done)

    def voice_to_indonesian_script(self) -> None:
        if not self._require_video() or not self._require_database():
            return

        assert self.project is not None
        video_path = self.project.video_path
        audio_path = Path(self.project.project_dir) / "audio" / "transcription_audio.wav"
        database_path = self.project.database_path
        model_size = self.model_combo.currentText()
        device = self.device_combo.currentText()
        compute_type = self.compute_combo.currentText()

        def task(progress: Callable[[str], None]) -> list[Any]:
            if not audio_path.exists():
                extract_audio(video_path, audio_path, progress_callback=progress)

            progress("Translating foreign voice to English with local Whisper...")
            transcriber = WhisperTranscriber(
                model_size=model_size,
                device=device,
                compute_type=compute_type,
            )
            english_segments = transcriber.transcribe(
                audio_path,
                language=None,
                task="translate",
                progress_callback=progress,
            )

            progress("Translating English transcript to Indonesian locally...")
            translator = LocalIndonesianTranslator()
            indonesian_segments = translator.translate_segments(
                english_segments,
                progress_callback=progress,
            )

            db = TranscriptDatabase(database_path)
            db.replace_segments(indonesian_segments)
            return db.fetch_segments()

        def done(records: list[Any]) -> None:
            assert self.project is not None
            self.project.audio_path = str(audio_path)
            self.transcript_table.set_segments(records)
            self._log(f"Saved translated Indonesian voice transcript: {len(records)} segments.")
            self._generate_script_from_current_transcript()
            self.statusBar().showMessage("Voice translated to Indonesian script", 4000)

        self._start_task("Voice to Indonesian script", task, done)

    def search_transcript(self) -> None:
        if not self._require_database():
            return

        assert self.database is not None
        query = self.search_input.text()
        records = self.database.search(query)
        self.transcript_table.set_segments(records)
        self.statusBar().showMessage(f"{len(records)} transcript rows shown", 4000)

    def show_all_transcript(self) -> None:
        self.search_input.clear()
        if not self._require_database():
            return
        assert self.database is not None
        records = self.database.fetch_segments()
        self.transcript_table.set_segments(records)
        self.statusBar().showMessage(f"{len(records)} transcript rows shown", 4000)

    def import_text_transcript(self) -> None:
        if not self._require_database():
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import TXT Transcript",
            str(Path.home()),
            "Text Files (*.txt);;All Files (*)",
        )
        if not path:
            return

        try:
            assert self.database is not None
            text = read_text_file(path)
            segments = text_to_transcript_segments(text)
            if not segments:
                self._show_warning("The selected text file did not contain transcript text.")
                return
            self.database.replace_segments(segments)
            records = self.database.fetch_segments()
            self.transcript_table.set_segments(records)
            self._log(f"Imported TXT transcript: {path}")
            self._log(f"Saved imported transcript: {len(records)} segments.")
            self._generate_script_from_current_transcript()
            self.statusBar().showMessage(f"Imported {len(records)} transcript rows", 4000)
        except Exception as exc:
            self._show_error(str(exc))

    def import_subtitle_file(self) -> None:
        if not self._require_database():
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Subtitle File",
            str(Path.home()),
            "Subtitle/Text Files (*.srt *.vtt *.ass *.ssa *.txt);;All Files (*)",
        )
        if not path:
            return

        try:
            assert self.database is not None
            segments = subtitle_file_to_segments(path)
            if not segments:
                self._show_warning("The selected subtitle file did not contain readable text.")
                return
            self.database.replace_segments(segments)
            records = self.database.fetch_segments()
            self.transcript_table.set_segments(records)
            self._log(f"Imported subtitle file: {path}")
            self._log(f"Saved subtitle transcript: {len(records)} segments.")
            self._generate_script_from_current_transcript()
            self.statusBar().showMessage(f"Imported {len(records)} subtitle rows", 4000)
        except Exception as exc:
            self._show_error(str(exc))

    def extract_indonesian_subtitles(self) -> None:
        if not self._require_video() or not self._require_database():
            return

        assert self.project is not None
        video_path = self.project.video_path
        output_dir = Path(self.project.project_dir) / "subtitles"

        def task(progress: Callable[[str], None]) -> dict[str, Any]:
            segments, subtitle_path, stream = extract_best_subtitle_segments(
                video_path,
                output_dir,
                progress_callback=progress,
            )
            return {"segments": segments, "subtitle_path": str(subtitle_path), "stream": stream.label}

        def done(result: dict[str, Any]) -> None:
            assert self.database is not None
            segments = result["segments"]
            self.database.replace_segments(segments)
            records = self.database.fetch_segments()
            self.transcript_table.set_segments(records)
            self._log(f"Extracted subtitle stream: {result['stream']}")
            self._log(f"Saved extracted subtitle file: {result['subtitle_path']}")
            self._log(f"Saved subtitle transcript: {len(records)} segments.")
            self._generate_script_from_current_transcript()
            self.statusBar().showMessage(f"Extracted {len(records)} subtitle rows", 4000)

        self._start_task("Extracting Indonesian subtitles", task, done)

    def ocr_burned_subtitles(self) -> None:
        if not self._require_video() or not self._require_database():
            return

        QMessageBox.information(
            self,
            "OCR Burned Subtitles",
            "This will scan the bottom area of the video for burned-in subtitles. "
            "It can take a while and works best with clear, large Indonesian subtitles.",
        )

        assert self.project is not None
        video_path = self.project.video_path
        output_dir = Path(self.project.project_dir) / "subtitles"

        def task(progress: Callable[[str], None]) -> list[Any]:
            return ocr_burned_subtitles(video_path, output_dir, progress_callback=progress)

        def done(segments: list[Any]) -> None:
            assert self.database is not None
            self.database.replace_segments(segments)
            records = self.database.fetch_segments()
            self.transcript_table.set_segments(records)
            self._log(f"OCR burned subtitles complete: {len(records)} segments.")
            self._generate_script_from_current_transcript()
            self.statusBar().showMessage(f"OCR imported {len(records)} subtitle rows", 4000)

        self._start_task("OCR burned subtitles", task, done)

    def add_selected_to_cut_list(self) -> None:
        if not self._require_project():
            return

        selected = self.transcript_table.selected_segments()
        if not selected:
            self._show_warning("Select one or more transcript rows first.")
            return

        existing = self.cut_table.to_cut_items()
        new_items: list[dict[str, Any]] = []
        for segment in selected:
            new_items.append(
                self._with_clip_thumbnail(
                {
                    "id": f"clip_{len(existing) + len(new_items) + 1:03d}_{uuid.uuid4().hex[:6]}",
                    "source_segment_id": segment.get("id"),
                    "start": format_duration(float(segment.get("start", 0.0))),
                    "end": format_duration(float(segment.get("end", 0.0))),
                    "text": segment.get("text", ""),
                    "kind": "manual",
                }
                )
            )

        self.cut_table.set_cut_items(existing + new_items)
        self._log(f"Added {len(new_items)} segment(s) to Manual Clips.")
        self._push_editor_history()
        self.save_project()

    def add_visual_cut_to_list(self, start: float, end: float, text: str) -> None:
        if not self._require_video():
            return
        if end <= start:
            self._show_warning("End time must be after start time.")
            return

        existing = self.cut_table.to_cut_items()
        item = {
            "id": f"clip_{len(existing) + 1:03d}_{uuid.uuid4().hex[:6]}",
            "start": format_duration(start),
            "end": format_duration(end),
            "text": text,
            "kind": "manual",
        }
        item = self._with_clip_thumbnail(item)
        self.cut_table.set_cut_items(existing + [item])
        self.cut_table.selectRow(self.cut_table.rowCount() - 1)
        self._log(f"Saved Manual Clip: {item['start']} to {item['end']}.")
        self._push_editor_history()
        self.save_project()

    def add_visual_photo_to_list(self, timestamp: float) -> None:
        if not self._require_video():
            return

        assert self.project is not None
        timestamp = max(0.0, float(timestamp or 0.0))
        existing = self.cut_table.to_cut_items()
        photo_id = f"photo_{len(existing) + 1:03d}_{uuid.uuid4().hex[:6]}"
        photo_dir = Path(self.project.project_dir) / "photos"
        photo_path = photo_dir / f"{self._safe_project_filename(photo_id)}.jpg"
        try:
            extract_video_frame(self.project.video_path, photo_path, timestamp)
        except Exception as exc:
            self._show_error(f"Could not save photo frame: {exc}")
            return

        item = {
            "id": photo_id,
            "start": format_duration(timestamp),
            "end": format_duration(timestamp + 0.1),
            "timestamp": round(timestamp, 3),
            "output_duration": 3.0,
            "text": f"Photo frame {format_duration(timestamp)}",
            "kind": "photo",
            "media_type": "photo",
            "image_path": str(photo_path),
            "thumbnail_path": str(photo_path),
        }
        self.cut_table.set_cut_items(existing + [item])
        self.cut_table.selectRow(self.cut_table.rowCount() - 1)
        self._log(f"Saved Photo to Manual Clips: {format_duration(timestamp)}.")
        self._push_editor_history()
        self.save_project()

    def apply_visual_range_to_selected_cut(self, start: float, end: float) -> None:
        if not self._require_project():
            return
        if end <= start:
            self._show_warning("End time must be after start time.")
            return

        selected_row = self.cut_table.currentRow()
        updated = self.cut_table.update_first_selected_range(start, end)
        if not updated:
            self._show_warning("Select one Manual Clips row first.")
            return

        items = self.cut_table.to_cut_items()
        if 0 <= selected_row < len(items):
            items[selected_row] = self._with_clip_thumbnail(items[selected_row])
            self.cut_table.set_cut_items(items)
            self.cut_table.selectRow(selected_row)
        self._log(f"Updated {updated.get('id', 'clip')} range: {updated['start']} to {updated['end']}.")
        self._push_editor_history()
        self.save_project()

    def preview_selected_cut_range(self) -> None:
        if not getattr(self, "visual_cut_editor", None):
            return

        selected = self.cut_table.selected_cut_items()
        if not selected:
            return

        try:
            clip = ClipItem.from_dict(selected[0])
        except (TypeError, ValueError):
            return

        self.visual_cut_editor.set_clip_range(clip.start, clip.end, seek=True)

    def remove_selected_cuts(self) -> None:
        removed = self.cut_table.remove_selected_rows()
        if not removed:
            self._show_warning("Select one or more Manual Clips rows first.")
            return
        self._log(f"Removed {removed} Manual Clips row(s).")
        self._push_editor_history()
        self.save_project()

    def export_selected_clips(self) -> None:
        if not self._require_video():
            return

        selected = self.cut_table.selected_cut_items()
        if not selected:
            self._show_warning("Select one or more Manual Clips rows to export.")
            return

        assert self.project is not None
        default_dir = Path(self.project.project_dir) / "clips"
        output_dir = QFileDialog.getExistingDirectory(
            self,
            "Choose Clip Export Folder",
            str(default_dir),
        )
        if not output_dir:
            return

        video_path = self.project.video_path

        def task(progress: Callable[[str], None]) -> list[str]:
            clips = [ClipItem.from_dict(item) for item in selected]
            outputs = export_clips(video_path, output_dir, clips, progress_callback=progress)
            return [str(path) for path in outputs]

        def done(outputs: list[str]) -> None:
            for output in outputs:
                self._log(f"Exported clip: {output}")
            self.save_project()
            QMessageBox.information(self, "Export Complete", f"Exported {len(outputs)} clip(s).")

        self._start_task("Exporting clips", task, done)

    def choose_export_output_file(self) -> None:
        if not self._require_project():
            return
        assert self.project is not None
        default_dir = Path(self.project.project_dir) / "exports"
        default_dir.mkdir(exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Video",
            str(default_dir / f"{self._safe_project_filename(self.project.name)}_final.mp4"),
            "MP4 Video (*.mp4);;All Files (*)",
        )
        if path:
            self.export_output_input.setText(str(Path(path).with_suffix(".mp4")))
            self.save_project()

    def add_selected_manual_clips_to_timeline(self) -> None:
        if not self._require_project():
            return
        selected = self.cut_table.selected_cut_items()
        if not selected:
            self._show_warning("Select one or more Manual Clips first.")
            return
        insert_at = self.timeline_table.insertion_row_after_selection()
        self.timeline_table.append_clips(selected, insert_at=insert_at)
        self._log(f"Added {len(selected)} Manual Clip(s) at Main Timeline row {insert_at + 1}.")
        self.save_project()

    def add_all_manual_clips_to_timeline(self) -> None:
        if not self._require_project():
            return
        clips = self.cut_table.to_cut_items()
        if not clips:
            self._show_warning("No Manual Clips are available yet.")
            return
        insert_at = self.timeline_table.insertion_row_after_selection()
        self.timeline_table.append_clips(clips, insert_at=insert_at)
        self._log(f"Added all {len(clips)} Manual Clip(s) at Main Timeline row {insert_at + 1}.")
        self.save_project()

    def add_manual_clip_from_double_click(self, item: QTableWidgetItem) -> None:
        if item.column() == 3:
            return
        self.cut_table.selectRow(item.row())
        self.add_selected_manual_clips_to_timeline()

    def preview_timeline_clip(self, clip: dict[str, Any]) -> None:
        if not self.project or not self.project.video_path:
            return
        try:
            item = ClipItem.from_dict(clip)
        except (TypeError, ValueError):
            return
        self.visual_cut_editor.set_clip_range(item.start, item.end, seek=True)
        self.tabs.setCurrentWidget(self.cuts_tab)
        self.statusBar().showMessage("Timeline clip loaded in Video Ori preview", 3000)

    def preview_selected_timeline_clip(self) -> None:
        clip = self.timeline_table.selected_timeline_clip()
        if not clip:
            self._show_warning("Select one timeline clip first.")
            return
        self.preview_timeline_clip_in_main_preview(clip)

    def preview_timeline_clip_in_main_preview(self, clip: dict[str, Any]) -> None:
        if not self._require_video():
            return

        timeline = self._timeline_with_output_durations([clip])
        if not timeline:
            self._show_warning("Selected timeline clip cannot be previewed.")
            return

        assert self.project is not None
        preview_clips: list[dict[str, float]] = []
        for timeline_clip in timeline:
            try:
                item = ClipItem.from_dict(timeline_clip)
            except (TypeError, ValueError):
                continue
            output_duration = self._clip_output_duration(timeline_clip)
            if output_duration <= 0:
                output_duration = max(0.1, item.end - item.start)
            preview_clips.append(
                {
                    "start": item.start,
                    "end": item.end,
                    "output_duration": output_duration,
                }
            )
        if not preview_clips:
            self._show_warning("Selected timeline clip has no valid preview range.")
            return

        source_duration = 0.0
        if self.project.metadata:
            source_duration = VideoMetadata.from_dict(self.project.metadata).duration

        self.timeline_preview_panel.set_timeline_sequence(
            self.project.video_path,
            preview_clips,
            source_duration_seconds=source_duration,
            autoplay=True,
        )
        total_duration = self._timeline_total_duration(timeline)
        clip_id = str(timeline[0].get("id") or "selected clip")
        self._log(
            f"Previewing selected Main Timeline clip without saving a preview file: "
            f"{clip_id}, {format_duration(total_duration)}."
        )
        self.statusBar().showMessage("Selected Main Timeline clip preview playing", 4000)

    def preview_full_timeline_video(self) -> None:
        if not self._require_video():
            return

        timeline = self._timeline_with_output_durations(self.timeline_table.timeline_clips())
        if not timeline:
            self._show_warning("Timeline is empty. Build a rough cut or drag Manual Clips into it first.")
            return
        self.timeline_table.set_timeline_clips(timeline)
        self._refresh_timeline_total_label()
        total_duration = self._timeline_total_duration(timeline)
        total_clips = len(timeline)

        assert self.project is not None
        preview_clips: list[dict[str, float]] = []
        for clip in timeline:
            try:
                item = ClipItem.from_dict(clip)
            except (TypeError, ValueError):
                continue
            output_duration = self._clip_output_duration(clip)
            if output_duration <= 0:
                output_duration = max(0.1, item.end - item.start)
            preview_clips.append(
                {
                    "start": item.start,
                    "end": item.end,
                    "output_duration": output_duration,
                }
            )
        if not preview_clips:
            self._show_warning("Timeline preview could not find any valid clip ranges.")
            return

        source_duration = 0.0
        if self.project.metadata:
            source_duration = VideoMetadata.from_dict(self.project.metadata).duration

        self.timeline_preview_panel.set_timeline_sequence(
            self.project.video_path,
            preview_clips,
            source_duration_seconds=source_duration,
            autoplay=True,
        )
        self._log(
            f"Previewing full Main Timeline without saving a preview file: "
            f"{total_clips} clip(s), {format_duration(total_duration)}."
        )
        self.statusBar().showMessage("Main Timeline preview playing without local preview file", 4000)

    def trim_selected_timeline_to_video_ori_selection(self) -> None:
        if not self._require_project():
            return
        start, end = self.visual_cut_editor._range_seconds()
        if end <= start:
            self._show_warning("Mark a valid range in Video Ori first.")
            return
        updated = self.timeline_table.update_selected_range(start, end)
        if not updated:
            self._show_warning("Select one timeline clip first.")
            return
        self._log(f"Trimmed timeline clip to {updated['start']} - {updated['end']}.")
        self.save_project()

    def split_selected_timeline_clip(self) -> None:
        if not self.timeline_table.split_selected_clip():
            self._show_warning("Select a timeline clip longer than 0.2 seconds first.")
            return
        self._log("Split selected timeline clip.")
        self.save_project()

    def delete_selected_timeline_clips(self) -> None:
        removed = self.timeline_table.remove_selected_rows()
        if not removed:
            self._show_warning("Select one or more timeline clips first.")
            return
        self._log(f"Deleted {removed} timeline clip(s).")
        self.save_project()

    def show_timeline_context_menu(self, position: Any) -> None:
        index = self.timeline_table.indexAt(position)
        selected_rows = {row.row() for row in self.timeline_table.selectionModel().selectedRows()}
        if index.isValid() and index.row() not in selected_rows:
            self.timeline_table.selectRow(index.row())
            selected_rows = {index.row()}
        if not selected_rows:
            return

        menu = QMenu(self)
        context_clip = None
        if index.isValid():
            clips = self.timeline_table.timeline_clips()
            if 0 <= index.row() < len(clips):
                context_clip = clips[index.row()]

        preview_action = menu.addAction("Preview This Item")
        effects_action = menu.addAction("Edit Zoom-In / Slowmo...")
        clear_effects_action = menu.addAction("Clear Zoom / Slowmo")
        menu.addSeparator()
        move_to_row_action = menu.addAction("Move to Row...")
        move_top_action = menu.addAction("Move to Top")
        move_up_action = menu.addAction("Move Up")
        move_down_action = menu.addAction("Move Down")
        move_bottom_action = menu.addAction("Move to Bottom")
        menu.addSeparator()
        delete_action = menu.addAction("Delete")

        chosen = menu.exec(self.timeline_table.viewport().mapToGlobal(position))
        if chosen == preview_action:
            if context_clip:
                self.preview_timeline_clip_in_main_preview(context_clip)
            else:
                self.preview_selected_timeline_clip()
        elif chosen == effects_action:
            self.edit_selected_timeline_clip_effects()
        elif chosen == clear_effects_action:
            self.clear_selected_timeline_clip_effects()
        elif chosen == move_to_row_action:
            self.move_selected_timeline_clips_to_row()
        elif chosen == move_top_action:
            self.move_selected_timeline_clips("top")
        elif chosen == move_up_action:
            self.move_selected_timeline_clips("up")
        elif chosen == move_down_action:
            self.move_selected_timeline_clips("down")
        elif chosen == move_bottom_action:
            self.move_selected_timeline_clips("bottom")
        elif chosen == delete_action:
            self.delete_selected_timeline_clips()

    def edit_selected_timeline_clip_effects(self) -> None:
        selected = self.timeline_table.selected_timeline_clip()
        if not selected:
            self._show_warning("Select one or more Main Timeline clips first.")
            return

        timeline = self.timeline_table.timeline_clips()
        selected_rows = sorted({row.row() for row in self.timeline_table.selectionModel().selectedRows()})
        selected_clips = [timeline[row] for row in selected_rows if 0 <= row < len(timeline)]
        photo_clips = [clip for clip in selected_clips if self._is_photo_clip(clip)]
        has_photo = bool(photo_clips)
        has_video = any(not self._is_photo_clip(clip) for clip in selected_clips)
        default_photo_duration = self._clip_output_duration(photo_clips[0]) if photo_clips else 3.0

        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Clip Effects")
        layout = QFormLayout(dialog)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        zoom_spin = QDoubleSpinBox()
        zoom_spin.setRange(100.0, 300.0)
        zoom_spin.setDecimals(0)
        zoom_spin.setSingleStep(5.0)
        zoom_spin.setSuffix(" %")
        zoom_spin.setValue(float(selected.get("zoom_percent", 100.0) or 100.0))

        slowmo_spin = QDoubleSpinBox()
        slowmo_spin.setRange(1.0, 4.0)
        slowmo_spin.setDecimals(2)
        slowmo_spin.setSingleStep(0.1)
        slowmo_spin.setSuffix("x")
        slowmo_spin.setValue(float(selected.get("slowmo_factor", 1.0) or 1.0))
        slowmo_spin.setEnabled(has_video)
        slowmo_spin.setToolTip("Slowmo hanya berlaku untuk clip video; photo tetap berupa still frame.")

        photo_duration_spin = QDoubleSpinBox()
        photo_duration_spin.setRange(0.1, 60.0)
        photo_duration_spin.setDecimals(2)
        photo_duration_spin.setSingleStep(0.25)
        photo_duration_spin.setSuffix(" sec")
        photo_duration_spin.setValue(max(0.1, default_photo_duration or 3.0))
        photo_duration_spin.setToolTip("Durasi still photo di Main Timeline.")

        layout.addRow("Zoom akhir", zoom_spin)
        layout.addRow("Slowmo", slowmo_spin)
        if has_photo:
            layout.addRow("Durasi photo", photo_duration_spin)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        changed = self.timeline_table.apply_effects_to_selected(
            zoom_spin.value(),
            slowmo_spin.value() if has_video else 1.0,
            photo_duration_spin.value() if has_photo else None,
        )
        if not changed:
            self._show_warning("Select one or more Main Timeline clips first.")
            return
        self._log(
            f"Applied clip effects: zoom-in 100% -> {zoom_spin.value():.0f}%"
            + (f", slowmo {slowmo_spin.value():.2f}x" if has_video else "")
            + (f", photo {photo_duration_spin.value():.2f}s" if has_photo else "")
            + f" to {changed} timeline clip(s)."
        )
        self.save_project()

    def clear_selected_timeline_clip_effects(self) -> None:
        changed = self.timeline_table.apply_effects_to_selected(100.0, 1.0)
        if not changed:
            self._show_warning("Select one or more Main Timeline clips first.")
            return
        self._log(f"Cleared zoom/slowmo effects from {changed} timeline clip(s).")
        self.save_project()

    def move_selected_timeline_clips_to_row(self) -> None:
        selected_rows = sorted({row.row() for row in self.timeline_table.selectionModel().selectedRows()})
        if not selected_rows:
            self._show_warning("Select one or more Main Timeline clips first.")
            return
        row_count = self.timeline_table.rowCount()
        if row_count <= 0:
            self._show_warning("Main Timeline is empty.")
            return

        target_row, accepted = QInputDialog.getInt(
            self,
            "Move to Row",
            f"Move selected clip(s) to row number 1 - {row_count}:",
            selected_rows[0] + 1,
            1,
            row_count,
            1,
        )
        if not accepted:
            return
        if not self.timeline_table.move_selected_rows_to_position(target_row):
            self.statusBar().showMessage("Selected clip(s) are already at that position", 2500)
            return
        self._log(f"Moved selected Main Timeline clip(s) to row {target_row}.")
        self.save_project()

    def move_selected_timeline_clips(self, target: str) -> None:
        actions = {
            "top": (lambda: self.timeline_table.move_selected_rows_to_edge(top=True), "to the top"),
            "up": (lambda: self.timeline_table.move_selected_rows(-1), "up"),
            "down": (lambda: self.timeline_table.move_selected_rows(1), "down"),
            "bottom": (lambda: self.timeline_table.move_selected_rows_to_edge(top=False), "to the bottom"),
        }
        action = actions.get(target)
        if not action:
            return
        moved, label = action[0](), action[1]
        if not moved:
            self._show_warning(
                "Select one or more Main Timeline clips, or choose clips that are not already at that position."
            )
            return
        self._log(f"Moved selected Main Timeline clip(s) {label}.")
        self.save_project()

    def adjust_timeline_zoom(self, delta: float) -> None:
        self.timeline_table.set_zoom(self.timeline_table.zoom() + delta)

    def build_rough_cut_timeline(self) -> None:
        if not self._require_video():
            return

        assert self.project is not None
        video_path = self.project.video_path
        config = self._rough_cut_config()
        transcript_records = self.database.fetch_segments() if self.database else []
        thumb_dir = Path(self.project.project_dir) / "thumbnails"

        def task(progress: Callable[[str], None]) -> list[dict[str, Any]]:
            progress("Building rough cut timeline plan from Video Ori...")
            segments = build_rough_cut_plan(video_path, config)
            hook_segment = None
            if config.use_video_hook:
                hook_segment = detect_conflict_hook_segment(
                    transcript_records,
                    video_path,
                    hook_seconds=config.hook_seconds,
                    source_start_seconds=config.source_start_seconds,
                    source_end_seconds=config.source_end_seconds,
                )
            if hook_segment is not None:
                segments = [hook_segment] + segments

            clips: list[dict[str, Any]] = []
            target_remaining = max(0.0, float(config.target_final_seconds or 0))
            for index, segment in enumerate(segments, start=1):
                source_duration = max(0.1, segment.end - segment.start)
                planned_duration = (
                    source_duration
                    if segment.index == 0
                    else max(source_duration, float(config.scene_output_seconds or source_duration))
                )
                if target_remaining > 0:
                    if target_remaining <= 0.05:
                        break
                    output_duration = min(planned_duration, target_remaining)
                    target_remaining -= output_duration
                else:
                    output_duration = planned_duration
                clip_id = f"rough_{index:03d}_{uuid.uuid4().hex[:6]}"
                item = {
                    "id": clip_id,
                    "start": format_duration(segment.start),
                    "end": format_duration(segment.end),
                    "output_duration": round(output_duration, 3),
                    "text": (
                        f"Rough cut {format_duration(segment.start)} - {format_duration(segment.end)} "
                        f"-> {format_duration(output_duration)}"
                    ),
                    "kind": "rough",
                    "timeline_role": "hook" if segment.index == 0 else "scene",
                }
                thumb_path = thumb_dir / f"{clip_id}.jpg"
                try:
                    extract_clip_thumbnail(video_path, thumb_path, segment.start)
                    item["thumbnail_path"] = str(thumb_path)
                except Exception as exc:
                    progress(f"Thumbnail skipped for {clip_id}: {exc}")
                clips.append(item)
            progress(f"Prepared {len(clips)} timeline clip(s).")
            return clips

        def done(clips: list[dict[str, Any]]) -> None:
            self.timeline_table.set_timeline_clips(clips)
            self._refresh_timeline_total_label()
            self._push_editor_history()
            self._log(f"Built rough cut timeline with {len(clips)} clip(s).")
            self.save_project()
            self.tabs.setCurrentWidget(self.cuts_tab)
            self.statusBar().showMessage("Rough cut timeline built", 4000)

        self._start_task("Building rough cut timeline", task, done)

    def export_final_video(self) -> None:
        if not self._require_video():
            return

        timeline = self._timeline_with_output_durations(self.timeline_table.timeline_clips())
        if not timeline:
            self._show_warning("Timeline is empty. Build a rough cut or drag Manual Clips into it first.")
            return
        self.timeline_table.set_timeline_clips(timeline)
        self._refresh_timeline_total_label()
        total_duration = self._timeline_total_duration(timeline)
        total_clips = len(timeline)

        if not self.export_output_input.text().strip():
            self.choose_export_output_file()
        output_path = self.export_output_input.text().strip()
        if not output_path:
            return

        assert self.project is not None
        video_path = self.project.video_path
        resolution = self.export_resolution_combo.currentText()
        fps = self.export_fps_spin.value()
        bitrate = self.export_bitrate_input.text().strip()

        def task(progress: Callable[[str], None]) -> str:
            progress(
                f"Exporting full Main Timeline: {total_clips} clip(s), "
                f"total {format_duration(total_duration)}."
            )
            output = export_timeline_video(
                video_path=video_path,
                output_path=output_path,
                clips=timeline,
                resolution=resolution,
                fps=fps,
                bitrate=bitrate,
                progress_callback=progress,
            )
            return str(output)

        def done(path: str) -> None:
            self._log(
                f"Exported full Main Timeline: {total_clips} clip(s), "
                f"{format_duration(total_duration)} -> {path}"
            )
            self.save_project()
            QMessageBox.information(
                self,
                "Export Complete",
                "Full Main Timeline exported.\n\n"
                f"Clips: {total_clips}\n"
                f"Timeline duration: {format_duration(total_duration)}\n"
                f"Output:\n{path}",
            )

        self._start_task("Exporting final video", task, done)

    def _timeline_with_output_durations(self, clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.editor_vm.timeline_with_output_durations(
            clips,
            self._timeline_duration_config(),
        )

    def _timeline_duration_config(self) -> TimelineDurationConfig:
        config = self._rough_cut_config()
        return TimelineDurationConfig(
            target_final_seconds=float(config.target_final_seconds or 0.0),
            scene_output_seconds=float(config.scene_output_seconds or 0.0),
            hook_seconds=float(config.hook_seconds or 0.0),
            clip_seconds=float(config.clip_seconds or 0.0),
        )

    def _timeline_total_duration(self, clips: list[dict[str, Any]]) -> float:
        return self.editor_vm.timeline_total_duration(clips)

    def _refresh_timeline_total_label(self) -> None:
        if not getattr(self, "timeline_total_label", None):
            return
        clips = self._timeline_with_output_durations(self.timeline_table.timeline_clips())
        total_duration = self._timeline_total_duration(clips)
        self.timeline_total_label.setText(
            f"Timeline total: {format_duration(total_duration)} ({len(clips)} clips)"
        )

    def _clip_source_duration(self, clip: dict[str, Any]) -> float:
        return self.editor_vm.clip_source_duration(clip)

    def _clip_output_duration(self, clip: dict[str, Any]) -> float:
        return self.editor_vm.clip_output_duration(clip)

    def _is_photo_clip(self, clip: dict[str, Any]) -> bool:
        return self.editor_vm.is_photo_clip(clip)

    def _export_settings_dict(self) -> dict[str, Any]:
        return {
            "resolution": self.export_resolution_combo.currentText(),
            "fps": float(self.export_fps_spin.value()),
            "bitrate": self.export_bitrate_input.text().strip(),
            "output_path": self.export_output_input.text().strip(),
        }

    def _apply_export_settings(self, settings: dict[str, Any]) -> None:
        settings = settings or {}
        resolution = str(settings.get("resolution") or "1280x720")
        index = self.export_resolution_combo.findText(resolution)
        self.export_resolution_combo.setCurrentIndex(index if index >= 0 else 0)
        self.export_fps_spin.setValue(float(settings.get("fps", 30.0) or 0.0))
        self.export_bitrate_input.setText(str(settings.get("bitrate", "4500k")))
        self.export_output_input.setText(str(settings.get("output_path", "")))

    def _with_clip_thumbnail(self, item: dict[str, Any]) -> dict[str, Any]:
        data = dict(item)
        if not self.project or not self.project.video_path:
            return data
        try:
            start = ClipItem.from_dict(data).start
        except (TypeError, ValueError):
            return data
        clip_id = str(data.get("id") or f"clip_{uuid.uuid4().hex[:6]}")
        thumb_dir = Path(self.project.project_dir) / "thumbnails"
        thumb_path = thumb_dir / f"{self._safe_project_filename(clip_id)}.jpg"
        try:
            extract_clip_thumbnail(self.project.video_path, thumb_path, start)
            data["thumbnail_path"] = str(thumb_path)
        except Exception as exc:
            self._log(f"Thumbnail skipped for {clip_id}: {exc}")
        return data

    def _capture_editor_state(self) -> dict[str, Any]:
        manual_clips = self.cut_table.to_cut_items() if getattr(self, "cut_table", None) else []
        timeline_clips = (
            self.timeline_table.timeline_clips() if getattr(self, "timeline_table", None) else []
        )
        return self.editor_vm.capture_state(manual_clips, timeline_clips)

    def _apply_editor_state(self, state: dict[str, Any]) -> None:
        with self.editor_vm.restoring_history():
            self.cut_table.set_cut_items(list(state.get("manual_clips") or []))
            self.timeline_table.set_timeline_clips(list(state.get("timeline_clips") or []))
            self._refresh_timeline_total_label()

    def _reset_editor_history(self) -> None:
        self.editor_vm.history.reset(self._capture_editor_state())

    def _push_editor_history(self) -> None:
        if self.editor_vm.is_restoring_history:
            return
        self.editor_vm.history.push(self._capture_editor_state())

    def _on_editor_timeline_changed(self) -> None:
        self._refresh_timeline_total_label()
        self._push_editor_history()
        if self.project:
            self.save_project()

    def _on_editor_manual_changed(self, _item: QTableWidgetItem) -> None:
        self._push_editor_history()
        if self.project:
            self.save_project()

    def undo_editor_change(self) -> None:
        state = self.editor_vm.history.undo()
        if state is None:
            self.statusBar().showMessage("Nothing to undo", 2500)
            return
        self._apply_editor_state(state)
        self.save_project()
        self.statusBar().showMessage("Undo", 2500)

    def redo_editor_change(self) -> None:
        state = self.editor_vm.history.redo()
        if state is None:
            self.statusBar().showMessage("Nothing to redo", 2500)
            return
        self._apply_editor_state(state)
        self.save_project()
        self.statusBar().showMessage("Redo", 2500)

    def suggest_conflict_hook(self) -> None:
        if not self._require_project():
            return

        transcript_text = self._current_story_source_text()
        title = self.project.name if self.project else "StoryCut AI"
        self.rough_hook_edit.setPlainText(build_conflict_hook(transcript_text, title=title))
        self.statusBar().showMessage("Conflict hook suggested", 4000)

    def choose_rough_music_file(self) -> None:
        start_dir = str(Path(self.project.project_dir) if self.project else self.app_root)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Royalty-Free Background Music",
            start_dir,
            "Audio Files (*.mp3 *.wav *.m4a *.aac *.flac *.ogg);;All Files (*)",
        )
        if not path:
            return
        self.rough_music_path_input.setText(path)
        if self.project:
            self.save_project()

    def clear_rough_music_file(self) -> None:
        self.rough_music_path_input.clear()
        if self.project:
            self.save_project()

    def use_full_rough_range(self) -> None:
        if not getattr(self, "rough_range_selector", None):
            return
        duration = self.rough_range_selector.duration_seconds()
        if self.project and self.project.metadata:
            duration = VideoMetadata.from_dict(self.project.metadata).duration
        self.rough_range_selector.set_range(0.0, duration)

    def _rough_range_changed(self, start: float, end: float) -> None:
        if not getattr(self, "rough_range_label", None):
            return
        if end <= start:
            self.rough_range_label.setText("Import Video Ori to choose the rough cut range.")
            return
        self.rough_range_label.setText(
            f"Selected Video Ori: {format_duration(start)} - {format_duration(end)}"
        )
        self._sync_rough_target_from_percent()

    def _sync_rough_target_from_percent(self, *_: Any) -> None:
        if not getattr(self, "rough_target_percent_spin", None):
            return
        base_seconds = self._rough_target_base_seconds()
        target_seconds = base_seconds * (self.rough_target_percent_spin.value() / 100.0)
        self.rough_target_final_minutes_spin.setValue(round(target_seconds / 60.0, 1))

    def _rough_target_base_seconds(self) -> float:
        start, end = self._rough_source_range()
        if end > start:
            return end - start
        if self.project and self.project.metadata:
            return VideoMetadata.from_dict(self.project.metadata).duration
        return 0.0

    def _refresh_rough_range_selector(self, duration_seconds: float | None = None) -> None:
        if not getattr(self, "rough_range_selector", None):
            return
        duration = duration_seconds or 0.0
        if duration <= 0 and self.project and self.project.metadata:
            duration = VideoMetadata.from_dict(self.project.metadata).duration
        self.rough_range_selector.set_duration(duration)

    def _rough_source_range(self) -> tuple[float, float]:
        if not getattr(self, "rough_range_selector", None):
            return 0.0, 0.0
        return self.rough_range_selector.selected_range()

    def _rough_range_label_text(self, start: float, end: float) -> str:
        if end <= start:
            return "Full video"
        return f"{format_duration(start)} - {format_duration(end)}"

    def _rough_range_filename_suffix(self, start: float, end: float) -> str:
        if end <= start:
            return ""
        return f"_{self._time_for_filename(start)}_to_{self._time_for_filename(end)}"

    def _time_for_filename(self, seconds: float) -> str:
        return time_for_filename(seconds)

    def choose_subtitle_output_file(self) -> None:
        if not self._require_project():
            return

        default_path = self._default_subtitle_output_path()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Indonesian Subtitle",
            str(default_path),
            "SubRip Subtitle (*.srt);;All Files (*)",
        )
        if not path:
            return
        self.subtitle_output_input.setText(path)

    def generate_indonesian_subtitles(self) -> None:
        if not self._require_video():
            return

        assert self.project is not None
        video_path = self.project.video_path
        audio_path = Path(self.project.project_dir) / "audio" / "subtitle_audio.wav"
        output_path = Path(self.subtitle_output_input.text().strip() or self._default_subtitle_output_path())
        database_path = self.project.database_path
        model_size = self.model_combo.currentText()
        device = self.device_combo.currentText()
        compute_type = self.compute_combo.currentText()
        audio_mode = str(self.subtitle_source_combo.currentData() or "foreign")
        source_language = str(self.subtitle_language_combo.currentData() or "") or None

        def task(progress: Callable[[str], None]) -> dict[str, Any]:
            extract_audio(video_path, audio_path, progress_callback=progress)

            transcriber = WhisperTranscriber(
                model_size=model_size,
                device=device,
                compute_type=compute_type,
            )

            if audio_mode == "id":
                progress("Transcribing Indonesian audio with local Whisper...")
                segments = transcriber.transcribe(
                    audio_path,
                    language="id",
                    task="transcribe",
                    condition_on_previous_text=False,
                    progress_callback=progress,
                )
            else:
                progress("Translating video audio to English timestamps with local Whisper...")
                if source_language:
                    progress(f"Using source language hint: {source_language}")
                english_segments = transcriber.transcribe(
                    audio_path,
                    language=source_language,
                    task="translate",
                    condition_on_previous_text=False,
                    progress_callback=progress,
                )
                progress("Translating subtitle text from English to Indonesian locally...")
                translator = LocalIndonesianTranslator()
                segments = translator.translate_segments(
                    english_segments,
                    progress_callback=progress,
                )

            segments = prepare_subtitle_segments(segments)
            if not segments:
                raise RuntimeError(
                    "No subtitle text was generated. Try a larger Whisper model, check that the video has clear audio, "
                    "or set Source language manually."
                )
            srt_path = write_srt_file(segments, output_path)
            db = TranscriptDatabase(database_path)
            db.replace_segments(segments)
            return {
                "srt_path": str(srt_path),
                "audio_path": str(audio_path),
                "records": db.fetch_segments(),
            }

        def done(result: dict[str, Any]) -> None:
            assert self.project is not None
            self.project.audio_path = str(result["audio_path"])
            records = list(result["records"])
            self.transcript_table.set_segments(records)
            self.subtitle_output_input.setText(str(result["srt_path"]))
            self.subtitle_status_view.setPlainText(
                "Subtitle Indonesia selesai dibuat.\n\n"
                f"File SRT:\n{result['srt_path']}\n\n"
                f"Jumlah subtitle: {len(records)} segment."
            )
            self._log(f"Generated Indonesian SRT subtitle: {result['srt_path']}")
            self.save_project()
            QMessageBox.information(
                self,
                "Subtitle Complete",
                f"Subtitle Indonesia berhasil dibuat:\n{result['srt_path']}",
            )

        self._start_task("Generating Indonesian subtitles", task, done)

    def _default_subtitle_output_path(self) -> Path:
        if not self.project:
            return self.app_root / "indonesian_audio_subtitles.srt"
        output_dir = Path(self.project.project_dir) / "subtitles"
        output_dir.mkdir(exist_ok=True)
        return output_dir / "indonesian_audio_subtitles.srt"

    def export_rough_cut_video(self) -> None:
        if not self._require_video():
            return

        assert self.project is not None
        if not self.rough_hook_edit.toPlainText().strip():
            self.suggest_conflict_hook()

        default_dir = Path(self.project.project_dir) / "rough_cuts"
        default_dir.mkdir(exist_ok=True)
        range_start, range_end = self._rough_source_range()
        default_path = default_dir / f"story_rough_cut{self._rough_range_filename_suffix(range_start, range_end)}.mp4"
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Rough Cut Video",
            str(default_path),
            "MP4 Video (*.mp4);;All Files (*)",
        )
        if not output_path:
            return

        hook_text = self.rough_hook_edit.toPlainText().strip()
        config = self._rough_cut_config()
        video_path = self.project.video_path
        transcript_records = self.database.fetch_segments() if self.database else []

        def task(progress: Callable[[str], None]) -> str:
            hook_segment = None
            if config.use_video_hook:
                progress("Finding conflict video hook from transcript timestamps...")
                hook_segment = detect_conflict_hook_segment(
                    transcript_records,
                    video_path,
                    hook_seconds=config.hook_seconds,
                    source_start_seconds=config.source_start_seconds,
                    source_end_seconds=config.source_end_seconds,
                )
            output = export_story_rough_cut(
                video_path=video_path,
                output_path=output_path,
                hook_text=hook_text,
                config=config,
                hook_segment=hook_segment,
                progress_callback=progress,
            )
            return str(output)

        def done(path: str) -> None:
            self._add_rough_cut_part(
                {
                    "range": self._rough_range_label_text(
                        config.source_start_seconds,
                        config.source_end_seconds,
                    ),
                    "source_start": config.source_start_seconds,
                    "source_end": config.source_end_seconds,
                    "path": path,
                    "status": "Ready",
                }
            )
            self._log(f"Exported rough cut video: {path}")
            QMessageBox.information(
                self,
                "Rough Cut Complete",
                "The rough cut video was exported. Use it as editable review/storytelling material; "
                "this does not guarantee copyright safety.",
            )
            self.save_project()

        self._start_task("Exporting rough cut video", task, done)

    def remove_selected_rough_part(self) -> None:
        row = self.rough_parts_table.currentRow()
        if row < 0 or row >= len(self.rough_cut_parts):
            self._show_warning("Select one rough cut part first.")
            return
        removed = self.rough_cut_parts.pop(row)
        self._refresh_rough_parts_table()
        self._log(f"Removed rough cut part from list: {removed.get('path', '')}")
        self.save_project()

    def combine_rough_cut_part_videos(self) -> None:
        if not self._require_project():
            return
        parts = [part for part in self.rough_cut_parts if Path(str(part.get("path", ""))).exists()]
        if not parts:
            self._show_warning("Export at least one rough cut part first.")
            return

        assert self.project is not None
        default_dir = Path(self.project.project_dir) / "rough_cuts"
        default_dir.mkdir(exist_ok=True)
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Combined Rough Cut",
            str(default_dir / "story_rough_cut_combined.mp4"),
            "MP4 Video (*.mp4);;All Files (*)",
        )
        if not output_path:
            return

        part_paths = [str(part["path"]) for part in parts]

        def task(progress: Callable[[str], None]) -> str:
            output = combine_rough_cut_parts(
                part_paths,
                output_path,
                progress_callback=progress,
            )
            return str(output)

        def done(path: str) -> None:
            self._log(f"Combined rough cut parts: {path}")
            QMessageBox.information(
                self,
                "Combine Complete",
                f"Combined rough cut video exported:\n{path}",
            )

        self._start_task("Combining rough cut parts", task, done)

    def _add_rough_cut_part(self, part: dict[str, Any]) -> None:
        self.rough_cut_parts.append(dict(part))
        self._refresh_rough_parts_table()
        self.save_project()

    def _set_rough_cut_parts(self, parts: list[dict[str, Any]]) -> None:
        self.rough_cut_parts = [dict(part) for part in parts or []]
        self._refresh_rough_parts_table()

    def _refresh_rough_parts_table(self) -> None:
        if not getattr(self, "rough_parts_table", None):
            return
        self.rough_parts_table.setRowCount(len(self.rough_cut_parts))
        for row, part in enumerate(self.rough_cut_parts):
            path = str(part.get("path", ""))
            range_text = str(part.get("range", "Full video"))
            status = str(part.get("status", "Ready"))
            if path and not Path(path).exists():
                status = "Missing file"
            self.rough_parts_table.setItem(row, 0, self._readonly_table_item(range_text))
            self.rough_parts_table.setItem(row, 1, self._readonly_table_item(path))
            self.rough_parts_table.setItem(row, 2, self._readonly_table_item(status))
        self.rough_parts_table.resizeRowsToContents()

    def _readonly_table_item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _generate_script_for_rough_cut(self, rough_cut_path: str) -> str | None:
        if not self.project:
            return None

        source_text = self._current_story_source_text(include_current_script=False)
        hook_text = self.rough_hook_edit.toPlainText().strip()
        rough_cut = Path(rough_cut_path)
        context = "\n".join(
            part
            for part in [
                f"ROUGH CUT VIDEO: {rough_cut.name}",
                f"TARGET DURATION: {self.rough_target_final_minutes_spin.value():.1f} minutes",
                f"HOOK NOTES: {hook_text}" if hook_text else "",
                source_text,
            ]
            if part.strip()
        )

        generator = RuleBasedScriptGenerator()
        script = generator.generate(
            context,
            title=self.project.name,
            language="id",
            style="screenplay",
        )

        style_index = self.script_style_combo.findData("screenplay")
        if style_index >= 0:
            self.script_style_combo.setCurrentIndex(style_index)
        language_index = self.script_language_combo.findData("id")
        if language_index >= 0:
            self.script_language_combo.setCurrentIndex(language_index)

        self.script_edit.setPlainText(script)
        self.tabs.setCurrentWidget(self.script_edit.parentWidget())

        script_path = rough_cut.with_name(f"{rough_cut.stem}_skenario_narasi.txt")
        script_path.write_text(script, encoding="utf-8")
        self._log(f"Generated rough cut screenplay/narration script: {script_path}")
        return str(script_path)

    def generate_script(self) -> None:
        if not self._require_database():
            return

        self._generate_script_from_current_transcript()

    def _generate_script_from_current_transcript(self) -> None:
        if not self.database or not self.project:
            return

        records = self.database.fetch_segments()
        transcript_text = self._timeline_text_for_script(records)
        language = str(self.script_language_combo.currentData() or "id")
        style = str(self.script_style_combo.currentData() or "recap")
        generator = RuleBasedScriptGenerator()
        script = generator.generate(
            transcript_text,
            title=self.project.name,
            language=language,
            style=style,
        )
        self.script_edit.setPlainText(script)
        language_label = SUPPORTED_SCRIPT_LANGUAGES.get(language, language)
        style_label = SUPPORTED_SCRIPT_STYLES.get(style, style)
        self._log(f"Generated {style_label} script in {language_label}.")
        self.tabs.setCurrentWidget(self.script_edit.parentWidget())
        self.save_project()

    def _timeline_text_for_script(self, records: list[Any]) -> str:
        entries: list[tuple[float, int, str]] = []
        for record in records:
            text = str(getattr(record, "text", "") or "").strip()
            if not text:
                continue
            entries.append((float(getattr(record, "start", 0.0) or 0.0), 1, text))

        for note in self.scene_table.to_scene_notes():
            line = format_scene_note_for_script(note)
            if not line:
                continue
            entries.append((float(note.get("timestamp", 0.0) or 0.0), 0, line))

        entries.sort(key=lambda item: (item[0], item[1]))
        return "\n".join(text for _, _, text in entries)

    def _current_story_source_text(self, include_current_script: bool = True) -> str:
        pieces: list[str] = []
        if self.database:
            records = self.database.fetch_segments()
            pieces.append(self._timeline_text_for_script(records))
        for note in self.scene_table.to_scene_notes():
            text = str(note.get("note") or "").strip()
            if text:
                pieces.append(text)
        current_script = self.script_edit.toPlainText().strip() if include_current_script else ""
        if current_script:
            pieces.append(current_script)
        return "\n".join(piece for piece in pieces if piece)

    def _rough_cut_config(self) -> RoughCutConfig:
        source_start, source_end = self._rough_source_range()
        return RoughCutConfig(
            clip_seconds=self.rough_clip_seconds_spin.value(),
            sample_every_seconds=self.rough_sample_every_spin.value(),
            max_clips=self.rough_max_clips_spin.value(),
            scene_output_seconds=self.rough_scene_output_seconds_spin.value(),
            target_final_seconds=int(round(self.rough_target_final_minutes_spin.value() * 60)),
            slow_every_n_clips=self.rough_slow_every_spin.value(),
            slow_factor=self.rough_slow_factor_spin.value(),
            hook_seconds=self.rough_hook_seconds_spin.value(),
            use_video_hook=self.rough_video_hook_check.isChecked(),
            fill_with_neighbor_clips=self.rough_neighbor_fill_check.isChecked(),
            keep_audio=self.rough_keep_audio_check.isChecked(),
            zoom_percent=self.rough_zoom_spin.value(),
            mirror_every_n_clips=self.rough_mirror_every_spin.value(),
            transition_seconds=self.rough_transition_spin.value(),
            color_grade=str(self.rough_color_grade_combo.currentData() or "review_warm"),
            background_audio_path=self.rough_music_path_input.text().strip(),
            background_audio_volume=self.rough_music_volume_spin.value(),
            source_start_seconds=source_start,
            source_end_seconds=source_end,
        )

    def _rough_cut_settings_dict(self) -> dict[str, Any]:
        return {
            "clip_seconds": self.rough_clip_seconds_spin.value(),
            "sample_every_seconds": self.rough_sample_every_spin.value(),
            "max_clips": self.rough_max_clips_spin.value(),
            "scene_output_seconds": self.rough_scene_output_seconds_spin.value(),
            "target_final_minutes": float(self.rough_target_final_minutes_spin.value()),
            "target_percent": float(self.rough_target_percent_spin.value()),
            "slow_every_n_clips": self.rough_slow_every_spin.value(),
            "slow_factor": self.rough_slow_factor_spin.value(),
            "hook_seconds": self.rough_hook_seconds_spin.value(),
            "use_video_hook": self.rough_video_hook_check.isChecked(),
            "fill_with_neighbor_clips": self.rough_neighbor_fill_check.isChecked(),
            "keep_audio": self.rough_keep_audio_check.isChecked(),
            "zoom_percent": self.rough_zoom_spin.value(),
            "mirror_every_n_clips": self.rough_mirror_every_spin.value(),
            "transition_seconds": float(self.rough_transition_spin.value()),
            "color_grade": str(self.rough_color_grade_combo.currentData() or "review_warm"),
            "background_audio_path": self.rough_music_path_input.text().strip(),
            "background_audio_volume": float(self.rough_music_volume_spin.value()),
            "source_start_seconds": float(self._rough_source_range()[0]),
            "source_end_seconds": float(self._rough_source_range()[1]),
        }

    def _apply_rough_cut_settings(self, settings: dict[str, Any]) -> None:
        settings = settings or {}
        self.rough_clip_seconds_spin.setValue(int(settings.get("clip_seconds", 5)))
        self.rough_sample_every_spin.setValue(int(settings.get("sample_every_seconds", 30)))
        self.rough_max_clips_spin.setValue(int(settings.get("max_clips", 60)))
        self.rough_scene_output_seconds_spin.setValue(int(settings.get("scene_output_seconds", 12)))
        source_start = float(settings.get("source_start_seconds", 0.0) or 0.0)
        source_end = float(settings.get("source_end_seconds", 0.0) or 0.0)
        if getattr(self, "rough_range_selector", None) and source_end > 0:
            self.rough_range_selector.set_range(source_start, source_end)
        if "target_percent" in settings:
            target_percent = float(settings.get("target_percent", 12.0))
        else:
            base_seconds = self._rough_target_base_seconds()
            target_minutes = float(settings.get("target_final_minutes", 12.0))
            target_percent = (target_minutes * 60 / base_seconds * 100) if base_seconds > 0 else 12.0
        target_percent = max(0.0, min(100.0, target_percent))
        self.rough_target_percent_spin.setValue(target_percent)
        self._sync_rough_target_from_percent()
        self.rough_slow_every_spin.setValue(int(settings.get("slow_every_n_clips", 0)))
        self.rough_slow_factor_spin.setValue(float(settings.get("slow_factor", 1.2)))
        self.rough_hook_seconds_spin.setValue(int(settings.get("hook_seconds", 5)))
        self.rough_video_hook_check.setChecked(bool(settings.get("use_video_hook", True)))
        self.rough_neighbor_fill_check.setChecked(bool(settings.get("fill_with_neighbor_clips", True)))
        self.rough_keep_audio_check.setChecked(bool(settings.get("keep_audio", False)))
        self.rough_zoom_spin.setValue(int(settings.get("zoom_percent", 4)))
        self.rough_mirror_every_spin.setValue(int(settings.get("mirror_every_n_clips", 2)))
        self.rough_transition_spin.setValue(float(settings.get("transition_seconds", 0.15)))
        color_grade = str(settings.get("color_grade", "review_warm"))
        color_index = self.rough_color_grade_combo.findData(color_grade)
        self.rough_color_grade_combo.setCurrentIndex(color_index if color_index >= 0 else 0)
        self.rough_music_path_input.setText(str(settings.get("background_audio_path", "")))
        self.rough_music_volume_spin.setValue(float(settings.get("background_audio_volume", 0.22)))

    def save_script_text(self) -> None:
        if not self._require_project():
            return

        script = self.script_edit.toPlainText().strip()
        if not script:
            self._show_warning("Generate or write a script first.")
            return

        assert self.project is not None
        default_path = Path(self.project.project_dir) / "story_script.txt"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Script TXT",
            str(default_path),
            "Text Files (*.txt);;All Files (*)",
        )
        if not path:
            return

        try:
            Path(path).write_text(script, encoding="utf-8")
            self._log(f"Saved script TXT: {path}")
            self.save_project()
            self.statusBar().showMessage("Script saved", 4000)
        except Exception as exc:
            self._show_error(str(exc))

    def _refresh_visual_editor_video(self, duration_seconds: float | None = None) -> None:
        if not getattr(self, "visual_cut_editor", None):
            return

        if not self.project or not self.project.video_path:
            self.visual_cut_editor.set_video("", 0.0)
            return

        duration = duration_seconds
        if duration is None and self.project.metadata:
            duration = VideoMetadata.from_dict(self.project.metadata).duration
        self.visual_cut_editor.set_video(self.project.video_path, duration or 0.0)

    def _load_project_data(self, data: ProjectData) -> None:
        self.project = data
        Path(data.project_dir).mkdir(parents=True, exist_ok=True)
        Path(data.project_dir, "audio").mkdir(exist_ok=True)
        Path(data.project_dir, "clips").mkdir(exist_ok=True)
        Path(data.project_dir, "photos").mkdir(exist_ok=True)
        Path(data.project_dir, "scene_frames").mkdir(exist_ok=True)
        Path(data.project_dir, "rough_cuts").mkdir(exist_ok=True)
        Path(data.project_dir, "exports").mkdir(exist_ok=True)
        Path(data.project_dir, "thumbnails").mkdir(exist_ok=True)
        self.database = TranscriptDatabase(data.database_path)

        metadata = VideoMetadata.from_dict(data.metadata) if data.metadata else None
        self.metadata_view.setText(metadata_to_text(metadata))
        self._refresh_visual_editor_video(metadata.duration if metadata else None)
        self._refresh_rough_range_selector(metadata.duration if metadata else None)
        self.scene_table.set_scene_notes(data.scene_notes)
        self.cut_table.set_cut_items(data.manual_clips or data.cut_list)
        self.timeline_table.set_timeline_clips(data.timeline_clips)
        self.timeline_preview_panel.set_video("", 0.0)
        self._refresh_timeline_total_label()
        self.checklist_widget.set_states(data.checklist)
        self.script_edit.setPlainText(data.script_text)
        self.rough_hook_edit.setPlainText(data.rough_hook_text)
        self._apply_rough_cut_settings(data.rough_cut_settings)
        self._apply_export_settings(data.export_settings)
        self._refresh_timeline_total_label()
        self._set_rough_cut_parts(data.rough_cut_parts)
        style_index = self.script_style_combo.findData(data.script_style)
        self.script_style_combo.setCurrentIndex(style_index if style_index >= 0 else 0)
        language_index = self.script_language_combo.findData(data.script_language)
        self.script_language_combo.setCurrentIndex(language_index if language_index >= 0 else 0)
        self.log_panel.set_messages(data.export_logs)
        self._refresh_transcript_table()
        self._set_project_label()
        self._reset_editor_history()
        self.statusBar().showMessage("Project loaded", 4000)

    def _sync_project_from_ui(self) -> None:
        if not self.project:
            return
        manual_clips = self.cut_table.to_cut_items()
        self.project.cut_list = manual_clips
        self.project.manual_clips = manual_clips
        self.project.timeline_clips = self.timeline_table.timeline_clips()
        self.project.checklist = self.checklist_widget.states()
        self.project.scene_notes = self.scene_table.to_scene_notes()
        self.project.script_text = self.script_edit.toPlainText()
        self.project.script_language = str(self.script_language_combo.currentData() or "id")
        self.project.script_style = str(self.script_style_combo.currentData() or "recap")
        self.project.rough_hook_text = self.rough_hook_edit.toPlainText()
        self.project.rough_cut_settings = self._rough_cut_settings_dict()
        self.project.rough_cut_parts = [dict(part) for part in self.rough_cut_parts]
        self.project.export_settings = self._export_settings_dict()

    def _refresh_transcript_table(self) -> None:
        if not self.database:
            self.transcript_table.set_segments([])
            return
        self.transcript_table.set_segments(self.database.fetch_segments())

    def _set_project_label(self) -> None:
        if not self.project:
            self.project_label.setText("No project loaded")
            if getattr(self, "project_status_label", None):
                self.project_status_label.setText("No project loaded")
            self.setWindowTitle("StoryCut AI")
            return

        video = self.project.video_path if self.project.video_path else "No Video Ori imported"
        text = f"{self.project.name} | {video}"
        self.project_label.setText(text)
        if getattr(self, "project_status_label", None):
            self.project_status_label.setText(text)
        self.setWindowTitle(f"StoryCut AI - {self.project.name}")

    def _require_project(self) -> bool:
        if not self.project:
            self._show_warning("Create or load a project first.")
            return False
        return True

    def _require_video(self) -> bool:
        if not self._require_project():
            return False
        assert self.project is not None
        if not self.project.video_path:
            self._show_warning("Import a video first.")
            return False
        return True

    def _require_database(self) -> bool:
        if not self._require_project():
            return False
        if not self.database:
            self._show_warning("Project database is not ready.")
            return False
        return True

    def _start_task(
        self,
        label: str,
        task: TaskFunction,
        on_success: Callable[[Any], None],
    ) -> None:
        worker = TaskWorker(task, self)
        progress_dialog = TaskProgressDialog(label, self)
        self._task_dialogs[worker] = progress_dialog

        worker.progress.connect(lambda message, active_worker=worker: self._task_progress(active_worker, message))
        worker.succeeded.connect(
            lambda result, active_worker=worker: self._task_succeeded(
                active_worker,
                result,
                on_success,
            )
        )
        worker.failed.connect(lambda message, active_worker=worker: self._task_failed(active_worker, message))
        worker.finished.connect(lambda: self._task_finished(worker))
        self._workers.append(worker)
        self._set_busy(True)
        self.statusBar().showMessage(label)
        self._task_progress(worker, label)
        progress_dialog.show()
        worker.start()

    def _task_progress(self, worker: TaskWorker, message: str) -> None:
        dialog = self._task_dialogs.get(worker)
        if dialog:
            dialog.set_message(message)
        self._log(message, persist=False)

    def _task_succeeded(
        self,
        worker: TaskWorker,
        result: Any,
        on_success: Callable[[Any], None],
    ) -> None:
        self._close_task_dialog(worker)
        try:
            on_success(result)
        except Exception as exc:
            self._show_error(str(exc))

    def _task_failed(self, worker: TaskWorker, message: str) -> None:
        self._close_task_dialog(worker)
        self._show_error(message)
        self._log(f"Error: {message}")

    def _task_finished(self, worker: TaskWorker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        self._close_task_dialog(worker)
        self._set_busy(False)
        self.statusBar().showMessage("Ready", 4000)

    def _close_task_dialog(self, worker: TaskWorker) -> None:
        dialog = self._task_dialogs.pop(worker, None)
        if dialog:
            dialog.close()
            dialog.deleteLater()

    def _set_busy(self, busy: bool) -> None:
        self._busy_count += 1 if busy else -1
        self._busy_count = max(0, self._busy_count)
        is_busy = self._busy_count > 0
        for button in getattr(self, "long_task_buttons", []):
            button.setEnabled(not is_busy)
        if is_busy:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        else:
            QApplication.restoreOverrideCursor()

    def _log(self, message: str, persist: bool = True) -> None:
        line = self.log_panel.append_message(message)
        if persist and self.project:
            self.project.export_logs.append(line)

    def _show_warning(self, message: str) -> None:
        QMessageBox.warning(self, "StoryCut AI", message)

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "StoryCut AI Error", message)

    def closeEvent(self, event: Any) -> None:
        if self.project:
            self.save_project()
        super().closeEvent(event)
