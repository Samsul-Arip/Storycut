from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .video_utils import format_duration, read_video_metadata, resolve_media_tool, run_command


ProgressCallback = Callable[[str], None]


@dataclass(slots=True)
class SceneFrame:
    timestamp: float
    image_path: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_scene_frames(
    video_path: str | Path,
    output_dir: str | Path,
    interval_seconds: int = 10,
    max_frames: int = 120,
    width: int = 360,
    progress_callback: ProgressCallback | None = None,
) -> list[SceneFrame]:
    source = Path(video_path)
    if not source.exists():
        raise FileNotFoundError(f"Video file does not exist: {source}")

    interval = max(2, int(interval_seconds or 10))
    frame_limit = max(1, int(max_frames or 120))
    frame_width = max(160, int(width or 360))
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    _clean_previous_frames(target_dir)

    metadata = read_video_metadata(source)
    duration = metadata.duration
    if progress_callback:
        progress_callback(
            "Extracting visual scene frames every "
            f"{interval} seconds, up to {frame_limit} frames..."
        )

    ffmpeg = resolve_media_tool("ffmpeg")
    output_pattern = target_dir / "scene_%05d.jpg"
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-vf",
        f"fps=1/{interval},scale={frame_width}:-1",
        "-frames:v",
        str(frame_limit),
        "-q:v",
        "4",
        str(output_pattern),
    ]
    run_command(command)

    frames: list[SceneFrame] = []
    for index, image_path in enumerate(sorted(target_dir.glob("scene_*.jpg"))):
        timestamp = min(float(index * interval), duration) if duration > 0 else float(index * interval)
        frames.append(SceneFrame(timestamp=timestamp, image_path=str(image_path)))

    if progress_callback:
        progress_callback(f"Scene frames ready: {len(frames)} thumbnail(s).")

    return frames


def format_scene_note_for_script(note: dict[str, Any]) -> str:
    text = str(note.get("note") or "").strip()
    if not text:
        return ""

    try:
        timestamp = format_duration(float(note.get("timestamp", 0.0)))
    except (TypeError, ValueError):
        timestamp = "00:00.000"

    return f"Pada visual sekitar {timestamp}, adegan memperlihatkan {text}."


def _clean_previous_frames(output_dir: Path) -> None:
    for image_path in output_dir.glob("scene_*.jpg"):
        if image_path.is_file():
            image_path.unlink()
