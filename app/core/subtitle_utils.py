from __future__ import annotations

import html
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .text_importer import read_text_file, text_to_transcript_segments
from .transcriber import TranscriptSegment
from .video_utils import MediaToolError, resolve_media_tool, run_command


ProgressCallback = Callable[[str], None]

INDONESIAN_LANGUAGE_TAGS = {
    "id",
    "idn",
    "ind",
    "ina",
    "indonesia",
    "indonesian",
    "bahasa",
    "bahasa indonesia",
}


@dataclass(slots=True)
class SubtitleStream:
    index: int
    subtitle_index: int
    codec: str
    language: str
    title: str

    @property
    def label(self) -> str:
        parts = [f"stream {self.index}", self.codec]
        if self.language:
            parts.append(self.language)
        if self.title:
            parts.append(self.title)
        return " / ".join(parts)


def list_subtitle_streams(video_path: str | Path, ffprobe_path: str = "ffprobe") -> list[SubtitleStream]:
    source = Path(video_path)
    if not source.exists():
        raise FileNotFoundError(f"Video file does not exist: {source}")

    ffprobe = resolve_media_tool(ffprobe_path)
    result = run_command(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            str(source),
        ]
    )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaToolError("ffprobe returned invalid JSON output.") from exc

    streams: list[SubtitleStream] = []
    subtitle_index = 0
    for stream in payload.get("streams", []):
        if stream.get("codec_type") != "subtitle":
            continue
        tags = stream.get("tags") or {}
        streams.append(
            SubtitleStream(
                index=int(stream.get("index", subtitle_index)),
                subtitle_index=subtitle_index,
                codec=str(stream.get("codec_name") or "unknown"),
                language=str(tags.get("language") or "").strip().lower(),
                title=str(tags.get("title") or tags.get("handler_name") or "").strip(),
            )
        )
        subtitle_index += 1
    return streams


def choose_indonesian_subtitle_stream(streams: list[SubtitleStream]) -> SubtitleStream | None:
    if not streams:
        return None

    for stream in streams:
        haystack = f"{stream.language} {stream.title}".strip().lower()
        if any(tag in haystack for tag in INDONESIAN_LANGUAGE_TAGS):
            return stream
    return streams[0]


def extract_best_subtitle_segments(
    video_path: str | Path,
    output_dir: str | Path,
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[TranscriptSegment], Path, SubtitleStream]:
    streams = list_subtitle_streams(video_path)
    if not streams:
        raise MediaToolError(
            "No extractable subtitle streams were found. If the Indonesian subtitle is burned into "
            "the picture, this MVP cannot read it yet; import an external .srt/.vtt/.ass/.txt file instead."
        )

    stream = choose_indonesian_subtitle_stream(streams)
    if stream is None:
        raise MediaToolError("No subtitle stream could be selected.")

    if progress_callback:
        progress_callback(f"Selected subtitle: {stream.label}")

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    subtitle_path = target_dir / "indonesian_subtitles.srt"
    extract_subtitle_stream(video_path, subtitle_path, stream, progress_callback=progress_callback)

    segments = subtitle_file_to_segments(subtitle_path)
    if not segments:
        raise MediaToolError(
            "Subtitle extraction succeeded, but no readable subtitle text was found."
        )
    return segments, subtitle_path, stream


def extract_subtitle_stream(
    video_path: str | Path,
    output_path: str | Path,
    stream: SubtitleStream,
    ffmpeg_path: str = "ffmpeg",
    progress_callback: ProgressCallback | None = None,
) -> Path:
    source = Path(video_path)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if progress_callback:
        progress_callback("Extracting Indonesian subtitle with FFmpeg...")

    ffmpeg = resolve_media_tool(ffmpeg_path)
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-map",
        f"0:{stream.index}",
        "-c:s",
        "srt",
        str(target),
    ]

    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise MediaToolError(
            "FFmpeg was not found. Install FFmpeg and make sure ffmpeg is on PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        details = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise MediaToolError(
            details
            + "\n\nIf this is an image-based subtitle stream, export/import a text subtitle file instead."
        ) from exc

    if progress_callback:
        progress_callback(f"Subtitle extracted: {target.name}")
    return target


def subtitle_file_to_segments(path: str | Path) -> list[TranscriptSegment]:
    source = Path(path)
    text = read_text_file(source)
    suffix = source.suffix.lower()

    if suffix in {".ass", ".ssa"} or "[events]" in text.lower():
        segments = _parse_ass_subtitles(text)
        if segments:
            return segments

    if "-->" in text:
        segments = _parse_timed_text_subtitles(text)
        if segments:
            return segments

    return text_to_transcript_segments(_strip_subtitle_markup(text))


def write_srt_file(segments: list[TranscriptSegment], output_path: str | Path) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    index = 1
    for segment in prepare_subtitle_segments(segments):
        text = str(segment.text or "").strip()
        if not text:
            continue
        start = max(0.0, float(segment.start or 0.0))
        end = max(start + 0.1, float(segment.end or 0.0))
        lines.extend(
            [
                str(index),
                f"{_format_srt_time(start)} --> {_format_srt_time(end)}",
                text,
                "",
            ]
        )
        index += 1

    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def prepare_subtitle_segments(
    segments: list[TranscriptSegment],
    max_chars_per_line: int = 42,
    max_lines: int = 2,
) -> list[TranscriptSegment]:
    refined: list[TranscriptSegment] = []
    max_chars = max(24, max_chars_per_line * max_lines)

    for segment in segments:
        text = _strip_subtitle_markup(str(segment.text or ""))
        if not text:
            continue

        start = max(0.0, float(segment.start or 0.0))
        end = max(start + 0.1, float(segment.end or 0.0))
        chunks = _split_subtitle_text(text, max_chars=max_chars)
        if not chunks:
            continue

        duration = max(0.1, end - start)
        total_weight = sum(max(1, len(chunk)) for chunk in chunks)
        cursor = start

        for index, chunk in enumerate(chunks):
            if index == len(chunks) - 1:
                chunk_end = end
            else:
                weight = max(1, len(chunk)) / max(1, total_weight)
                chunk_end = min(end, cursor + duration * weight)
            if chunk_end <= cursor:
                chunk_end = min(end, cursor + 0.1)

            refined.append(
                TranscriptSegment(
                    start=cursor,
                    end=chunk_end,
                    text=_wrap_subtitle_text(chunk, max_chars_per_line, max_lines),
                )
            )
            cursor = chunk_end

    return refined


def _split_subtitle_text(text: str, max_chars: int) -> list[str]:
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", text)
        if part.strip()
    ] or [text.strip()]

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_words_to_subtitle_chunks(sentence, max_chars))
            continue

        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = candidate

    if current:
        chunks.append(current)
    return chunks


def _split_words_to_subtitle_chunks(text: str, max_chars: int) -> list[str]:
    chunks: list[str] = []
    current_words: list[str] = []
    current_len = 0
    for word in text.split():
        next_len = current_len + len(word) + (1 if current_words else 0)
        if current_words and next_len > max_chars:
            chunks.append(" ".join(current_words))
            current_words = [word]
            current_len = len(word)
        else:
            current_words.append(word)
            current_len = next_len
    if current_words:
        chunks.append(" ".join(current_words))
    return chunks


def _wrap_subtitle_text(text: str, max_chars_per_line: int, max_lines: int) -> str:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars_per_line:
            lines.append(current)
            current = word
        else:
            current = candidate

    if current:
        lines.append(current)

    if len(lines) <= max_lines:
        return "\n".join(lines)

    kept = lines[: max(1, max_lines - 1)]
    kept.append(" ".join(lines[max(1, max_lines - 1) :]))
    return "\n".join(kept)


def _parse_timed_text_subtitles(text: str) -> list[TranscriptSegment]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", normalized)
    segments: list[TranscriptSegment] = []

    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if timing_index < 0:
            continue

        timing = lines[timing_index]
        start_text, end_text = timing.split("-->", 1)
        start = _parse_subtitle_time(start_text.strip())
        end = _parse_subtitle_time(end_text.strip().split()[0])
        body_lines = lines[timing_index + 1 :]
        subtitle_text = _strip_subtitle_markup(" ".join(body_lines))
        if subtitle_text and end > start:
            segments.append(TranscriptSegment(start=start, end=end, text=subtitle_text))

    return segments


def _parse_ass_subtitles(text: str) -> list[TranscriptSegment]:
    format_fields: list[str] = []
    segments: list[TranscriptSegment] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if lower.startswith("format:"):
            format_fields = [field.strip().lower() for field in line.split(":", 1)[1].split(",")]
            continue
        if not lower.startswith("dialogue:"):
            continue

        payload = line.split(":", 1)[1].strip()
        if format_fields:
            fields = payload.split(",", len(format_fields) - 1)
            mapping = {
                name: fields[index].strip()
                for index, name in enumerate(format_fields)
                if index < len(fields)
            }
            start_text = mapping.get("start", "")
            end_text = mapping.get("end", "")
            body = mapping.get("text", "")
        else:
            fields = payload.split(",", 9)
            if len(fields) < 10:
                continue
            start_text, end_text, body = fields[1], fields[2], fields[9]

        start = _parse_subtitle_time(start_text)
        end = _parse_subtitle_time(end_text)
        subtitle_text = _strip_subtitle_markup(body.replace("\\N", " "))
        if subtitle_text and end > start:
            segments.append(TranscriptSegment(start=start, end=end, text=subtitle_text))

    return segments


def _parse_subtitle_time(value: str) -> float:
    clean = value.strip().replace(",", ".")
    clean = re.sub(r"\s+.*$", "", clean)
    parts = clean.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours = "0"
        minutes, seconds = parts
    else:
        return float(clean)
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _format_srt_time(seconds: float) -> str:
    total_ms = int(round(max(0.0, seconds) * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _strip_subtitle_markup(value: str) -> str:
    text = html.unescape(value)
    text = re.sub(r"\{\\[^}]*\}", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\[[^\]]+\]", " ", text)
    text = text.replace("\\N", " ").replace("\\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()
