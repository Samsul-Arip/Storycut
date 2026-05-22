from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core.video_utils import format_duration, parse_timestamp


DEFAULT_CHECKLIST_ITEMS = [
    "I am adding original commentary, criticism, analysis, or explanation.",
    "I am using only the clips needed to support the review or storytelling point.",
    "No source video clip is longer than five seconds.",
    "I am not presenting long uninterrupted portions as a substitute for the original work.",
    "I replaced copied subtitles/dialogue with my own narration or paraphrased script.",
    "I removed source audio unless a short excerpt is necessary for commentary.",
    "Any background music I add is royalty-free or properly licensed.",
    "The final edit focuses on the core conflict, climax, resolution, and my own viewpoint.",
    "My narration changes the context by explaining meaning, themes, craft, or character choices.",
    "I will review platform and local legal guidance before publishing.",
    "I understand this checklist is guidance only and does not guarantee legal safety.",
]


class TranscriptTable(QTableWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._records: list[dict[str, Any]] = []
        self.setColumnCount(4)
        self.setHorizontalHeaderLabels(["ID", "Start", "End", "Text"])
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

    def set_segments(self, records: list[Any]) -> None:
        self._records = [_to_dict(record) for record in records]
        self.setRowCount(len(self._records))

        for row, record in enumerate(self._records):
            id_item = _readonly_item(str(record.get("id", "")))
            id_item.setData(Qt.ItemDataRole.UserRole, record)
            self.setItem(row, 0, id_item)
            self.setItem(row, 1, _readonly_item(format_duration(float(record.get("start", 0.0)))))
            self.setItem(row, 2, _readonly_item(format_duration(float(record.get("end", 0.0)))))
            self.setItem(row, 3, _readonly_item(str(record.get("text", ""))))

        self.resizeRowsToContents()

    def selected_segments(self) -> list[dict[str, Any]]:
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()})
        return [dict(self._records[row]) for row in rows if 0 <= row < len(self._records)]


class CutListTable(QTableWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(4)
        self.setHorizontalHeaderLabels(["Clip", "Start", "End", "Text"])
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

    def set_cut_items(self, items: list[dict[str, Any]]) -> None:
        self.blockSignals(True)
        self.setRowCount(len(items))

        for row, item in enumerate(items):
            data = dict(item)
            clip_id = str(data.get("id") or f"clip_{row + 1:03d}")
            start_text = _display_time(data.get("start", 0.0))
            end_text = _display_time(data.get("end", 0.0))

            id_item = _readonly_item(clip_id)
            id_item.setData(Qt.ItemDataRole.UserRole, data)
            self.setItem(row, 0, id_item)
            self.setItem(row, 1, QTableWidgetItem(start_text))
            self.setItem(row, 2, QTableWidgetItem(end_text))
            self.setItem(row, 3, QTableWidgetItem(str(data.get("text", ""))))

        self.blockSignals(False)
        self.resizeRowsToContents()

    def to_cut_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for row in range(self.rowCount()):
            id_item = self.item(row, 0)
            base = dict(id_item.data(Qt.ItemDataRole.UserRole) or {}) if id_item else {}
            base["id"] = id_item.text().strip() if id_item else f"clip_{row + 1:03d}"
            base["start"] = self.item(row, 1).text().strip() if self.item(row, 1) else "0"
            base["end"] = self.item(row, 2).text().strip() if self.item(row, 2) else "0"
            base["text"] = self.item(row, 3).text().strip() if self.item(row, 3) else ""
            items.append(base)
        return items

    def selected_cut_items(self) -> list[dict[str, Any]]:
        all_items = self.to_cut_items()
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()})
        return [all_items[row] for row in rows if 0 <= row < len(all_items)]

    def update_first_selected_range(self, start: float, end: float) -> dict[str, Any] | None:
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()})
        if not rows:
            return None

        row = rows[0]
        start_text = format_duration(start)
        end_text = format_duration(end)
        self.item(row, 1).setText(start_text)
        self.item(row, 2).setText(end_text)

        id_item = self.item(row, 0)
        if id_item:
            data = dict(id_item.data(Qt.ItemDataRole.UserRole) or {})
            data["start"] = start_text
            data["end"] = end_text
            id_item.setData(Qt.ItemDataRole.UserRole, data)

        return self.to_cut_items()[row]

    def remove_selected_rows(self) -> int:
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            self.removeRow(row)
        return len(rows)


class RangeTimeline(QWidget):
    seekRequested = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration_ms = 0
        self._position_ms = 0
        self._in_ms = 0
        self._out_ms = 0
        self.setMinimumHeight(58)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_duration(self, duration_ms: int) -> None:
        self._duration_ms = max(0, int(duration_ms))
        if self._duration_ms <= 0:
            self._position_ms = 0
            self._in_ms = 0
            self._out_ms = 0
        else:
            self._position_ms = min(self._position_ms, self._duration_ms)
            self._in_ms = min(self._in_ms, self._duration_ms)
            self._out_ms = min(max(self._out_ms, self._in_ms), self._duration_ms)
        self.update()

    def set_position(self, position_ms: int) -> None:
        self._position_ms = self._clamp_ms(position_ms)
        self.update()

    def set_range(self, in_ms: int, out_ms: int) -> None:
        self._in_ms = self._clamp_ms(in_ms)
        self._out_ms = self._clamp_ms(max(out_ms, in_ms))
        self.update()

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._seek_from_x(int(event.position().x()))

    def mouseMoveEvent(self, event: Any) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._seek_from_x(int(event.position().x()))

    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        track = self.rect().adjusted(12, 20, -12, -18)
        track.setHeight(14)
        radius = 7

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2f3b4e"))
        painter.drawRoundedRect(track, radius, radius)

        if self._duration_ms <= 0:
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Import video untuk mulai cut visual")
            return

        in_x = self._x_for_ms(self._in_ms, track.left(), track.width())
        out_x = self._x_for_ms(self._out_ms, track.left(), track.width())
        pos_x = self._x_for_ms(self._position_ms, track.left(), track.width())

        selection_width = max(4, out_x - in_x)
        selection = track.adjusted(in_x - track.left(), -2, -(track.right() - out_x), 2)
        selection.setWidth(selection_width)
        painter.setBrush(QColor("#2563eb"))
        painter.drawRoundedRect(selection, radius, radius)

        painter.setBrush(QColor("#e5e7eb"))
        for handle_x in (in_x, out_x):
            painter.drawRoundedRect(handle_x - 3, track.top() - 6, 6, track.height() + 12, 3, 3)

        pen = QPen(QColor("#f97316"), 2)
        painter.setPen(pen)
        painter.drawLine(pos_x, track.top() - 10, pos_x, track.bottom() + 10)

        painter.setPen(QColor("#cbd5e1"))
        painter.drawText(12, self.height() - 4, format_duration(self._in_ms / 1000))
        painter.drawText(
            self.width() - 92,
            self.height() - 4,
            format_duration(self._out_ms / 1000),
        )

    def _seek_from_x(self, x: int) -> None:
        if self._duration_ms <= 0:
            return
        track = self.rect().adjusted(12, 20, -12, -18)
        ratio = (x - track.left()) / max(1, track.width())
        self.seekRequested.emit(self._clamp_ms(round(ratio * self._duration_ms)))

    def _x_for_ms(self, value_ms: int, left: int, width: int) -> int:
        ratio = self._clamp_ms(value_ms) / max(1, self._duration_ms)
        return left + round(width * ratio)

    def _clamp_ms(self, value_ms: int) -> int:
        if self._duration_ms <= 0:
            return 0
        return max(0, min(int(value_ms), self._duration_ms))


class RoughCutRangeSelector(QWidget):
    rangeChanged = pyqtSignal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration = 0.0
        self._start = 0.0
        self._end = 0.0
        self._drag_mode = ""
        self._drag_offset = 0.0
        self.setMinimumHeight(92)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def selected_range(self) -> tuple[float, float]:
        return self._start, self._end

    def duration_seconds(self) -> float:
        return self._duration

    def set_duration(self, duration_seconds: float) -> None:
        previous_duration = self._duration
        self._duration = max(0.0, float(duration_seconds or 0.0))
        if self._duration <= 0:
            self._start = 0.0
            self._end = 0.0
        elif previous_duration <= 0 or self._end <= 0:
            self._start = 0.0
            self._end = self._duration
        else:
            self._start = min(max(0.0, self._start), self._duration)
            self._end = min(max(self._start + self._minimum_gap(), self._end), self._duration)
        self.update()
        self.rangeChanged.emit(self._start, self._end)

    def set_range(self, start_seconds: float, end_seconds: float) -> None:
        if self._duration <= 0:
            self._start = 0.0
            self._end = 0.0
        else:
            start = min(max(0.0, float(start_seconds or 0.0)), self._duration)
            end = min(max(start + self._minimum_gap(), float(end_seconds or 0.0)), self._duration)
            if end <= start:
                end = min(self._duration, start + self._minimum_gap())
                start = max(0.0, end - self._minimum_gap())
            self._start = start
            self._end = end
        self.update()
        self.rangeChanged.emit(self._start, self._end)

    def mousePressEvent(self, event: Any) -> None:
        if self._duration <= 0 or event.button() != Qt.MouseButton.LeftButton:
            return

        seconds = self._seconds_from_x(int(event.position().x()))
        start_x = self._x_for_seconds(self._start)
        end_x = self._x_for_seconds(self._end)
        x = int(event.position().x())

        if abs(x - start_x) <= 12:
            self._drag_mode = "start"
        elif abs(x - end_x) <= 12:
            self._drag_mode = "end"
        elif self._start <= seconds <= self._end:
            self._drag_mode = "move"
            self._drag_offset = seconds - self._start
        else:
            self._drag_mode = "start" if seconds < self._start else "end"
            self._set_drag_position(seconds)

    def mouseMoveEvent(self, event: Any) -> None:
        if not self._drag_mode:
            return
        self._set_drag_position(self._seconds_from_x(int(event.position().x())))

    def mouseReleaseEvent(self, event: Any) -> None:
        self._drag_mode = ""
        self._drag_offset = 0.0

    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        track = self._track_rect()
        radius = 8
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2f3b4e"))
        painter.drawRoundedRect(track, radius, radius)

        if self._duration <= 0:
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Import video untuk memilih range rough cut")
            return

        start_x = self._x_for_seconds(self._start)
        end_x = self._x_for_seconds(self._end)
        selection = track.adjusted(start_x - track.left(), -3, -(track.right() - end_x), 3)
        painter.setBrush(QColor("#2563eb"))
        painter.drawRoundedRect(selection, radius, radius)

        painter.setBrush(QColor("#f8fafc"))
        for handle_x in (start_x, end_x):
            painter.drawRoundedRect(handle_x - 4, track.top() - 9, 8, track.height() + 18, 4, 4)

        painter.setPen(QColor("#cbd5e1"))
        painter.drawText(12, 22, "Source range")
        painter.drawText(
            self.width() - 280,
            22,
            f"{format_duration(self._start)} - {format_duration(self._end)}",
        )
        painter.drawText(track.left(), self.height() - 8, format_duration(self._start))
        end_text = format_duration(self._end)
        painter.drawText(track.right() - 90, self.height() - 8, end_text)

    def _set_drag_position(self, seconds: float) -> None:
        seconds = min(max(0.0, seconds), self._duration)
        gap = self._minimum_gap()
        if self._drag_mode == "start":
            self._start = min(seconds, self._end - gap)
        elif self._drag_mode == "end":
            self._end = max(seconds, self._start + gap)
        elif self._drag_mode == "move":
            length = max(gap, self._end - self._start)
            new_start = min(max(0.0, seconds - self._drag_offset), max(0.0, self._duration - length))
            self._start = new_start
            self._end = min(self._duration, new_start + length)
        self.update()
        self.rangeChanged.emit(self._start, self._end)

    def _seconds_from_x(self, x: int) -> float:
        track = self._track_rect()
        ratio = (x - track.left()) / max(1, track.width())
        return min(max(0.0, ratio), 1.0) * self._duration

    def _x_for_seconds(self, seconds: float) -> int:
        track = self._track_rect()
        ratio = min(max(0.0, seconds / max(0.001, self._duration)), 1.0)
        return track.left() + round(track.width() * ratio)

    def _track_rect(self) -> Any:
        track = self.rect().adjusted(12, 38, -12, -28)
        track.setHeight(16)
        return track

    def _minimum_gap(self) -> float:
        return min(60.0, max(1.0, self._duration / 200)) if self._duration > 0 else 1.0


class VideoCutEditorWidget(QWidget):
    addClipRequested = pyqtSignal(float, float, str)
    updateClipRequested = pyqtSignal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._video_path = ""
        self._duration_ms = 0
        self._position_ms = 0
        self._range_preview = False
        self._syncing_range = False

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.65)
        self.player.setAudioOutput(self.audio_output)

        self.video_widget = QVideoWidget()
        self.video_widget.setObjectName("VideoPreview")
        self.video_widget.setMinimumSize(420, 220)
        self.video_widget.setMaximumHeight(340)
        self.video_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.player.setVideoOutput(self.video_widget)

        self.file_label = QLabel("No video loaded")
        self.file_label.setObjectName("PanelTitle")
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.play_button = QToolButton()
        self.play_button.setObjectName("TransportButton")
        self.play_button.setToolTip("Play / pause preview")
        self.back_button = QToolButton()
        self.back_button.setObjectName("TransportButton")
        self.back_button.setToolTip("Mundur 1 detik")
        self.forward_button = QToolButton()
        self.forward_button.setObjectName("TransportButton")
        self.forward_button.setToolTip("Maju 1 detik")

        style = self.style()
        self.play_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.back_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaSeekBackward))
        self.forward_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaSeekForward))

        for button in (self.play_button, self.back_button, self.forward_button):
            button.setIconSize(QSize(18, 18))
            button.setFixedSize(36, 34)

        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.time_label = QLabel("00:00.000 / 00:00.000")
        self.time_label.setMinimumWidth(170)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.timeline = RangeTimeline()

        self.in_spin = QDoubleSpinBox()
        self.out_spin = QDoubleSpinBox()
        for spin in (self.in_spin, self.out_spin):
            spin.setDecimals(3)
            spin.setRange(0.0, 0.0)
            spin.setSingleStep(0.1)
            spin.setSuffix(" sec")
            spin.setMinimumHeight(32)

        self.mark_in_button = QPushButton("Mark In")
        self.mark_out_button = QPushButton("Mark Out")
        self.preview_range_button = QPushButton("Preview Range")
        self.add_clip_button = QPushButton("Add Cut")
        self.apply_clip_button = QPushButton("Apply to Selected")
        self.add_clip_button.setObjectName("PrimaryButton")

        self._build_layout()
        self._connect_signals()
        self.set_video("", 0.0)

    def set_video(self, video_path: str, duration_seconds: float | None = None) -> None:
        self._video_path = video_path
        self._range_preview = False
        self.player.stop()

        if not video_path:
            self.player.setSource(QUrl())
            self.file_label.setText("No video loaded")
            self.status_label.setText("Import video untuk membuka editor visual")
            self._set_duration_ms(0)
            self._set_enabled(False)
            return

        source = Path(video_path)
        self.file_label.setText(source.name)
        self.status_label.setText(str(source))
        self.player.setSource(QUrl.fromLocalFile(str(source)))
        self._set_enabled(True)

        duration_ms = int(round(max(0.0, float(duration_seconds or 0.0)) * 1000))
        self._set_duration_ms(duration_ms)
        default_out = min(5.0, self.duration_seconds()) if self.duration_seconds() else 0.0
        self.set_clip_range(0.0, default_out, seek=True)

    def set_clip_range(self, start: float, end: float, seek: bool = False) -> None:
        duration = self.duration_seconds()
        start = max(0.0, float(start or 0.0))
        end = max(start, float(end or 0.0))
        if duration > 0:
            start = min(start, duration)
            end = min(max(end, start), duration)
        if duration > 0 and end <= start:
            end = min(duration, start + 0.1)

        self._syncing_range = True
        self.in_spin.setValue(start)
        self.out_spin.setValue(end)
        self._syncing_range = False
        self.timeline.set_range(round(start * 1000), round(end * 1000))

        if seek:
            self.seek_to_ms(round(start * 1000))

    def duration_seconds(self) -> float:
        return max(0.0, self._duration_ms / 1000)

    def seek_to_ms(self, position_ms: int) -> None:
        if self._duration_ms <= 0:
            return
        position_ms = max(0, min(int(position_ms), self._duration_ms))
        self.player.setPosition(position_ms)
        self._on_position_changed(position_ms)

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(self.file_label, 1)
        header.addWidget(self.status_label, 1)

        transport = QHBoxLayout()
        transport.addWidget(self.back_button)
        transport.addWidget(self.play_button)
        transport.addWidget(self.forward_button)
        transport.addWidget(self.position_slider, 1)
        transport.addWidget(self.time_label)

        range_panel = QFrame()
        range_panel.setObjectName("EditorPanel")
        range_layout = QGridLayout(range_panel)
        range_layout.setContentsMargins(12, 12, 12, 12)
        range_layout.setHorizontalSpacing(10)
        range_layout.setVerticalSpacing(8)
        range_layout.addWidget(QLabel("Start"), 0, 0)
        range_layout.addWidget(self.in_spin, 0, 1)
        range_layout.addWidget(QLabel("End"), 0, 2)
        range_layout.addWidget(self.out_spin, 0, 3)
        range_layout.addWidget(self.mark_in_button, 1, 0)
        range_layout.addWidget(self.mark_out_button, 1, 1)
        range_layout.addWidget(self.preview_range_button, 1, 2)
        range_layout.addWidget(self.add_clip_button, 1, 3)
        range_layout.addWidget(self.apply_clip_button, 1, 4)
        range_layout.addWidget(self.timeline, 2, 0, 1, 6)
        range_layout.setColumnStretch(5, 1)

        layout.addLayout(header)
        layout.addWidget(self.video_widget, 1)
        layout.addLayout(transport)
        layout.addWidget(range_panel)

    def _connect_signals(self) -> None:
        self.play_button.clicked.connect(self._toggle_playback)
        self.back_button.clicked.connect(lambda: self.seek_to_ms(self._position_ms - 1000))
        self.forward_button.clicked.connect(lambda: self.seek_to_ms(self._position_ms + 1000))
        self.position_slider.sliderMoved.connect(self.seek_to_ms)
        self.timeline.seekRequested.connect(self.seek_to_ms)
        self.in_spin.valueChanged.connect(self._range_spin_changed)
        self.out_spin.valueChanged.connect(self._range_spin_changed)
        self.mark_in_button.clicked.connect(self._mark_in)
        self.mark_out_button.clicked.connect(self._mark_out)
        self.preview_range_button.clicked.connect(self._preview_range)
        self.add_clip_button.clicked.connect(self._emit_add_clip)
        self.apply_clip_button.clicked.connect(self._emit_update_clip)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.playbackStateChanged.connect(self._sync_play_button)
        self.player.errorOccurred.connect(self._on_playback_error)

    def _set_enabled(self, enabled: bool) -> None:
        for widget in [
            self.video_widget,
            self.play_button,
            self.back_button,
            self.forward_button,
            self.position_slider,
            self.in_spin,
            self.out_spin,
            self.mark_in_button,
            self.mark_out_button,
            self.preview_range_button,
            self.add_clip_button,
            self.apply_clip_button,
        ]:
            widget.setEnabled(enabled)

    def _set_duration_ms(self, duration_ms: int) -> None:
        self._duration_ms = max(0, int(duration_ms))
        max_seconds = self.duration_seconds()
        self.position_slider.setRange(0, self._duration_ms)
        for spin in (self.in_spin, self.out_spin):
            spin.setRange(0.0, max_seconds)
        self.timeline.set_duration(self._duration_ms)
        self._on_position_changed(min(self._position_ms, self._duration_ms))

    def _on_position_changed(self, position_ms: int) -> None:
        self._position_ms = max(0, min(int(position_ms), max(0, self._duration_ms)))
        self.position_slider.blockSignals(True)
        self.position_slider.setValue(self._position_ms)
        self.position_slider.blockSignals(False)
        self.timeline.set_position(self._position_ms)
        self.time_label.setText(
            f"{format_duration(self._position_ms / 1000)} / {format_duration(self.duration_seconds())}"
        )

        if self._range_preview and self._position_ms >= round(self.out_spin.value() * 1000):
            self._range_preview = False
            self.player.pause()
            self.seek_to_ms(round(self.out_spin.value() * 1000))

    def _on_duration_changed(self, duration_ms: int) -> None:
        if duration_ms <= 0:
            return
        old_duration = self._duration_ms
        self._set_duration_ms(duration_ms)
        if old_duration <= 0:
            self.set_clip_range(0.0, min(5.0, self.duration_seconds()), seek=False)

    def _on_playback_error(self, error: QMediaPlayer.Error, error_string: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        self.status_label.setText(error_string or "Preview tidak bisa diputar di sistem ini")

    def _sync_play_button(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause)
        else:
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        self.play_button.setIcon(icon)

    def _toggle_playback(self) -> None:
        if not self._video_path:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._range_preview = False
            self.player.pause()
        else:
            self._range_preview = False
            self.player.play()

    def _mark_in(self) -> None:
        current = self._position_ms / 1000
        self.set_clip_range(current, max(self.out_spin.value(), current + 0.1), seek=False)

    def _mark_out(self) -> None:
        current = self._position_ms / 1000
        self.set_clip_range(min(self.in_spin.value(), current - 0.1), current, seek=False)

    def _preview_range(self) -> None:
        if not self._video_path or self.out_spin.value() <= self.in_spin.value():
            return
        self._range_preview = True
        self.seek_to_ms(round(self.in_spin.value() * 1000))
        self.player.play()

    def _range_spin_changed(self) -> None:
        if self._syncing_range:
            return
        self.set_clip_range(self.in_spin.value(), self.out_spin.value(), seek=False)

    def _emit_add_clip(self) -> None:
        start, end = self._range_seconds()
        if end <= start:
            return
        label = f"Visual cut {format_duration(start)} - {format_duration(end)}"
        self.addClipRequested.emit(start, end, label)

    def _emit_update_clip(self) -> None:
        start, end = self._range_seconds()
        if end <= start:
            return
        self.updateClipRequested.emit(start, end)

    def _range_seconds(self) -> tuple[float, float]:
        return float(self.in_spin.value()), float(self.out_spin.value())


class SceneNotesTable(QTableWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHorizontalHeaderLabels(["Frame", "Time", "Visual Note"])
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.verticalHeader().setVisible(False)
        self.setIconSize(QSize(160, 90))
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

    def set_scene_notes(self, notes: list[dict[str, Any]]) -> None:
        self.blockSignals(True)
        self.setRowCount(len(notes))

        for row, note in enumerate(notes):
            data = dict(note)
            timestamp = float(data.get("timestamp", 0.0) or 0.0)
            image_path = str(data.get("image_path") or "")

            frame_item = _readonly_item("")
            frame_item.setData(Qt.ItemDataRole.UserRole, data)
            pixmap = _thumbnail_pixmap(image_path)
            if pixmap:
                frame_item.setData(Qt.ItemDataRole.DecorationRole, pixmap)
            self.setItem(row, 0, frame_item)
            self.setItem(row, 1, _readonly_item(format_duration(timestamp)))
            self.setItem(row, 2, QTableWidgetItem(str(data.get("note") or "")))
            self.setRowHeight(row, 96)

        self.blockSignals(False)

    def to_scene_notes(self) -> list[dict[str, Any]]:
        notes: list[dict[str, Any]] = []
        for row in range(self.rowCount()):
            frame_item = self.item(row, 0)
            base = dict(frame_item.data(Qt.ItemDataRole.UserRole) or {}) if frame_item else {}
            time_item = self.item(row, 1)
            note_item = self.item(row, 2)

            try:
                base["timestamp"] = parse_timestamp(time_item.text()) if time_item else 0.0
            except (TypeError, ValueError):
                base["timestamp"] = float(base.get("timestamp", 0.0) or 0.0)

            base["image_path"] = str(base.get("image_path") or "")
            base["note"] = note_item.text().strip() if note_item else ""
            notes.append(base)
        return notes


class ChecklistWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checks: list[QCheckBox] = []

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Transformative content checklist. This is planning guidance only, not legal advice."
            )
        )

        for text in DEFAULT_CHECKLIST_ITEMS:
            checkbox = QCheckBox(text)
            self._checks.append(checkbox)
            layout.addWidget(checkbox)

        layout.addStretch(1)

    def states(self) -> list[dict[str, Any]]:
        return [{"text": check.text(), "checked": check.isChecked()} for check in self._checks]

    def set_states(self, states: list[dict[str, Any]]) -> None:
        saved = {str(item.get("text")): bool(item.get("checked")) for item in states or []}
        for check in self._checks:
            check.setChecked(saved.get(check.text(), False))


class LogPanel(QTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)

    def append_message(self, message: str) -> str:
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        self.append(line)
        return line

    def set_messages(self, messages: list[str]) -> None:
        self.clear()
        for message in messages:
            self.append(message)


def _readonly_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


def _thumbnail_pixmap(image_path: str) -> QPixmap | None:
    path = Path(image_path)
    if not path.exists():
        return None

    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None
    return pixmap.scaled(
        160,
        90,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _to_dict(record: Any) -> dict[str, Any]:
    if hasattr(record, "to_dict"):
        return dict(record.to_dict())
    if isinstance(record, dict):
        return dict(record)
    return {
        "id": getattr(record, "id", ""),
        "start": getattr(record, "start", 0.0),
        "end": getattr(record, "end", 0.0),
        "text": getattr(record, "text", ""),
    }


def _display_time(value: Any) -> str:
    try:
        return format_duration(parse_timestamp(value))
    except (TypeError, ValueError):
        return str(value)
