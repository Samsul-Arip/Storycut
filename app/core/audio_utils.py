from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from .video_utils import MediaToolError, resolve_media_tool


ProgressCallback = Callable[[str], None]


def extract_audio(
    video_path: str | Path,
    output_path: str | Path,
    ffmpeg_path: str = "ffmpeg",
    sample_rate: int = 16000,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    source = Path(video_path)
    target = Path(output_path)

    if not source.exists():
        raise FileNotFoundError(f"Video file does not exist: {source}")

    target.parent.mkdir(parents=True, exist_ok=True)
    if progress_callback:
        progress_callback(f"Extracting mono WAV audio to {target.name}...")

    ffmpeg = resolve_media_tool(ffmpeg_path)
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "wav",
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
        raise MediaToolError(details) from exc

    if progress_callback:
        progress_callback("Audio extraction complete.")
    return target
