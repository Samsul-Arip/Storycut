from __future__ import annotations

import array
import math
import os
import subprocess
import sys
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


def read_audio_waveform(
    video_path: str | Path,
    ffmpeg_path: str = "ffmpeg",
    sample_rate: int = 4000,
    max_points: int = 12000,
) -> list[float]:
    source = Path(video_path)
    if not source.exists():
        raise FileNotFoundError(f"Video file does not exist: {source}")

    ffmpeg = resolve_media_tool(ffmpeg_path)
    command = [
        ffmpeg,
        "-v",
        "error",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(max(800, int(sample_rate))),
        "-f",
        "s16le",
        "pipe:1",
    ]
    run_kwargs: dict[str, object] = {
        "check": True,
        "capture_output": True,
    }
    if os.name == "nt":
        run_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        result = subprocess.run(command, **run_kwargs)
    except FileNotFoundError as exc:
        raise MediaToolError(
            "FFmpeg was not found. Install FFmpeg and make sure ffmpeg is on PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        details = exc.stderr.decode("utf-8", errors="replace").strip() or str(exc)
        raise MediaToolError(details) from exc

    raw_audio = result.stdout
    if len(raw_audio) < 2:
        return []
    if len(raw_audio) % 2:
        raw_audio = raw_audio[:-1]

    samples = array.array("h")
    samples.frombytes(raw_audio)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return []

    points = max(1, int(max_points))
    samples_per_point = max(1, math.ceil(len(samples) / points))
    peaks: list[float] = []
    for start in range(0, len(samples), samples_per_point):
        window = samples[start : start + samples_per_point]
        peak = max((abs(value) for value in window), default=0) / 32768.0
        peaks.append(min(1.0, peak))

    max_peak = max(peaks, default=0.0)
    if max_peak <= 0:
        return peaks
    return [min(1.0, (peak / max_peak) ** 0.65) for peak in peaks]
