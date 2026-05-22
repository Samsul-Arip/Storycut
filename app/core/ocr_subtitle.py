from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

from .transcriber import TranscriptSegment
from .video_utils import MediaToolError, resolve_media_tool


ProgressCallback = Callable[[str], None]


class OCRError(RuntimeError):
    """Raised when burned-in subtitle OCR cannot complete."""


@dataclass(slots=True)
class OCRSubtitleConfig:
    sample_interval: float = 1.0
    bottom_crop_ratio: float = 0.32
    language: str = "ind+eng"
    similarity_threshold: float = 0.82


def ocr_burned_subtitles(
    video_path: str | Path,
    output_dir: str | Path,
    config: OCRSubtitleConfig | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[TranscriptSegment]:
    cfg = config or OCRSubtitleConfig()
    source = Path(video_path)
    if not source.exists():
        raise FileNotFoundError(f"Video file does not exist: {source}")

    _configure_tesseract()

    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise OCRError(
            "OCR dependencies are not installed. Run: pip install -r requirements.txt"
        ) from exc

    frames_dir = Path(output_dir) / "ocr_frames"
    _prepare_directory(frames_dir)
    _extract_bottom_frames(source, frames_dir, cfg, progress_callback=progress_callback)

    frames = sorted(frames_dir.glob("frame_*.png"))
    if not frames:
        raise OCRError("No OCR frames were extracted from the video.")

    if progress_callback:
        progress_callback(f"Running OCR on {len(frames)} sampled frames...")

    raw_segments: list[TranscriptSegment] = []
    for frame_number, frame_path in enumerate(frames):
        timestamp = frame_number * cfg.sample_interval
        with Image.open(frame_path) as image:
            text = _ocr_image(pytesseract, image, cfg.language)
        text = _clean_ocr_text(text)
        if not text:
            continue
        raw_segments.append(
            TranscriptSegment(
                start=timestamp,
                end=timestamp + cfg.sample_interval,
                text=text,
            )
        )
        if progress_callback and frame_number and frame_number % 20 == 0:
            progress_callback(f"OCR progress: {frame_number}/{len(frames)} frames")

    segments = _merge_repeated_ocr_segments(raw_segments, cfg.similarity_threshold)
    if not segments:
        raise OCRError(
            "OCR did not find readable subtitle text. Try using an external subtitle file, "
            "or use a video with clearer/larger subtitles."
        )

    if progress_callback:
        progress_callback(f"OCR complete: {len(segments)} subtitle segments.")
    return segments


def _configure_tesseract() -> None:
    try:
        import pytesseract
    except ImportError:
        return

    configured = os.environ.get("TESSERACT_CMD")
    candidates = [
        configured,
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            pytesseract.pytesseract.tesseract_cmd = str(candidate)
            return


def _extract_bottom_frames(
    video_path: Path,
    frames_dir: Path,
    config: OCRSubtitleConfig,
    progress_callback: ProgressCallback | None = None,
) -> None:
    if progress_callback:
        progress_callback("Extracting bottom subtitle area frames with FFmpeg...")

    ffmpeg = resolve_media_tool("ffmpeg")
    crop_ratio = min(0.6, max(0.12, config.bottom_crop_ratio))
    fps = 1.0 / max(0.2, config.sample_interval)
    output_pattern = frames_dir / "frame_%06d.png"

    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vf",
        f"fps={fps:.4f},crop=iw:floor(ih*{crop_ratio}/2)*2:0:ih-floor(ih*{crop_ratio}/2)*2",
        str(output_pattern),
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


def _ocr_image(pytesseract_module: object, image: object, language: str) -> str:
    config = "--psm 6"
    try:
        return pytesseract_module.image_to_string(image, lang=language, config=config)
    except Exception as exc:
        if language != "eng":
            try:
                return pytesseract_module.image_to_string(image, lang="eng", config=config)
            except Exception as fallback_exc:
                raise OCRError(_ocr_runtime_help(fallback_exc)) from fallback_exc
        raise OCRError(_ocr_runtime_help(exc)) from exc


def _ocr_runtime_help(exc: Exception) -> str:
    return (
        "OCR could not run. Install Tesseract OCR for Windows and OCR Python dependencies.\n\n"
        "Recommended:\n"
        "1. Run install_ocr_support.ps1 from the storycut_ai folder.\n"
        "2. Restart StoryCut AI.\n\n"
        f"Details: {exc}"
    )


def _clean_ocr_text(text: str) -> str:
    clean = text.replace("\n", " ")
    clean = re.sub(r"[^0-9A-Za-zÀ-ÿ.,!?'\- ]+", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    clean = clean.strip("-.,:; ")
    if len(clean) < 4:
        return ""
    if _looks_like_ocr_noise(clean):
        return ""
    if clean[-1] not in ".!?":
        clean += "."
    return clean[0].upper() + clean[1:]


def _looks_like_ocr_noise(text: str) -> bool:
    letters = re.findall(r"[A-Za-zÀ-ÿ]", text)
    if len(letters) < 3:
        return True
    words = text.split()
    if len(words) <= 2 and len(text) < 12:
        return True
    return False


def _merge_repeated_ocr_segments(
    segments: list[TranscriptSegment],
    similarity_threshold: float,
) -> list[TranscriptSegment]:
    if not segments:
        return []

    merged: list[TranscriptSegment] = []
    current = segments[0]

    for segment in segments[1:]:
        similarity = SequenceMatcher(None, current.text.lower(), segment.text.lower()).ratio()
        if similarity >= similarity_threshold:
            current = TranscriptSegment(
                start=current.start,
                end=segment.end,
                text=_prefer_better_text(current.text, segment.text),
            )
            continue
        merged.append(current)
        current = segment

    merged.append(current)
    return merged


def _prefer_better_text(left: str, right: str) -> str:
    if len(right) > len(left) + 4:
        return right
    return left


def _prepare_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
