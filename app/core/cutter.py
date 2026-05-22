from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .video_utils import MediaToolError, format_duration, parse_timestamp, resolve_media_tool, run_command


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


def export_timeline_video(
    video_path: str | Path,
    output_path: str | Path,
    clips: Iterable[dict[str, Any] | ClipItem],
    resolution: str = "1280x720",
    fps: float = 30.0,
    bitrate: str = "4500k",
    ffmpeg_path: str = "ffmpeg",
    progress_callback: ProgressCallback | None = None,
) -> Path:
    source = Path(video_path)
    target = Path(output_path)
    timeline_items = [_timeline_export_item(clip) for clip in clips]

    if not source.exists():
        raise FileNotFoundError(f"Video file does not exist: {source}")
    if not timeline_items:
        raise ValueError("Timeline is empty. Add rough-cut or manual clips before exporting.")

    target = target.with_suffix(".mp4")
    target.parent.mkdir(parents=True, exist_ok=True)
    work_dir = target.parent / f"{target.stem}_timeline_work"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg = resolve_media_tool(ffmpeg_path)
    width_height = _parse_resolution(resolution)
    total_duration = sum(float(item["output_duration"]) for item in timeline_items)
    if progress_callback:
        progress_callback(
            f"Full Main Timeline export: {len(timeline_items)} clip(s), "
            f"target duration {format_duration(total_duration)}."
        )
    rendered: list[Path] = []
    for index, item in enumerate(timeline_items, start=1):
        clip = item["clip"]
        output_duration = float(item["output_duration"])
        if clip.end <= clip.start:
            raise ValueError(f"Clip {clip.id} end time must be after start time.")
        segment_path = work_dir / f"{index:04d}_{_safe_filename(clip.id)}.mp4"
        if progress_callback:
            progress_callback(
                f"Rendering timeline clip {index}/{len(timeline_items)}: "
                f"{format_duration(clip.start)} - {format_duration(clip.end)} "
                f"as {format_duration(output_duration)}"
            )
        _render_timeline_segment(
            ffmpeg,
            source,
            segment_path,
            clip,
            output_duration,
            width_height,
            fps,
            bitrate,
        )
        rendered.append(segment_path)

    concat_file = work_dir / "concat.txt"
    concat_file.write_text("\n".join(_concat_line(path) for path in rendered), encoding="utf-8")

    if progress_callback:
        progress_callback("Combining timeline clips into final MP4...")
    run_command(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(target),
        ]
    )

    if progress_callback:
        progress_callback(f"Final video exported: {target}")
    return target


def extract_clip_thumbnail(
    video_path: str | Path,
    output_path: str | Path,
    timestamp_seconds: float,
    ffmpeg_path: str = "ffmpeg",
) -> Path:
    source = Path(video_path)
    target = Path(output_path)
    if not source.exists():
        raise FileNotFoundError(f"Video file does not exist: {source}")

    target.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = resolve_media_tool(ffmpeg_path)
    run_command(
        [
            ffmpeg,
            "-y",
            "-ss",
            f"{max(0.0, float(timestamp_seconds or 0.0)):.3f}",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            "scale=160:-1",
            "-q:v",
            "3",
            str(target),
        ]
    )
    return target


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


def _render_timeline_segment(
    ffmpeg: str,
    source: Path,
    target: Path,
    clip: ClipItem,
    output_duration: float,
    width_height: tuple[int, int] | None,
    fps: float,
    bitrate: str,
) -> None:
    filters: list[str] = []
    if width_height is not None:
        width, height = width_height
        filters.append(
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
    if fps > 0:
        filters.append(f"fps={fps:.3f}")

    source_duration = max(0.1, clip.end - clip.start)
    render_duration = min(source_duration, max(0.1, float(output_duration or source_duration)))
    render_target = target
    if output_duration > render_duration + 0.05:
        render_target = target.with_name(f"{target.stem}_base{target.suffix}")

    command = [
        ffmpeg,
        "-y",
        "-ss",
        f"{clip.start:.3f}",
        "-t",
        f"{render_duration:.3f}",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
    ]
    if filters:
        command.extend(["-vf", ",".join(filters)])
    command.extend(["-c:v", "libx264", "-preset", "veryfast"])
    clean_bitrate = str(bitrate or "").strip()
    if clean_bitrate:
        command.extend(["-b:v", clean_bitrate])
    else:
        command.extend(["-crf", "20"])
    command.extend(["-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(render_target)])
    run_command(command)

    if render_target != target:
        _loop_rendered_segment(ffmpeg, render_target, target, output_duration)


def _timeline_export_item(raw_clip: dict[str, Any] | ClipItem) -> dict[str, Any]:
    if isinstance(raw_clip, ClipItem):
        clip = raw_clip
        output_duration = max(0.1, clip.end - clip.start)
    else:
        data = dict(raw_clip)
        clip = ClipItem.from_dict(data)
        output_duration = _output_duration_from_dict(data, clip)
    return {"clip": clip, "output_duration": output_duration}


def _output_duration_from_dict(data: dict[str, Any], clip: ClipItem) -> float:
    for key in ("output_duration", "output_duration_seconds"):
        try:
            value = float(data.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    return max(0.1, clip.end - clip.start)


def _loop_rendered_segment(ffmpeg: str, source: Path, target: Path, target_duration: float) -> None:
    run_command(
        [
            ffmpeg,
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(source),
            "-t",
            f"{max(0.1, target_duration):.3f}",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(target),
        ]
    )


def _parse_resolution(value: str) -> tuple[int, int] | None:
    text = str(value or "").strip().lower()
    if not text or text == "original":
        return None
    match = re.search(r"(\d{3,5})\s*x\s*(\d{3,5})", text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _concat_line(path: Path) -> str:
    escaped = str(path.resolve()).replace("\\", "/").replace("'", "'\\''")
    return f"file '{escaped}'"
