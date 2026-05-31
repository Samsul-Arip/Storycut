from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QItemSelectionModel, QMimeData, QSize, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QIcon, QPainter, QPen, QPixmap
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
    QScrollBar,
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

from app.core.audio_utils import read_audio_waveform
from app.core.video_utils import format_duration, parse_timestamp


CLIP_MIME_TYPE = "application/x-storycut-clip"


DEFAULT_CHECKLIST_ITEMS = [
    "I am adding original commentary, criticism, analysis, or explanation.",
    "I am using only the clips needed to support the review or storytelling point.",
    "No Video Ori clip is longer than five seconds.",
    "I am not presenting long uninterrupted portions as a substitute for the original work.",
    "I replaced copied subtitles/dialogue with my own narration or paraphrased script.",
    "I removed Video Ori audio unless a short excerpt is necessary for commentary.",
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


class ManualClipTable(QTableWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(4)
        self.setHorizontalHeaderLabels(["Clip", "Dur", "Timestamp", "Note"])
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        self.setAlternatingRowColors(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalHeader().setVisible(False)
        self.setIconSize(QSize(80, 45))
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

    def set_manual_clips(self, items: list[dict[str, Any]]) -> None:
        self.blockSignals(True)
        self.setRowCount(len(items))
        for row, item in enumerate(items):
            data = dict(item)
            clip_id = str(data.get("id") or f"manual_{row + 1:03d}")
            start = parse_timestamp(data.get("start", 0.0))
            end = parse_timestamp(data.get("end", start))
            is_photo = _is_photo_clip(data)
            output_duration = _clip_output_duration(data, start, end)

            clip_item = _readonly_item(f"[Photo] {clip_id}" if is_photo else clip_id)
            clip_item.setData(Qt.ItemDataRole.UserRole, data)
            thumbnail = _thumbnail_icon(data)
            if thumbnail:
                clip_item.setIcon(thumbnail)
            self.setItem(row, 0, clip_item)
            self.setItem(
                row,
                1,
                _readonly_item(format_duration(output_duration) if is_photo else _duration_text(start, end)),
            )
            self.setItem(
                row,
                2,
                _readonly_item(format_duration(start) if is_photo else f"{format_duration(start)} - {format_duration(end)}"),
            )
            self.setItem(row, 3, QTableWidgetItem(str(data.get("text", ""))))
        self.blockSignals(False)
        self.resizeRowsToContents()

    def manual_clips(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for row in range(self.rowCount()):
            id_item = self.item(row, 0)
            base = dict(id_item.data(Qt.ItemDataRole.UserRole) or {}) if id_item else {}
            item_id = id_item.text().strip() if id_item else f"manual_{row + 1:03d}"
            base["id"] = item_id.removeprefix("[Photo] ").strip()
            if self.item(row, 3):
                base["text"] = self.item(row, 3).text().strip()
            items.append(base)
        return items

    def selected_manual_clips(self) -> list[dict[str, Any]]:
        all_items = self.manual_clips()
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()})
        return [all_items[row] for row in rows if 0 <= row < len(all_items)]

    def update_first_selected_range(self, start: float, end: float) -> dict[str, Any] | None:
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()})
        if not rows:
            return None
        row = rows[0]
        id_item = self.item(row, 0)
        data = dict(id_item.data(Qt.ItemDataRole.UserRole) or {}) if id_item else {}
        data["start"] = format_duration(start)
        data["end"] = format_duration(end)
        if id_item:
            id_item.setData(Qt.ItemDataRole.UserRole, data)
        self.item(row, 1).setText(_duration_text(start, end))
        self.item(row, 2).setText(f"{format_duration(start)} - {format_duration(end)}")
        return self.manual_clips()[row]

    def remove_selected_rows(self) -> int:
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            self.removeRow(row)
        return len(rows)

    def set_cut_items(self, items: list[dict[str, Any]]) -> None:
        self.set_manual_clips(items)

    def to_cut_items(self) -> list[dict[str, Any]]:
        return self.manual_clips()

    def selected_cut_items(self) -> list[dict[str, Any]]:
        return self.selected_manual_clips()

    def startDrag(self, supported_actions: Qt.DropAction) -> None:
        clips = self.selected_manual_clips()
        if not clips:
            return
        mime = QMimeData()
        mime.setData(
            CLIP_MIME_TYPE,
            json.dumps({"origin": "manual", "clips": clips}).encode("utf-8"),
        )
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class TimelineClipTable(QTableWidget):
    timelineChanged = pyqtSignal()
    clipActivated = pyqtSignal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._zoom = 1.0
        self.setColumnCount(7)
        self.setHorizontalHeaderLabels(
            ["#", "Clip", "Thumbnail", "Start", "End", "Duration", "Text"]
        )
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setIconSize(QSize(112, 63))
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.itemSelectionChanged.connect(self._emit_selected_clip)
        self.itemChanged.connect(self._on_item_changed)

    def set_timeline_clips(self, items: list[dict[str, Any]]) -> None:
        self.blockSignals(True)
        self.setRowCount(len(items))
        for row, item in enumerate(items):
            data = dict(item)
            clip_id = str(data.get("id") or data.get("timeline_id") or f"tl_{row + 1:03d}")
            start = parse_timestamp(data.get("start", 0.0))
            end = parse_timestamp(data.get("end", start))
            output_duration = _clip_output_duration(data, start, end)
            is_photo = _is_photo_clip(data)

            number_item = _readonly_item(str(row + 1))
            clip_item = _readonly_item(f"[Photo] {clip_id}" if is_photo else clip_id)
            clip_item.setData(Qt.ItemDataRole.UserRole, data)
            thumb_item = _readonly_item("")
            thumbnail = _thumbnail_icon(data)
            if thumbnail:
                thumb_item.setIcon(thumbnail)

            self.setItem(row, 0, number_item)
            self.setItem(row, 1, clip_item)
            self.setItem(row, 2, thumb_item)
            self.setItem(row, 3, QTableWidgetItem(format_duration(start)))
            self.setItem(row, 4, QTableWidgetItem("Photo" if is_photo else format_duration(end)))
            self.setItem(row, 5, _readonly_item(format_duration(output_duration)))
            self.setItem(row, 6, QTableWidgetItem(str(data.get("text", ""))))
            self.setRowHeight(row, int(62 * self._zoom))
        self.blockSignals(False)
        self.resizeColumnsToContents()
        self.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)

    def timeline_clips(self) -> list[dict[str, Any]]:
        clips: list[dict[str, Any]] = []
        for row in range(self.rowCount()):
            clip_item = self.item(row, 1)
            base = dict(clip_item.data(Qt.ItemDataRole.UserRole) or {}) if clip_item else {}
            item_id = clip_item.text().strip() if clip_item else f"tl_{row + 1:03d}"
            base["id"] = item_id.removeprefix("[Photo] ").strip()
            if self.item(row, 3):
                base["start"] = self.item(row, 3).text().strip()
            if self.item(row, 4) and not _is_photo_clip(base):
                base["end"] = self.item(row, 4).text().strip()
            if self.item(row, 6):
                base["text"] = self.item(row, 6).text().strip()
            clips.append(base)
        return clips

    def selected_timeline_clip(self) -> dict[str, Any] | None:
        row = self.currentRow()
        clips = self.timeline_clips()
        if row < 0 or row >= len(clips):
            return None
        return clips[row]

    def remove_selected_rows(self) -> int:
        clips = self.timeline_clips()
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            if 0 <= row < len(clips):
                clips.pop(row)
        if not rows:
            return 0
        self.set_timeline_clips(clips)
        self.timelineChanged.emit()
        return len(rows)

    def split_selected_clip(self) -> bool:
        row = self.currentRow()
        clips = self.timeline_clips()
        if row < 0 or row >= len(clips):
            return False
        clip = dict(clips[row])
        start = parse_timestamp(clip.get("start", 0.0))
        end = parse_timestamp(clip.get("end", 0.0))
        if end - start < 0.2:
            return False
        middle = start + ((end - start) / 2)
        output_duration = _clip_output_duration(clip, start, end)
        first = dict(clip)
        second = dict(clip)
        first["id"] = f"{clip.get('id', 'clip')}_A"
        first["end"] = format_duration(middle)
        first["text"] = f"{clip.get('text', '')} (part A)".strip()
        first["output_duration"] = round(output_duration / 2, 3)
        second["id"] = f"{clip.get('id', 'clip')}_B"
        second["start"] = format_duration(middle)
        second["text"] = f"{clip.get('text', '')} (part B)".strip()
        second["output_duration"] = round(output_duration / 2, 3)
        clips[row : row + 1] = [first, second]
        self.set_timeline_clips(clips)
        self.selectRow(row)
        self.timelineChanged.emit()
        return True

    def update_selected_range(self, start: float, end: float) -> dict[str, Any] | None:
        row = self.currentRow()
        clips = self.timeline_clips()
        if row < 0 or row >= len(clips):
            return None
        clips[row]["start"] = format_duration(start)
        clips[row]["end"] = format_duration(end)
        if clips[row].get("kind") != "rough":
            clips[row]["output_duration"] = round(max(0.1, end - start), 3)
        self.set_timeline_clips(clips)
        self.selectRow(row)
        self.timelineChanged.emit()
        return clips[row]

    def append_clips(self, clips_to_add: list[dict[str, Any]], insert_at: int | None = None) -> None:
        clips = self.timeline_clips()
        if insert_at is None:
            insert_at = len(clips)
        insert_at = min(max(0, int(insert_at)), len(clips))
        incoming = [_timeline_copy(clip, index) for index, clip in enumerate(clips_to_add, start=1)]
        for offset, clip in enumerate(incoming):
            clips.insert(insert_at + offset, clip)
        self.set_timeline_clips(clips)
        if incoming:
            self._select_rows(list(range(insert_at, insert_at + len(incoming))))
        self.timelineChanged.emit()

    def insertion_row_after_selection(self) -> int:
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()})
        if rows:
            return min(self.rowCount(), rows[-1] + 1)
        current = self.currentRow()
        if current >= 0:
            return min(self.rowCount(), current + 1)
        return self.rowCount()

    def move_selected_rows(self, direction: int) -> bool:
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()})
        clips = self.timeline_clips()
        if not rows or not clips:
            return False
        if direction < 0:
            if rows[0] <= 0:
                return False
            for row in rows:
                clips[row - 1], clips[row] = clips[row], clips[row - 1]
            new_rows = [row - 1 for row in rows]
        else:
            if rows[-1] >= len(clips) - 1:
                return False
            for row in reversed(rows):
                clips[row + 1], clips[row] = clips[row], clips[row + 1]
            new_rows = [row + 1 for row in rows]
        self.set_timeline_clips(clips)
        self._select_rows(new_rows)
        self.timelineChanged.emit()
        return True

    def move_selected_rows_to_edge(self, top: bool) -> bool:
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()})
        clips = self.timeline_clips()
        if not rows or not clips:
            return False
        selected = [clips[row] for row in rows if 0 <= row < len(clips)]
        remaining = [clip for index, clip in enumerate(clips) if index not in set(rows)]
        if top:
            new_clips = selected + remaining
            new_rows = list(range(len(selected)))
        else:
            new_clips = remaining + selected
            start = len(remaining)
            new_rows = list(range(start, start + len(selected)))
        if new_clips == clips:
            return False
        self.set_timeline_clips(new_clips)
        self._select_rows(new_rows)
        self.timelineChanged.emit()
        return True

    def move_selected_rows_to_position(self, position: int) -> bool:
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()})
        clips = self.timeline_clips()
        if not rows or not clips:
            return False
        row_set = set(rows)
        selected = [clips[row] for row in rows if 0 <= row < len(clips)]
        remaining = [clip for index, clip in enumerate(clips) if index not in row_set]
        if not selected:
            return False

        insert_at = min(max(0, int(position) - 1), len(remaining))
        new_clips = remaining[:insert_at] + selected + remaining[insert_at:]
        if new_clips == clips:
            return False

        new_rows = list(range(insert_at, insert_at + len(selected)))
        self.set_timeline_clips(new_clips)
        self._select_rows(new_rows)
        self.timelineChanged.emit()
        return True

    def apply_effects_to_selected(
        self,
        zoom_percent: float,
        slowmo_factor: float,
        photo_duration: float | None = None,
    ) -> int:
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()})
        clips = self.timeline_clips()
        if not rows or not clips:
            return 0

        changed = 0
        for row in rows:
            if row < 0 or row >= len(clips):
                continue
            clip = dict(clips[row])
            zoom = max(100.0, float(zoom_percent or 100.0))
            slowmo = max(1.0, float(slowmo_factor or 1.0))

            if zoom > 100.01:
                clip["zoom_percent"] = round(zoom, 3)
            else:
                clip.pop("zoom_percent", None)
                clip.pop("effect_zoom_percent", None)

            if _is_photo_clip(clip):
                clip.pop("slowmo_factor", None)
                clip.pop("effect_slowmo_factor", None)
                if photo_duration is not None:
                    clip["output_duration"] = round(max(0.1, float(photo_duration or 3.0)), 3)
            elif slowmo > 1.001:
                clip["slowmo_factor"] = round(slowmo, 3)
                start = parse_timestamp(clip.get("start", 0.0))
                end = parse_timestamp(clip.get("end", start))
                clip["output_duration"] = round(max(0.1, end - start) * slowmo, 3)
            else:
                had_slowmo = "slowmo_factor" in clip or "effect_slowmo_factor" in clip
                clip.pop("slowmo_factor", None)
                clip.pop("effect_slowmo_factor", None)
                if had_slowmo:
                    start = parse_timestamp(clip.get("start", 0.0))
                    end = parse_timestamp(clip.get("end", start))
                    clip["output_duration"] = round(max(0.1, end - start), 3)

            clips[row] = clip
            changed += 1

        if not changed:
            return 0
        self.set_timeline_clips(clips)
        self._select_rows(rows)
        self.timelineChanged.emit()
        return changed

    def _select_rows(self, rows: list[int]) -> None:
        self.clearSelection()
        selection_model = self.selectionModel()
        valid_rows = [row for row in rows if 0 <= row < self.rowCount()]
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        for row in valid_rows:
            selection_model.select(self.model().index(row, 0), flags)
        if valid_rows:
            selection_model.setCurrentIndex(
                self.model().index(valid_rows[0], 0),
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )

    def set_zoom(self, zoom: float) -> None:
        self._zoom = min(max(0.7, zoom), 2.2)
        self.setIconSize(QSize(int(112 * self._zoom), int(63 * self._zoom)))
        for row in range(self.rowCount()):
            self.setRowHeight(row, int(62 * self._zoom))

    def zoom(self) -> float:
        return self._zoom

    def startDrag(self, supported_actions: Qt.DropAction) -> None:
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()})
        clips = self.timeline_clips()
        selected = [clips[row] for row in rows if 0 <= row < len(clips)]
        if not selected:
            return
        mime = QMimeData()
        mime.setData(
            CLIP_MIME_TYPE,
            json.dumps({"origin": "timeline", "rows": rows, "clips": selected}).encode("utf-8"),
        )
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event: Any) -> None:
        if event.mimeData().hasFormat(CLIP_MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: Any) -> None:
        if event.mimeData().hasFormat(CLIP_MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: Any) -> None:
        if not event.mimeData().hasFormat(CLIP_MIME_TYPE):
            super().dropEvent(event)
            return
        payload = _decode_clip_payload(event.mimeData().data(CLIP_MIME_TYPE))
        if not payload:
            return

        target_row = self._drop_row(event)
        clips = self.timeline_clips()
        incoming = [dict(clip) for clip in payload.get("clips", [])]
        if payload.get("origin") == "timeline":
            rows = sorted(int(row) for row in payload.get("rows", []) if 0 <= int(row) < len(clips))
            moving = [clips[row] for row in rows]
            for row in reversed(rows):
                clips.pop(row)
            target_row -= sum(1 for row in rows if row < target_row)
            incoming = moving
        else:
            incoming = [_timeline_copy(clip, index) for index, clip in enumerate(incoming, start=1)]

        target_row = min(max(0, target_row), len(clips))
        for offset, clip in enumerate(incoming):
            clips.insert(target_row + offset, clip)
        self.set_timeline_clips(clips)
        if incoming:
            self.selectRow(target_row)
        self.timelineChanged.emit()
        event.acceptProposedAction()

    def _drop_row(self, event: Any) -> int:
        position = event.position().toPoint() if hasattr(event, "position") else event.pos()
        index = self.indexAt(position)
        return index.row() if index.isValid() else self.rowCount()

    def _emit_selected_clip(self) -> None:
        clip = self.selected_timeline_clip()
        if clip:
            self.clipActivated.emit(clip)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() in (3, 4):
            try:
                start = parse_timestamp(self.item(item.row(), 3).text())
                end = parse_timestamp(self.item(item.row(), 4).text())
                clip_item = self.item(item.row(), 1)
                data = dict(clip_item.data(Qt.ItemDataRole.UserRole) or {}) if clip_item else {}
                if data.get("kind") != "rough":
                    data["output_duration"] = round(max(0.1, end - start), 3)
                    if clip_item:
                        clip_item.setData(Qt.ItemDataRole.UserRole, data)
                output_duration = _clip_output_duration(data, start, end)
                self.blockSignals(True)
                self.item(item.row(), 5).setText(format_duration(output_duration))
                self.blockSignals(False)
            except (AttributeError, TypeError, ValueError):
                self.blockSignals(False)
        self.timelineChanged.emit()


class AudioWaveformWorker(QThread):
    succeeded = pyqtSignal(str, list)
    failed = pyqtSignal(str, str)

    def __init__(self, video_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._video_path = video_path

    def run(self) -> None:
        try:
            peaks = read_audio_waveform(self._video_path)
            self.succeeded.emit(self._video_path, peaks)
        except Exception as exc:
            self.failed.emit(self._video_path, str(exc))


class RangeTimeline(QWidget):
    seekRequested = pyqtSignal(int)
    rangeEdited = pyqtSignal(int, int)
    viewChanged = pyqtSignal(int, int, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration_ms = 0
        self._position_ms = 0
        self._in_ms = 0
        self._out_ms = 0
        self._view_start_ms = 0
        self._zoom = 1.0
        self._drag_mode = ""
        self._waveform_peaks: list[float] = []
        self._waveform_status = "Waveform audio akan muncul setelah video dimuat"
        self.setMinimumHeight(132)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(
            "Scroll di timeline untuk zoom, Shift+scroll untuk geser waktu, "
            "drag handle putih untuk mengatur In/Out."
        )

    def set_duration(self, duration_ms: int) -> None:
        self._duration_ms = max(0, int(duration_ms))
        if self._duration_ms <= 0:
            self._position_ms = 0
            self._in_ms = 0
            self._out_ms = 0
            self._view_start_ms = 0
            self._zoom = 1.0
        else:
            self._position_ms = min(self._position_ms, self._duration_ms)
            self._in_ms = min(self._in_ms, self._duration_ms)
            self._out_ms = min(max(self._out_ms, self._in_ms), self._duration_ms)
            self._zoom = min(max(1.0, self._zoom), self._max_zoom())
            self._view_start_ms = self._clamped_view_start(self._view_start_ms)
        self.update()
        self._emit_view_changed()

    def set_position(self, position_ms: int) -> None:
        self._position_ms = self._clamp_ms(position_ms)
        self._ensure_visible(self._position_ms)
        self.update()

    def set_range(self, in_ms: int, out_ms: int) -> None:
        self._in_ms = self._clamp_ms(in_ms)
        self._out_ms = self._clamp_ms(max(out_ms, in_ms))
        self.update()

    def set_waveform(self, peaks: list[float]) -> None:
        self._waveform_peaks = [min(1.0, max(0.0, float(peak))) for peak in peaks]
        self._waveform_status = (
            "Waveform audio siap" if self._waveform_peaks else "Waveform audio tidak tersedia"
        )
        self.update()

    def set_waveform_status(self, status: str) -> None:
        self._waveform_peaks = []
        self._waveform_status = status
        self.update()

    def set_zoom(self, zoom: float, anchor_ms: int | None = None) -> None:
        if self._duration_ms <= 0:
            return
        old_visible = self._visible_duration_ms()
        if anchor_ms is None:
            anchor_ms = self._view_start_ms + old_visible // 2
        anchor_ms = self._clamp_ms(anchor_ms)
        anchor_ratio = (anchor_ms - self._view_start_ms) / max(1, old_visible)

        self._zoom = min(max(1.0, float(zoom)), self._max_zoom())
        new_visible = self._visible_duration_ms()
        self._view_start_ms = self._clamped_view_start(
            round(anchor_ms - (new_visible * anchor_ratio))
        )
        self.update()
        self._emit_view_changed()

    def adjust_zoom(self, factor: float, anchor_ms: int | None = None) -> None:
        self.set_zoom(self._zoom * max(0.1, float(factor)), anchor_ms)

    def fit_to_duration(self) -> None:
        self.set_zoom(1.0)

    def zoom(self) -> float:
        return self._zoom

    def max_zoom(self) -> float:
        return self._max_zoom()

    def viewport_info(self) -> tuple[int, int, float]:
        return self._view_start_ms, self._visible_duration_ms(), self._zoom

    def set_view_start_ms(self, view_start_ms: int) -> None:
        if self._duration_ms <= 0:
            return
        next_start = self._clamped_view_start(view_start_ms)
        if next_start == self._view_start_ms:
            return
        self._view_start_ms = next_start
        self.update()
        self._emit_view_changed()

    def mousePressEvent(self, event: Any) -> None:
        if self._duration_ms <= 0 or event.button() != Qt.MouseButton.LeftButton:
            return
        x = int(event.position().x())
        self._drag_mode = self._handle_hit_test(x)
        if self._drag_mode in {"in", "out"}:
            self._edit_range_edge(self._drag_mode, self._ms_from_x(x))
            return
        self._drag_mode = "seek"
        self._seek_from_x(x)

    def mouseMoveEvent(self, event: Any) -> None:
        if self._duration_ms <= 0:
            return
        x = int(event.position().x())
        if self._drag_mode in {"in", "out"} and event.buttons() & Qt.MouseButton.LeftButton:
            self._edit_range_edge(self._drag_mode, self._ms_from_x(x))
        elif self._drag_mode == "seek" and event.buttons() & Qt.MouseButton.LeftButton:
            self._seek_from_x(x)

    def mouseReleaseEvent(self, event: Any) -> None:
        self._drag_mode = ""

    def wheelEvent(self, event: Any) -> None:
        if self._duration_ms <= 0:
            super().wheelEvent(event)
            return

        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return

        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            step = int(self._visible_duration_ms() * 0.18)
            direction = -1 if delta > 0 else 1
            self.set_view_start_ms(self._view_start_ms + (direction * step))
        else:
            factor = 1.3 if delta > 0 else 1 / 1.3
            self.adjust_zoom(factor, self._ms_from_x(int(event.position().x())))
        event.accept()

    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        track = self._track_rect()
        waveform_rect = track.adjusted(0, 24, 0, -12)

        painter.setPen(QPen(QColor("#263244"), 1))
        painter.setBrush(QColor("#0f172a"))
        painter.drawRoundedRect(track, 8, 8)

        if self._duration_ms <= 0:
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Import video untuk mulai cut visual")
            return

        self._draw_ruler(painter, track)
        self._draw_selection(painter, waveform_rect)
        self._draw_waveform(painter, waveform_rect)
        self._draw_handles_and_playhead(painter, waveform_rect)
        self._draw_footer(painter, track)

    def _seek_from_x(self, x: int) -> None:
        if self._duration_ms <= 0:
            return
        self.seekRequested.emit(self._ms_from_x(x))

    def _edit_range_edge(self, mode: str, value_ms: int) -> None:
        if mode == "in":
            self._in_ms = min(self._clamp_ms(value_ms), max(0, self._out_ms - 10))
        elif mode == "out":
            self._out_ms = max(self._clamp_ms(value_ms), min(self._duration_ms, self._in_ms + 10))
        self.update()
        self.rangeEdited.emit(self._in_ms, self._out_ms)

    def _handle_hit_test(self, x: int) -> str:
        track = self._track_rect()
        for mode, value in (("in", self._in_ms), ("out", self._out_ms)):
            handle_x = self._x_for_ms(value, track.left(), track.width())
            if abs(x - handle_x) <= 10:
                return mode
        return ""

    def _draw_ruler(self, painter: QPainter, track: Any) -> None:
        top = track.top() + 5
        visible_seconds = self._visible_duration_ms() / 1000.0
        target_step = visible_seconds / max(1, track.width() / 90)
        step = self._nice_tick_step(target_step)
        start_seconds = self._view_start_ms / 1000.0
        end_seconds = self._view_end_ms() / 1000.0
        first_tick = math.floor(start_seconds / step) * step

        painter.setPen(QPen(QColor("#334155"), 1))
        tick = first_tick
        while tick <= end_seconds + step:
            value_ms = round(tick * 1000)
            x = self._x_for_ms(value_ms, track.left(), track.width())
            if track.left() <= x <= track.right():
                painter.drawLine(x, top + 17, x, track.bottom() - 4)
                painter.setPen(QColor("#94a3b8"))
                tick_text = format_duration(tick)
                text_width = painter.fontMetrics().horizontalAdvance(tick_text)
                text_x = min(max(track.left() + 4, x + 4), track.right() - text_width - 4)
                painter.drawText(text_x, top + 12, tick_text)
                painter.setPen(QPen(QColor("#334155"), 1))
            tick += step

    def _draw_selection(self, painter: QPainter, rect: Any) -> None:
        start = max(self._in_ms, self._view_start_ms)
        end = min(self._out_ms, self._view_end_ms())
        if end <= start:
            return
        left = self._x_for_ms(start, rect.left(), rect.width())
        right = self._x_for_ms(end, rect.left(), rect.width())
        color = QColor("#1d4ed8")
        color.setAlpha(85)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRect(left, rect.top(), max(1, right - left), rect.height())

    def _draw_waveform(self, painter: QPainter, rect: Any) -> None:
        center_y = rect.center().y()
        painter.setPen(QPen(QColor("#334155"), 1))
        painter.drawLine(rect.left(), center_y, rect.right(), center_y)

        if not self._waveform_peaks:
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._waveform_status)
            return

        peak_count = len(self._waveform_peaks)
        half_height = max(2, rect.height() // 2 - 4)
        normal_pen = QPen(QColor("#60a5fa"), 1)
        selected_pen = QPen(QColor("#bfdbfe"), 1)
        for x in range(rect.left(), rect.right() + 1):
            start_ms = self._ms_from_x(x)
            end_ms = self._ms_from_x(x + 1)
            start_index = min(peak_count - 1, max(0, int(start_ms / max(1, self._duration_ms) * peak_count)))
            end_index = min(
                peak_count,
                max(start_index + 1, int(end_ms / max(1, self._duration_ms) * peak_count) + 1),
            )
            peak = max(self._waveform_peaks[start_index:end_index], default=0.0)
            line_height = max(1, round(peak * half_height))
            mid_ms = (start_ms + end_ms) // 2
            painter.setPen(selected_pen if self._in_ms <= mid_ms <= self._out_ms else normal_pen)
            painter.drawLine(x, center_y - line_height, x, center_y + line_height)

    def _draw_handles_and_playhead(self, painter: QPainter, rect: Any) -> None:
        for value_ms in (self._in_ms, self._out_ms):
            x = self._x_for_ms(value_ms, rect.left(), rect.width())
            if rect.left() - 8 <= x <= rect.right() + 8:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#f8fafc"))
                painter.drawRoundedRect(x - 4, rect.top() - 5, 8, rect.height() + 10, 4, 4)

        playhead_x = self._x_for_ms(self._position_ms, rect.left(), rect.width())
        if rect.left() - 2 <= playhead_x <= rect.right() + 2:
            painter.setPen(QPen(QColor("#f97316"), 2))
            painter.drawLine(playhead_x, rect.top() - 12, playhead_x, rect.bottom() + 12)

    def _draw_footer(self, painter: QPainter, track: Any) -> None:
        painter.setPen(QColor("#cbd5e1"))
        footer_top = self.height() - 24
        footer_height = 20
        painter.drawText(
            track.left(),
            footer_top,
            180,
            footer_height,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"In {format_duration(self._in_ms / 1000)}",
        )
        out_text = f"Out {format_duration(self._out_ms / 1000)}"
        painter.drawText(
            track.right() - 180,
            footer_top,
            180,
            footer_height,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            out_text,
        )
        view_text = (
            f"{format_duration(self._view_start_ms / 1000)} - "
            f"{format_duration(self._view_end_ms() / 1000)}"
        )
        painter.setPen(QColor("#94a3b8"))
        painter.drawText(
            track.left() + 2,
            track.top() + 2,
            max(120, track.width() - 100),
            18,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            view_text,
        )
        painter.drawText(
            track.right() - 90,
            track.top() + 2,
            88,
            18,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"{round(self._zoom * 100)}%",
        )

    def _track_rect(self) -> Any:
        return self.rect().adjusted(12, 8, -12, -24)

    def _ms_from_x(self, x: int) -> int:
        track = self._track_rect()
        ratio = (x - track.left()) / max(1, track.width())
        ratio = min(max(0.0, ratio), 1.0)
        return self._clamp_ms(round(self._view_start_ms + (ratio * self._visible_duration_ms())))

    def _x_for_ms(self, value_ms: int, left: int, width: int) -> int:
        ratio = (self._clamp_ms(value_ms) - self._view_start_ms) / max(1, self._visible_duration_ms())
        return left + round(width * ratio)

    def _visible_duration_ms(self) -> int:
        if self._duration_ms <= 0:
            return 0
        return min(self._duration_ms, max(1, round(self._duration_ms / max(1.0, self._zoom))))

    def _view_end_ms(self) -> int:
        return min(self._duration_ms, self._view_start_ms + self._visible_duration_ms())

    def _ensure_visible(self, value_ms: int) -> None:
        if self._duration_ms <= 0 or self._zoom <= 1.0:
            return
        visible = self._visible_duration_ms()
        margin = min(1200, max(80, visible // 8))
        next_start = self._view_start_ms
        if value_ms < self._view_start_ms + margin:
            next_start = value_ms - margin
        elif value_ms > self._view_start_ms + visible - margin:
            next_start = value_ms - visible + margin
        next_start = self._clamped_view_start(next_start)
        if next_start != self._view_start_ms:
            self._view_start_ms = next_start
            self._emit_view_changed()

    def _clamped_view_start(self, value_ms: int) -> int:
        if self._duration_ms <= 0:
            return 0
        maximum = max(0, self._duration_ms - self._visible_duration_ms())
        return max(0, min(int(value_ms), maximum))

    def _clamp_ms(self, value_ms: int) -> int:
        if self._duration_ms <= 0:
            return 0
        return max(0, min(int(value_ms), self._duration_ms))

    def _max_zoom(self) -> float:
        if self._duration_ms <= 0:
            return 1.0
        return min(10000.0, max(1.0, self._duration_ms / 1000.0))

    def _emit_view_changed(self) -> None:
        self.viewChanged.emit(self._view_start_ms, self._visible_duration_ms(), self._zoom)

    def _nice_tick_step(self, target_seconds: float) -> float:
        for step in (
            0.05,
            0.1,
            0.2,
            0.5,
            1.0,
            2.0,
            5.0,
            10.0,
            15.0,
            30.0,
            60.0,
            120.0,
            300.0,
            600.0,
            1200.0,
        ):
            if step >= target_seconds:
                return step
        return 1800.0


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
    addPhotoRequested = pyqtSignal(float)
    updateClipRequested = pyqtSignal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._video_path = ""
        self._duration_ms = 0
        self._position_ms = 0
        self._range_preview = False
        self._syncing_range = False
        self._syncing_timeline_controls = False
        self._waveform_path = ""
        self._waveform_workers: list[AudioWaveformWorker] = []

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
        self.file_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

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
        self.timeline_scroll = QScrollBar(Qt.Orientation.Horizontal)
        self.timeline_scroll.setRange(0, 0)
        self.timeline_scroll.setEnabled(False)
        self.timeline_zoom_label = QLabel("Zoom 100%")
        self.timeline_zoom_label.setMinimumWidth(86)
        self.timeline_zoom_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.timeline_zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.timeline_zoom_slider.setRange(0, 100)
        self.timeline_zoom_slider.setValue(0)
        self.timeline_zoom_slider.setToolTip("Perbesar timeline untuk melihat detik audio lebih dekat")
        self.timeline_zoom_out_button = QToolButton()
        self.timeline_zoom_out_button.setObjectName("TransportButton")
        self.timeline_zoom_out_button.setText("-")
        self.timeline_zoom_out_button.setToolTip("Zoom out timeline")
        self.timeline_zoom_in_button = QToolButton()
        self.timeline_zoom_in_button.setObjectName("TransportButton")
        self.timeline_zoom_in_button.setText("+")
        self.timeline_zoom_in_button.setToolTip("Zoom in timeline")
        self.timeline_fit_button = QToolButton()
        self.timeline_fit_button.setObjectName("TransportButton")
        self.timeline_fit_button.setText("Fit")
        self.timeline_fit_button.setToolTip("Tampilkan seluruh durasi video")
        for button in (
            self.timeline_zoom_out_button,
            self.timeline_zoom_in_button,
            self.timeline_fit_button,
        ):
            button.setMinimumWidth(38)
            button.setMinimumHeight(30)

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
        self.add_photo_button = QPushButton("Save Photo")
        self.add_photo_button.setToolTip("Ambil frame pada posisi playhead dan simpan ke Manual Clips")
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
            self.file_label.setToolTip("")
            self.status_label.setText("Import video untuk membuka editor visual")
            self.status_label.setToolTip("")
            self._waveform_path = ""
            self.timeline.set_waveform_status("Import video untuk melihat waveform audio")
            self._set_duration_ms(0)
            self._set_enabled(False)
            return

        source = Path(video_path)
        self.file_label.setText(source.name)
        self.file_label.setToolTip(source.name)
        self.status_label.setText(str(source))
        self.status_label.setToolTip(str(source))
        self.player.setSource(QUrl.fromLocalFile(str(source)))
        self._set_enabled(True)
        if video_path != self._waveform_path:
            self._waveform_path = video_path
            self.timeline.set_waveform_status("Membuat waveform audio...")
            self._start_waveform_worker(video_path)

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
        range_layout.addWidget(self.add_photo_button, 1, 4)
        range_layout.addWidget(self.apply_clip_button, 1, 5)
        zoom_row = QHBoxLayout()
        zoom_row.setContentsMargins(0, 0, 0, 0)
        zoom_row.setSpacing(8)
        zoom_row.addWidget(QLabel("Timeline"))
        zoom_row.addWidget(self.timeline_zoom_out_button)
        zoom_row.addWidget(self.timeline_zoom_slider, 1)
        zoom_row.addWidget(self.timeline_zoom_in_button)
        zoom_row.addWidget(self.timeline_fit_button)
        zoom_row.addWidget(self.timeline_zoom_label)
        range_layout.addLayout(zoom_row, 2, 0, 1, 6)
        range_layout.addWidget(self.timeline, 3, 0, 1, 6)
        range_layout.addWidget(self.timeline_scroll, 4, 0, 1, 6)
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
        self.timeline.rangeEdited.connect(self._timeline_range_edited)
        self.timeline.viewChanged.connect(self._sync_timeline_view)
        self.timeline_scroll.valueChanged.connect(self.timeline.set_view_start_ms)
        self.timeline_zoom_slider.valueChanged.connect(self._zoom_slider_changed)
        self.timeline_zoom_out_button.clicked.connect(lambda: self._adjust_visual_timeline_zoom(1 / 1.35))
        self.timeline_zoom_in_button.clicked.connect(lambda: self._adjust_visual_timeline_zoom(1.35))
        self.timeline_fit_button.clicked.connect(self.timeline.fit_to_duration)
        self.in_spin.valueChanged.connect(self._range_spin_changed)
        self.out_spin.valueChanged.connect(self._range_spin_changed)
        self.mark_in_button.clicked.connect(self._mark_in)
        self.mark_out_button.clicked.connect(self._mark_out)
        self.preview_range_button.clicked.connect(self._preview_range)
        self.add_clip_button.clicked.connect(self._emit_add_clip)
        self.add_photo_button.clicked.connect(self._emit_add_photo)
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
            self.timeline,
            self.timeline_scroll,
            self.timeline_zoom_out_button,
            self.timeline_zoom_in_button,
            self.timeline_fit_button,
            self.timeline_zoom_slider,
            self.in_spin,
            self.out_spin,
            self.mark_in_button,
            self.mark_out_button,
            self.preview_range_button,
            self.add_clip_button,
            self.add_photo_button,
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

    def _timeline_range_edited(self, in_ms: int, out_ms: int) -> None:
        self._syncing_range = True
        self.in_spin.setValue(in_ms / 1000)
        self.out_spin.setValue(out_ms / 1000)
        self._syncing_range = False

    def _sync_timeline_view(self, start_ms: int, visible_ms: int, zoom: float) -> None:
        if self._syncing_timeline_controls:
            return
        self._syncing_timeline_controls = True
        try:
            maximum = max(0, self._duration_ms - visible_ms)
            self.timeline_scroll.blockSignals(True)
            self.timeline_scroll.setRange(0, maximum)
            self.timeline_scroll.setPageStep(max(1, visible_ms))
            self.timeline_scroll.setSingleStep(max(1, visible_ms // 20))
            self.timeline_scroll.setValue(min(maximum, start_ms))
            self.timeline_scroll.setEnabled(maximum > 0)
            self.timeline_scroll.blockSignals(False)

            self.timeline_zoom_slider.blockSignals(True)
            self.timeline_zoom_slider.setValue(self._slider_value_for_zoom(zoom))
            self.timeline_zoom_slider.blockSignals(False)
            self.timeline_zoom_label.setText(f"Zoom {round(zoom * 100)}%")
        finally:
            self._syncing_timeline_controls = False

    def _zoom_slider_changed(self, value: int) -> None:
        if self._syncing_timeline_controls:
            return
        self.timeline.set_zoom(self._zoom_for_slider_value(value), self._position_ms)

    def _adjust_visual_timeline_zoom(self, factor: float) -> None:
        self.timeline.adjust_zoom(factor, self._position_ms)

    def _slider_value_for_zoom(self, zoom: float) -> int:
        max_zoom = self.timeline.max_zoom()
        if max_zoom <= 1.0:
            return 0
        return min(100, max(0, round(math.log(max(1.0, zoom), max_zoom) * 100)))

    def _zoom_for_slider_value(self, value: int) -> float:
        max_zoom = self.timeline.max_zoom()
        if max_zoom <= 1.0:
            return 1.0
        return max_zoom ** (min(100, max(0, value)) / 100)

    def _start_waveform_worker(self, video_path: str) -> None:
        worker = AudioWaveformWorker(video_path, self)
        self._waveform_workers.append(worker)
        worker.succeeded.connect(self._on_waveform_ready)
        worker.failed.connect(self._on_waveform_failed)
        worker.finished.connect(lambda active_worker=worker: self._waveform_worker_finished(active_worker))
        worker.start()

    def _on_waveform_ready(self, video_path: str, peaks: list[float]) -> None:
        if video_path != self._video_path:
            return
        self.timeline.set_waveform(peaks)

    def _on_waveform_failed(self, video_path: str, error_message: str) -> None:
        if video_path != self._video_path:
            return
        message = "Waveform audio tidak bisa dibaca. Pastikan FFmpeg tersedia dan video punya audio."
        self.timeline.set_waveform_status(message)
        self.status_label.setText(message if not error_message else f"{message}")

    def _waveform_worker_finished(self, worker: AudioWaveformWorker) -> None:
        if worker in self._waveform_workers:
            self._waveform_workers.remove(worker)
        worker.deleteLater()

    def _emit_add_clip(self) -> None:
        start, end = self._range_seconds()
        if end <= start:
            return
        label = f"Visual cut {format_duration(start)} - {format_duration(end)}"
        self.addClipRequested.emit(start, end, label)

    def _emit_add_photo(self) -> None:
        if not self._video_path:
            return
        self.addPhotoRequested.emit(self.current_position_seconds())

    def _emit_update_clip(self) -> None:
        start, end = self._range_seconds()
        if end <= start:
            return
        self.updateClipRequested.emit(start, end)

    def _range_seconds(self) -> tuple[float, float]:
        return float(self.in_spin.value()), float(self.out_spin.value())

    def current_position_seconds(self) -> float:
        return max(0.0, self._position_ms / 1000)


class VideoPreviewPanel(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._video_path = ""
        self._duration_ms = 0
        self._position_ms = 0
        self._clip_start_ms = 0
        self._clip_end_ms = 0
        self._range_preview = False
        self._sequence_preview = False
        self._sequence_items: list[dict[str, int]] = []
        self._sequence_index = 0
        self._sequence_total_ms = 0
        self._sequence_output_position_ms = 0
        self._sequence_item_elapsed_ms = 0
        self._sequence_chunk_output_start_ms = 0
        self._sequence_remaining_ms = 0
        self._sequence_source_duration_ms = 0
        self._sequence_finished = False

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.65)
        self.player.setAudioOutput(self.audio_output)

        self.video_widget = QVideoWidget()
        self.video_widget.setObjectName("VideoPreview")
        self.video_widget.setMinimumSize(360, 220)
        self.video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.player.setVideoOutput(self.video_widget)

        self.video_frame = QFrame()
        self.video_frame.setObjectName("TimelinePreviewFrame")
        self.video_frame.setStyleSheet("QFrame#TimelinePreviewFrame { background: #030712; border: 0; }")
        self.video_frame.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        video_frame_layout = QVBoxLayout(self.video_frame)
        video_frame_layout.setContentsMargins(0, 0, 0, 64)
        video_frame_layout.setSpacing(0)
        video_frame_layout.addWidget(self.video_widget, 1)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("PanelTitle")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.status_label = QLabel("No preview loaded")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

        self.play_button = QToolButton()
        self.back_button = QToolButton()
        self.forward_button = QToolButton()
        style = self.style()
        self.play_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.back_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaSeekBackward))
        self.forward_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaSeekForward))
        for button in (self.play_button, self.back_button, self.forward_button):
            button.setObjectName("TransportButton")
            button.setIconSize(QSize(18, 18))
            button.setFixedSize(36, 34)

        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.time_label = QLabel("00:00.000 / 00:00.000")
        self.time_label.setMinimumWidth(170)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(self.title_label)
        header.addWidget(self.status_label, 1)
        transport = QHBoxLayout()
        transport.setContentsMargins(0, 0, 0, 0)
        transport.setSpacing(8)
        transport.addWidget(self.back_button)
        transport.addWidget(self.play_button)
        transport.addWidget(self.forward_button)
        transport.addWidget(self.position_slider, 1)
        transport.addWidget(self.time_label)
        layout.addLayout(header)
        layout.addLayout(transport)
        layout.addWidget(self.video_frame, 1)

        self.play_button.clicked.connect(self._toggle_playback)
        self.back_button.clicked.connect(lambda: self._jump_relative_ms(-1000))
        self.forward_button.clicked.connect(lambda: self._jump_relative_ms(1000))
        self.position_slider.sliderMoved.connect(self.seek_to_ms)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.playbackStateChanged.connect(self._sync_play_button)
        self.player.errorOccurred.connect(self._on_playback_error)
        self.set_video("", 0.0)

    def set_video(self, video_path: str, duration_seconds: float | None = None) -> None:
        self._video_path = video_path
        self._range_preview = False
        self._sequence_preview = False
        self._sequence_items = []
        self._sequence_index = 0
        self._sequence_total_ms = 0
        self._sequence_output_position_ms = 0
        self._sequence_item_elapsed_ms = 0
        self._sequence_chunk_output_start_ms = 0
        self._sequence_remaining_ms = 0
        self._sequence_source_duration_ms = 0
        self._sequence_finished = False
        self.player.stop()
        self._clip_start_ms = 0
        self._clip_end_ms = 0
        if not video_path:
            self.player.setSource(QUrl())
            self.status_label.setText("No preview loaded")
            self.status_label.setToolTip("")
            self._set_duration_ms(0)
            self._set_enabled(False)
            return

        source = Path(video_path)
        self.player.setSource(QUrl.fromLocalFile(str(source)))
        self.status_label.setText(source.name)
        self.status_label.setToolTip(str(source))
        self._set_enabled(True)
        self._set_duration_ms(int(round(max(0.0, float(duration_seconds or 0.0)) * 1000)))

    def set_clip_range(self, start: float, end: float, seek: bool = True) -> None:
        self._sequence_preview = False
        self._sequence_total_ms = 0
        self._sequence_output_position_ms = 0
        self._sequence_finished = False
        self._clip_start_ms = round(max(0.0, start) * 1000)
        self._clip_end_ms = round(max(start, end) * 1000)
        self._range_preview = self._clip_end_ms > self._clip_start_ms
        if seek:
            self.seek_to_ms(self._clip_start_ms)

    def set_timeline_sequence(
        self,
        video_path: str,
        clips: list[dict[str, float]],
        source_duration_seconds: float | None = None,
        autoplay: bool = True,
    ) -> None:
        sequence: list[dict[str, int]] = []
        for clip in clips:
            start_ms = round(max(0.0, float(clip.get("start", 0.0) or 0.0)) * 1000)
            end_ms = round(max(start_ms / 1000, float(clip.get("end", 0.0) or 0.0)) * 1000)
            output_ms = round(max(0.0, float(clip.get("output_duration", 0.0) or 0.0)) * 1000)
            if end_ms <= start_ms:
                continue
            if output_ms <= 0:
                output_ms = end_ms - start_ms
            sequence.append({"start": start_ms, "end": end_ms, "output": max(1, output_ms)})

        self.set_video(video_path, source_duration_seconds)
        self._sequence_items = sequence
        self._sequence_preview = bool(sequence)
        self._sequence_index = 0
        self._sequence_total_ms = sum(item["output"] for item in sequence)
        self._sequence_output_position_ms = 0
        self._sequence_item_elapsed_ms = 0
        self._sequence_chunk_output_start_ms = 0
        self._sequence_remaining_ms = 0
        self._sequence_finished = False
        if not sequence:
            self.status_label.setText("Timeline preview kosong")
            return

        self.position_slider.setRange(0, self._sequence_total_ms)
        self.status_label.setText(f"Timeline preview: 1/{len(sequence)}")
        self._start_sequence_item(0, autoplay=autoplay)

    def seek_to_ms(self, position_ms: int) -> None:
        if self._sequence_preview:
            was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            self._seek_sequence_to_output_ms(position_ms, autoplay=was_playing)
            return

        self._seek_source_to_ms(position_ms)

    def _seek_source_to_ms(self, position_ms: int) -> None:
        if self._duration_ms <= 0:
            return
        position_ms = max(0, min(int(position_ms), self._duration_ms))
        self.player.setPosition(position_ms)
        self._on_position_changed(position_ms)

    def _jump_relative_ms(self, delta_ms: int) -> None:
        if self._sequence_preview:
            self.seek_to_ms(self._sequence_output_position_ms + delta_ms)
            return
        self.seek_to_ms(self._position_ms + delta_ms)

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (self.play_button, self.back_button, self.forward_button, self.position_slider):
            widget.setEnabled(enabled)

    def _set_duration_ms(self, duration_ms: int) -> None:
        self._duration_ms = max(0, int(duration_ms))
        if self._sequence_preview and self._sequence_total_ms > 0:
            self.position_slider.setRange(0, self._sequence_total_ms)
            self._sync_sequence_timeline_ui()
        else:
            self.position_slider.setRange(0, self._duration_ms)
            self._on_position_changed(min(self._position_ms, self._duration_ms))

    def _on_position_changed(self, position_ms: int) -> None:
        self._position_ms = max(0, min(int(position_ms), max(0, self._duration_ms)))
        if self._sequence_preview:
            self._sync_sequence_position_from_source()
        else:
            self.position_slider.blockSignals(True)
            self.position_slider.setValue(self._position_ms)
            self.position_slider.blockSignals(False)
            self.time_label.setText(
                f"{format_duration(self._position_ms / 1000)} / {format_duration(self._duration_ms / 1000)}"
            )
        if self._range_preview and self._clip_end_ms > 0 and self._position_ms >= self._clip_end_ms:
            if self._sequence_preview:
                self._advance_sequence()
            else:
                self.player.pause()
                self.seek_to_ms(self._clip_start_ms)

    def _on_duration_changed(self, duration_ms: int) -> None:
        if duration_ms > 0:
            self._set_duration_ms(duration_ms)

    def _on_playback_error(self, error: QMediaPlayer.Error, error_string: str) -> None:
        if error != QMediaPlayer.Error.NoError:
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
            self.player.pause()
        else:
            if self._sequence_preview and self._sequence_finished:
                self._start_sequence_item(0, output_offset_ms=0, autoplay=True)
                return
            if self._range_preview and self._position_ms >= self._clip_end_ms:
                self._seek_source_to_ms(self._clip_start_ms)
            self.player.play()

    def _start_sequence_item(
        self,
        index: int,
        output_offset_ms: int = 0,
        autoplay: bool = True,
    ) -> None:
        if not self._sequence_items:
            return
        self._sequence_index = min(max(0, index), len(self._sequence_items) - 1)
        item = self._sequence_items[self._sequence_index]
        start_ms = int(item["start"])
        end_ms = int(item["end"])
        output_ms = int(item["output"])
        source_ms = max(1, end_ms - start_ms)
        output_offset_ms = min(max(0, int(output_offset_ms)), max(0, output_ms - 1))
        loop_offset_ms = output_offset_ms % source_ms
        remaining_output_ms = max(1, output_ms - output_offset_ms)
        render_ms = min(max(1, source_ms - loop_offset_ms), remaining_output_ms)
        self._sequence_source_duration_ms = source_ms
        self._sequence_item_elapsed_ms = output_offset_ms
        self._sequence_remaining_ms = max(0, output_ms - output_offset_ms - render_ms)
        self._sequence_chunk_output_start_ms = self._sequence_cumulative_ms(self._sequence_index) + output_offset_ms
        self._sequence_output_position_ms = self._sequence_chunk_output_start_ms
        self._sequence_finished = False
        self._clip_start_ms = start_ms + loop_offset_ms
        self._clip_end_ms = self._clip_start_ms + render_ms
        self._range_preview = True
        self.status_label.setText(f"Timeline preview: {self._sequence_index + 1}/{len(self._sequence_items)}")
        self._sync_sequence_timeline_ui()
        self._seek_source_to_ms(self._clip_start_ms)
        if autoplay:
            self.player.play()

    def _advance_sequence(self) -> None:
        if not self._sequence_items:
            self.player.pause()
            self._sequence_preview = False
            return

        item = self._sequence_items[self._sequence_index]
        current_chunk_ms = max(1, self._clip_end_ms - self._clip_start_ms)
        next_output_offset_ms = self._sequence_item_elapsed_ms + current_chunk_ms
        if next_output_offset_ms < int(item["output"]) - 50:
            self._start_sequence_item(
                self._sequence_index,
                output_offset_ms=next_output_offset_ms,
                autoplay=True,
            )
            return

        next_index = self._sequence_index + 1
        if next_index >= len(self._sequence_items):
            self.player.pause()
            self._range_preview = False
            self._sequence_finished = True
            self._sequence_output_position_ms = self._sequence_total_ms
            self._sync_sequence_timeline_ui()
            self.status_label.setText("Timeline preview selesai")
            return

        self._start_sequence_item(next_index, output_offset_ms=0, autoplay=True)

    def _seek_sequence_to_output_ms(self, position_ms: int, autoplay: bool = False) -> None:
        if not self._sequence_items or self._sequence_total_ms <= 0:
            return

        position_ms = min(max(0, int(position_ms)), self._sequence_total_ms)
        if position_ms >= self._sequence_total_ms:
            last_index = len(self._sequence_items) - 1
            last_output = max(1, int(self._sequence_items[last_index]["output"]))
            self._start_sequence_item(last_index, output_offset_ms=last_output - 1, autoplay=False)
            self.player.pause()
            self._sequence_finished = True
            self._range_preview = False
            self._sequence_output_position_ms = self._sequence_total_ms
            self._sync_sequence_timeline_ui()
            self.status_label.setText("Timeline preview selesai")
            return

        cursor = 0
        for index, item in enumerate(self._sequence_items):
            output_ms = int(item["output"])
            if position_ms < cursor + output_ms:
                self._start_sequence_item(index, output_offset_ms=position_ms - cursor, autoplay=autoplay)
                return
            cursor += output_ms

    def _sync_sequence_position_from_source(self) -> None:
        source_elapsed_ms = max(0, min(self._position_ms - self._clip_start_ms, self._clip_end_ms - self._clip_start_ms))
        self._sequence_output_position_ms = min(
            self._sequence_total_ms,
            self._sequence_chunk_output_start_ms + source_elapsed_ms,
        )
        self._sync_sequence_timeline_ui()

    def _sync_sequence_timeline_ui(self) -> None:
        self.position_slider.blockSignals(True)
        self.position_slider.setRange(0, max(0, self._sequence_total_ms))
        self.position_slider.setValue(min(max(0, self._sequence_output_position_ms), self._sequence_total_ms))
        self.position_slider.blockSignals(False)
        self.time_label.setText(
            f"{format_duration(self._sequence_output_position_ms / 1000)} / "
            f"{format_duration(self._sequence_total_ms / 1000)}"
        )

    def _sequence_cumulative_ms(self, index: int) -> int:
        return sum(int(item["output"]) for item in self._sequence_items[: max(0, index)])


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


def _thumbnail_icon(data: dict[str, Any]) -> QIcon | None:
    image_path = str(data.get("thumbnail_path") or data.get("thumbnail") or data.get("image_path") or "").strip()
    if not image_path:
        return None
    pixmap = _thumbnail_pixmap(image_path)
    return QIcon(pixmap) if pixmap else None


def _is_photo_clip(data: dict[str, Any]) -> bool:
    kind = str(data.get("media_type") or data.get("kind") or "").strip().lower()
    return kind in {"photo", "still", "image"} or bool(data.get("image_path"))


def _duration_text(start: float, end: float) -> str:
    return format_duration(max(0.0, end - start))


def _clip_output_duration(data: dict[str, Any], start: float, end: float) -> float:
    for key in ("output_duration", "output_duration_seconds"):
        try:
            value = float(data.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    return max(0.0, end - start)


def _decode_clip_payload(raw: Any) -> dict[str, Any]:
    try:
        if hasattr(raw, "data"):
            raw = raw.data()
        payload = json.loads(bytes(raw).decode("utf-8"))
    except (TypeError, ValueError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _timeline_copy(clip: dict[str, Any], index: int = 1) -> dict[str, Any]:
    data = dict(clip)
    base_id = str(data.get("id") or "clip")
    data["id"] = f"{base_id}_tl_{datetime.now().strftime('%H%M%S%f')}_{index}"
    data["source_clip_id"] = base_id
    data["kind"] = str(data.get("kind") or "manual")
    try:
        start = parse_timestamp(data.get("start", 0.0))
        end = parse_timestamp(data.get("end", start))
        data.setdefault("output_duration", round(max(0.1, end - start), 3))
    except (TypeError, ValueError):
        pass
    return data


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
