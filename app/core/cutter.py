from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .video_utils import MediaToolError, format_duration, parse_timestamp, resolve_media_tool


ProgressCallback = Callable[[str], None]


@dataclass(slots=True)
class ClipItem:
    id: str
    start: float
    end: float
    text: str
    source_segment_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClipItem":
        return cls(
            id=str(data.get("id") or "clip"),
            start=parse_timestamp(data.get("start", 0.0)),
            end=parse_timestamp(data.get("end", 0.0)),
            text=str(data.get("text") or ""),
            source_segment_id=(
                int(data["source_segment_id"])
                if data.get("source_segment_id") not in (None, "")
                else None
            ),
        )


def export_clip(
    video_path: str | Path,
    output_dir: str | Path,
    clip: ClipItem,
    ffmpeg_path: str = "ffmpeg",
    reencode: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    source = Path(video_path)
    target_dir = Path(output_dir)

    if not source.exists():
        raise FileNotFoundError(f"Video file does not exist: {source}")
    if clip.end <= clip.start:
        raise ValueError(f"Clip {clip.id} end time must be after start time.")

    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / _build_clip_filename(clip)

    if progress_callback:
        progress_callback(
            f"Exporting {clip.id}: {format_duration(clip.start)} to {format_duration(clip.end)}"
        )

    ffmpeg = resolve_media_tool(ffmpeg_path)
    command = [
        ffmpeg,
        "-y",
        "-ss",
        f"{clip.start:.3f}",
        "-to",
        f"{clip.end:.3f}",
        "-i",
        str(source),
    ]

    if reencode:
        command.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-movflags",
                "+faststart",
            ]
        )
    else:
        command.extend(["-c", "copy"])

    command.append(str(target))

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
        raise MediaToolError(details) from exc

    if progress_callback:
        progress_callback(f"Clip exported: {target.name}")
    return target


def export_clips(
    video_path: str | Path,
    output_dir: str | Path,
    clips: Iterable[ClipItem],
    ffmpeg_path: str = "ffmpeg",
    progress_callback: ProgressCallback | None = None,
) -> list[Path]:
    outputs: list[Path] = []
    for clip in clips:
        outputs.append(
            export_clip(
                video_path=video_path,
                output_dir=output_dir,
                clip=clip,
                ffmpeg_path=ffmpeg_path,
                progress_callback=progress_callback,
            )
        )
    return outputs


def _build_clip_filename(clip: ClipItem) -> str:
    safe_id = _safe_filename(clip.id or "clip")
    start = _time_for_filename(clip.start)
    end = _time_for_filename(clip.end)
    return f"{safe_id}_{start}_{end}.mp4"


def _time_for_filename(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}-{minutes:02d}-{secs:02d}-{millis:03d}"


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return safe.strip("._") or "clip"
