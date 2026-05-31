from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .video_utils import (
    MediaToolError,
    format_duration,
    parse_timestamp,
    read_video_metadata,
    resolve_media_tool,
    run_command,
)


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
    source_metadata = _safe_video_metadata(source)
    source_has_audio = bool(source_metadata.has_audio) if source_metadata else True
    render_size = _timeline_render_size(source_metadata, width_height)
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
        if not item.get("is_photo") and clip.end <= clip.start:
            raise ValueError(f"Clip {clip.id} end time must be after start time.")
        segment_path = work_dir / f"{index:04d}_{_safe_filename(clip.id)}.mp4"
        if progress_callback:
            effect_text = _effect_progress_text(item)
            progress_callback(
                f"Rendering timeline clip {index}/{len(timeline_items)}: "
                f"{format_duration(clip.start)} - {format_duration(clip.end)} "
                f"as {format_duration(output_duration)}{effect_text}"
            )
        if item.get("is_photo"):
            image_path = Path(str(item.get("image_path") or ""))
            if not image_path.exists():
                raise FileNotFoundError(f"Photo file does not exist: {image_path}")
            _render_photo_timeline_segment(
                ffmpeg,
                image_path,
                segment_path,
                output_duration,
                render_size,
                fps,
                bitrate,
                float(item.get("zoom_percent", 100.0) or 100.0),
            )
        else:
            _render_timeline_segment(
                ffmpeg,
                source,
                segment_path,
                clip,
                output_duration,
                render_size,
                fps,
                bitrate,
                float(item.get("zoom_percent", 100.0) or 100.0),
                float(item.get("slowmo_factor", 1.0) or 1.0),
                source_has_audio,
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


def extract_video_frame(
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
            "-q:v",
            "2",
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
    render_size: tuple[int, int] | None,
    fps: float,
    bitrate: str,
    zoom_percent: float = 100.0,
    slowmo_factor: float = 1.0,
    source_has_audio: bool = True,
) -> None:
    source_duration = max(0.1, clip.end - clip.start)
    slowmo_factor = max(1.0, float(slowmo_factor or 1.0))
    slowed_duration = source_duration * slowmo_factor
    render_duration = source_duration if slowmo_factor > 1.001 else min(
        source_duration,
        max(0.1, float(output_duration or source_duration)),
    )
    needs_loop = output_duration > slowed_duration + 0.05
    needs_full_duration_zoom = zoom_percent > 100.01 and needs_loop
    render_target = target
    if needs_loop:
        render_target = target.with_name(f"{target.stem}_base{target.suffix}")

    segment_duration = max(0.1, min(output_duration, slowed_duration))
    render_zoom_percent = 100.0 if needs_full_duration_zoom else zoom_percent
    filters = _video_filters(render_size, fps, render_zoom_percent, slowmo_factor, segment_duration)
    command = [
        ffmpeg,
        "-y",
        "-ss",
        f"{clip.start:.3f}",
        "-t",
        f"{render_duration:.3f}",
        "-i",
        str(source),
    ]
    if not source_has_audio:
        command.extend(
            [
                "-f",
                "lavfi",
                "-t",
                f"{max(0.1, output_duration):.3f}",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
            ]
        )
    command.extend(
        [
            "-map",
            "0:v:0",
            "-map",
            "0:a:0" if source_has_audio else "1:a:0",
        ]
    )
    if filters:
        command.extend(["-vf", ",".join(filters)])
    if source_has_audio and slowmo_factor > 1.001:
        command.extend(["-af", _atempo_filter(1 / slowmo_factor)])
    command.extend(
        [
            "-t",
            f"{segment_duration:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
        ]
    )
    clean_bitrate = str(bitrate or "").strip()
    if clean_bitrate:
        command.extend(["-b:v", clean_bitrate])
    else:
        command.extend(["-crf", "20"])
    command.extend(
        [
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(render_target),
        ]
    )
    run_command(command)

    if render_target != target:
        if needs_full_duration_zoom:
            loop_target = target.with_name(f"{target.stem}_looped{target.suffix}")
            _loop_rendered_segment(ffmpeg, render_target, loop_target, output_duration)
            _apply_zoom_to_rendered_segment(
                ffmpeg,
                loop_target,
                target,
                output_duration,
                render_size,
                fps,
                bitrate,
                zoom_percent,
            )
        else:
            _loop_rendered_segment(ffmpeg, render_target, target, output_duration)


def _render_photo_timeline_segment(
    ffmpeg: str,
    image_path: Path,
    target: Path,
    output_duration: float,
    render_size: tuple[int, int] | None,
    fps: float,
    bitrate: str,
    zoom_percent: float = 100.0,
) -> None:
    duration = max(0.1, float(output_duration or 3.0))
    filters = _video_filters(render_size, fps, zoom_percent, 1.0, duration)
    command = [
        ffmpeg,
        "-y",
        "-loop",
        "1",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(image_path),
        "-f",
        "lavfi",
        "-t",
        f"{duration:.3f}",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
    ]
    if filters:
        command.extend(["-vf", ",".join(filters)])
    command.extend(["-c:v", "libx264", "-preset", "veryfast"])
    clean_bitrate = str(bitrate or "").strip()
    if clean_bitrate:
        command.extend(["-b:v", clean_bitrate])
    else:
        command.extend(["-crf", "20"])
    command.extend(
        [
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            "-movflags",
            "+faststart",
            str(target),
        ]
    )
    run_command(command)


def _apply_zoom_to_rendered_segment(
    ffmpeg: str,
    source: Path,
    target: Path,
    output_duration: float,
    render_size: tuple[int, int] | None,
    fps: float,
    bitrate: str,
    zoom_percent: float,
) -> None:
    filters = _video_filters(render_size, fps, zoom_percent, 1.0, output_duration)
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-t",
        f"{max(0.1, output_duration):.3f}",
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
    command.extend(
        [
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(target),
        ]
    )
    run_command(command)


def _timeline_export_item(raw_clip: dict[str, Any] | ClipItem) -> dict[str, Any]:
    data: dict[str, Any]
    if isinstance(raw_clip, ClipItem):
        clip = raw_clip
        data = clip.to_dict()
        output_duration = max(0.1, clip.end - clip.start)
    else:
        data = dict(raw_clip)
        if _is_photo_item(data):
            timestamp = _photo_timestamp(data)
            data.setdefault("start", format_duration(timestamp))
            data.setdefault("end", format_duration(timestamp + 0.1))
        clip = ClipItem.from_dict(data)
        output_duration = _output_duration_from_dict(data, clip)
    return {
        "clip": clip,
        "output_duration": output_duration,
        "is_photo": _is_photo_item(data),
        "image_path": str(data.get("image_path") or data.get("thumbnail_path") or ""),
        "zoom_percent": _zoom_percent_from_dict(data),
        "slowmo_factor": _slowmo_factor_from_dict(data),
    }


def _output_duration_from_dict(data: dict[str, Any], clip: ClipItem) -> float:
    for key in ("output_duration", "output_duration_seconds"):
        try:
            value = float(data.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    if _is_photo_item(data):
        return 3.0
    slowmo_factor = _slowmo_factor_from_dict(data)
    if slowmo_factor > 1.0:
        return max(0.1, clip.end - clip.start) * slowmo_factor
    return max(0.1, clip.end - clip.start)


def _video_filters(
    render_size: tuple[int, int] | None,
    fps: float,
    zoom_percent: float = 100.0,
    slowmo_factor: float = 1.0,
    duration_seconds: float = 0.0,
) -> list[str]:
    filters: list[str] = []
    zoom_end = max(100.0, float(zoom_percent or 100.0)) / 100.0
    effective_fps = _effective_fps(fps)
    if render_size is not None:
        width, height = render_size
        filters.append(
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
    if slowmo_factor > 1.001:
        filters.append(f"setpts={slowmo_factor:.4f}*PTS")
    if zoom_end > 1.001 and render_size is not None:
        width, height = render_size
        total_frames = max(2, int(round(effective_fps * max(0.1, float(duration_seconds or 0.1)))))
        progress_frames = max(1, total_frames - 1)
        zoom_delta = zoom_end - 1.0
        zoom_step = zoom_delta / progress_frames
        filters.append(f"fps={effective_fps:.3f}")
        filters.append(
            "zoompan="
            f"z='min({zoom_end:.6f},if(eq(on,0),1,pzoom+{zoom_step:.10f}))':"
            "d=1:"
            "x=iw/2-(iw/zoom/2):"
            "y=ih/2-(ih/zoom/2):"
            f"s={width}x{height}:"
            f"fps={effective_fps:.3f}"
        )
    elif zoom_end > 1.001:
        filters.append(
            f"crop=iw/{zoom_end:.4f}:ih/{zoom_end:.4f}:(iw-iw/{zoom_end:.4f})/2:(ih-ih/{zoom_end:.4f})/2"
        )
        if fps > 0:
            filters.append(f"fps={fps:.3f}")
    elif fps > 0:
        filters.append(f"fps={fps:.3f}")
    return filters


def _zoom_percent_from_dict(data: dict[str, Any]) -> float:
    for key in ("zoom_percent", "effect_zoom_percent"):
        try:
            value = float(data.get(key, 100.0) or 100.0)
        except (TypeError, ValueError):
            value = 100.0
        if value > 100.0:
            return value
    return 100.0


def _slowmo_factor_from_dict(data: dict[str, Any]) -> float:
    for key in ("slowmo_factor", "effect_slowmo_factor"):
        try:
            value = float(data.get(key, 1.0) or 1.0)
        except (TypeError, ValueError):
            value = 1.0
        if value > 1.0:
            return value
    return 1.0


def _is_photo_item(data: dict[str, Any]) -> bool:
    kind = str(data.get("media_type") or data.get("kind") or "").strip().lower()
    return kind in {"photo", "still", "image"} or bool(data.get("image_path"))


def _photo_timestamp(data: dict[str, Any]) -> float:
    for key in ("timestamp", "photo_timestamp", "start"):
        try:
            return parse_timestamp(data.get(key, 0.0))
        except (TypeError, ValueError):
            continue
    return 0.0


def _effect_progress_text(item: dict[str, Any]) -> str:
    pieces: list[str] = []
    if item.get("is_photo"):
        pieces.append("photo")
    zoom_percent = float(item.get("zoom_percent", 100.0) or 100.0)
    slowmo_factor = float(item.get("slowmo_factor", 1.0) or 1.0)
    if zoom_percent > 100.0:
        pieces.append(f"zoom-in 100%->{zoom_percent:.0f}%")
    if slowmo_factor > 1.0:
        pieces.append(f"slowmo {slowmo_factor:.2f}x")
    return f" ({', '.join(pieces)})" if pieces else ""


def _safe_video_metadata(source: Path) -> Any | None:
    try:
        return read_video_metadata(source)
    except Exception:
        return None


def _timeline_render_size(
    source_metadata: Any | None,
    requested_size: tuple[int, int] | None,
) -> tuple[int, int] | None:
    if requested_size is not None:
        return requested_size
    if source_metadata and getattr(source_metadata, "width", 0) and getattr(source_metadata, "height", 0):
        return int(source_metadata.width), int(source_metadata.height)
    return None


def _effective_fps(fps: float) -> float:
    try:
        value = float(fps or 0.0)
    except (TypeError, ValueError):
        value = 0.0
    return value if value > 0 else 30.0


def _atempo_filter(speed: float) -> str:
    speed = max(0.01, float(speed or 1.0))
    parts: list[float] = []
    while speed < 0.5:
        parts.append(0.5)
        speed /= 0.5
    while speed > 2.0:
        parts.append(2.0)
        speed /= 2.0
    parts.append(speed)
    return ",".join(f"atempo={part:.5f}" for part in parts)


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
