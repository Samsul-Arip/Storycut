from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any


class MediaToolError(RuntimeError):
    """Raised when FFmpeg or FFprobe cannot process a media file."""


@dataclass(slots=True)
class VideoMetadata:
    duration: float
    file_size: int
    width: int
    height: int
    fps: float
    has_audio: bool
    video_codec: str
    audio_codec: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VideoMetadata":
        return cls(
            duration=float(data.get("duration", 0.0)),
            file_size=int(data.get("file_size", 0)),
            width=int(data.get("width", 0)),
            height=int(data.get("height", 0)),
            fps=float(data.get("fps", 0.0)),
            has_audio=bool(data.get("has_audio", False)),
            video_codec=str(data.get("video_codec", "")),
            audio_codec=str(data.get("audio_codec", "")),
        )


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    run_kwargs: dict[str, Any] = {
        "check": True,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        run_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        return subprocess.run(command, **run_kwargs)
    except FileNotFoundError as exc:
        raise MediaToolError(
            f"Required media tool was not found: {command[0]}. "
            "Install FFmpeg and make sure ffmpeg/ffprobe are on PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        details = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise MediaToolError(details) from exc


def read_video_metadata(video_path: str | Path, ffprobe_path: str = "ffprobe") -> VideoMetadata:
    source = Path(video_path)
    if not source.exists():
        raise FileNotFoundError(f"Video file does not exist: {source}")

    ffprobe = resolve_media_tool(ffprobe_path)
    command = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(source),
    ]
    result = run_command(command)

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaToolError("ffprobe returned invalid JSON output.") from exc

    streams = payload.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    format_info = payload.get("format", {})

    duration = _safe_float(format_info.get("duration"))
    if duration <= 0:
        duration = _safe_float(video_stream.get("duration"))

    return VideoMetadata(
        duration=duration,
        file_size=source.stat().st_size,
        width=int(video_stream.get("width") or 0),
        height=int(video_stream.get("height") or 0),
        fps=_parse_fps(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")),
        has_audio=bool(audio_stream),
        video_codec=str(video_stream.get("codec_name") or "unknown"),
        audio_codec=str(audio_stream.get("codec_name") or "none"),
    )


def resolve_media_tool(tool_name: str) -> str:
    """Find ffmpeg/ffprobe from PATH, bundled app folders, or common WinGet installs."""
    requested = Path(tool_name)
    if requested.is_file():
        return str(requested)

    from_path = shutil.which(tool_name)
    if from_path:
        return from_path

    exe_name = tool_name if tool_name.lower().endswith(".exe") else f"{tool_name}.exe"
    for directory in _candidate_media_tool_dirs():
        candidate = directory / exe_name
        if candidate.is_file():
            return str(candidate)

    raise MediaToolError(
        f"Required media tool was not found: {tool_name}. "
        "Install FFmpeg and make sure ffmpeg/ffprobe are on PATH, "
        "or place ffmpeg.exe and ffprobe.exe in a local bin folder."
    )


def format_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"
    return f"{minutes:02d}:{secs:06.3f}"


def parse_timestamp(value: str | float | int) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, float(value))

    text = str(value).strip()
    if not text:
        raise ValueError("Timestamp cannot be empty.")

    if ":" not in text:
        return max(0.0, float(text))

    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError(f"Invalid timestamp: {value}")

    parts = ["0"] * (3 - len(parts)) + parts
    hours, minutes, seconds = parts
    return max(0.0, int(hours) * 3600 + int(minutes) * 60 + float(seconds))


def format_file_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def metadata_to_text(metadata: VideoMetadata | None) -> str:
    if metadata is None:
        return "No video metadata loaded."

    resolution = f"{metadata.width}x{metadata.height}" if metadata.width and metadata.height else "unknown"
    return "\n".join(
        [
            f"Duration: {format_duration(metadata.duration)}",
            f"File size: {format_file_size(metadata.file_size)}",
            f"Resolution: {resolution}",
            f"FPS: {metadata.fps:.3f}" if metadata.fps else "FPS: unknown",
            f"Audio: {'available' if metadata.has_audio else 'not detected'}",
            f"Video codec: {metadata.video_codec}",
            f"Audio codec: {metadata.audio_codec}",
        ]
    )


def _parse_fps(raw_value: Any) -> float:
    if not raw_value:
        return 0.0
    try:
        fraction = Fraction(str(raw_value))
        if fraction.denominator == 0:
            return 0.0
        return float(fraction)
    except (ValueError, ZeroDivisionError):
        return _safe_float(raw_value)


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _candidate_media_tool_dirs() -> list[Path]:
    dirs: list[Path] = []

    app_root = Path(__file__).resolve().parents[2]
    dirs.extend(
        [
            app_root / "bin",
            app_root.parent / "bin",
            Path.cwd() / "bin",
            Path.cwd(),
        ]
    )

    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        dirs.extend([executable_dir, executable_dir / "bin"])
        bundle_dir = Path(getattr(sys, "_MEIPASS", executable_dir))
        dirs.extend([bundle_dir, bundle_dir / "bin"])

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        winget_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if winget_root.exists():
            dirs.extend(path for path in winget_root.glob("Gyan.FFmpeg*/*/bin") if path.is_dir())
            dirs.extend(path for path in winget_root.glob("BtbN.FFmpeg*/*/bin") if path.is_dir())

    program_files = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
    for base in filter(None, program_files):
        root = Path(str(base))
        dirs.extend([root / "FFmpeg" / "bin", root / "ffmpeg" / "bin"])

    unique_dirs: list[Path] = []
    seen: set[str] = set()
    for directory in dirs:
        key = str(directory).lower()
        if key not in seen:
            unique_dirs.append(directory)
            seen.add(key)
    return unique_dirs
