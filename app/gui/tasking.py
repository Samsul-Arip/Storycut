from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import QDialog, QLabel, QProgressBar, QTextEdit, QVBoxLayout, QWidget


TaskFunction = Callable[[Callable[[str], None]], Any]


class TaskWorker(QThread):
    progress = pyqtSignal(str)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, task: TaskFunction, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._task = task

    def run(self) -> None:
        try:
            result = self._task(self.progress.emit)
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class TaskProgressDialog(QDialog):
    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(label)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumWidth(460)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel(label)
        title.setObjectName("PanelTitle")

        self.message_label = QLabel("Preparing...")
        self.message_label.setWordWrap(True)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMinimumHeight(12)

        self.detail_view = QTextEdit()
        self.detail_view.setReadOnly(True)
        self.detail_view.setMaximumHeight(128)
        self.detail_view.setPlaceholderText("Progress details will appear here.")

        note = QLabel("Keep StoryCut AI open while the export is running.")
        note.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(self.message_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.detail_view)
        layout.addWidget(note)

    def set_message(self, message: str) -> None:
        text = str(message or "").strip()
        if not text:
            return
        self.message_label.setText(text)
        self.detail_view.append(text)
        scrollbar = self.detail_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

