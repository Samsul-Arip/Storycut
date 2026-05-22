from __future__ import annotations

from pathlib import Path

from .transcriber import TranscriptSegment


def read_text_file(path: str | Path) -> str:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Text file does not exist: {source}")

    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return source.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return source.read_text(encoding="utf-8", errors="replace")


def text_to_transcript_segments(text: str, words_per_segment: int = 80) -> list[TranscriptSegment]:
    words = text.split()
    if not words:
        return []

    segments: list[TranscriptSegment] = []
    start = 0.0
    for index in range(0, len(words), words_per_segment):
        chunk = " ".join(words[index : index + words_per_segment]).strip()
        if not chunk:
            continue
        duration = max(4.0, len(chunk.split()) * 0.45)
        segments.append(TranscriptSegment(start=start, end=start + duration, text=chunk))
        start += duration
    return segments
