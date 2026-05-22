from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
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

    def remove_selected_rows(self) -> int:
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            self.removeRow(row)
        return len(rows)


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
