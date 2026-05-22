from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .transcriber import TranscriptSegment


@dataclass(slots=True)
class TranscriptRecord:
    id: int
    start: float
    end: float
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TranscriptDatabase:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS transcript_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    text TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_transcript_time ON transcript_segments(start_time, end_time)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_transcript_text ON transcript_segments(text)"
            )

    def clear_transcript(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM transcript_segments")

    def save_segments(self, segments: Iterable[TranscriptSegment]) -> None:
        rows = [(segment.start, segment.end, segment.text) for segment in segments]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO transcript_segments (start_time, end_time, text)
                VALUES (?, ?, ?)
                """,
                rows,
            )

    def replace_segments(self, segments: Iterable[TranscriptSegment]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM transcript_segments")
            conn.executemany(
                """
                INSERT INTO transcript_segments (start_time, end_time, text)
                VALUES (?, ?, ?)
                """,
                [(segment.start, segment.end, segment.text) for segment in segments],
            )

    def fetch_segments(self) -> list[TranscriptRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, start_time, end_time, text
                FROM transcript_segments
                ORDER BY start_time ASC
                """
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def search(self, query: str) -> list[TranscriptRecord]:
        clean_query = query.strip()
        if not clean_query:
            return self.fetch_segments()

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, start_time, end_time, text
                FROM transcript_segments
                WHERE text LIKE ? ESCAPE '\\'
                ORDER BY start_time ASC
                """,
                (f"%{_escape_like(clean_query)}%",),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_segment(self, segment_id: int) -> TranscriptRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, start_time, end_time, text
                FROM transcript_segments
                WHERE id = ?
                """,
                (segment_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> TranscriptRecord:
        return TranscriptRecord(
            id=int(row["id"]),
            start=float(row["start_time"]),
            end=float(row["end_time"]),
            text=str(row["text"]),
        )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
