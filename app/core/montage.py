from __future__ import annotations

import hashlib
import math
import random
import shutil
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .video_utils import format_duration, read_video_metadata, resolve_media_tool, run_command


ProgressCallback = Callable[[str], None]


ROUGH_CUT_COLOR_GRADES = {
    "none": "Original color",
    "review_warm": "Warm review grade",
    "cinematic": "Cinematic contrast",
    "bright": "Bright social grade",
}


CONFLICT_MARKERS = {
    "ancaman",
    "balas dendam",
    "bahaya",
    "berbahaya",
    "dendam",
    "dibunuh",
    "hilang",
    "kematian",
    "konflik",
    "membunuh",
    "menabrak",
    "mengancam",
    "menyerang",
    "misteri",
    "musuh",
    "rahasia",
    "tewas",
    "terbunuh",
}


@dataclass(slots=True)
class RoughCutConfig:
    clip_seconds: int = 5
    sample_every_seconds: int = 30
    max_clips: int = 60
    scene_output_seconds: int = 12
    target_final_seconds: int = 12 * 60
    slow_every_n_clips: int = 0
    slow_factor: float = 1.2
    hook_seconds: int = 5
    use_video_hook: bool = True
    fill_with_neighbor_clips: bool = True
    keep_audio: bool = False
    zoom_percent: int = 4
    mirror_every_n_clips: int = 2
    transition_seconds: float = 0.15
    color_grade: str = "review_warm"
    background_audio_path: str = ""
    background_audio_volume: float = 0.22
    width: int = 1280
    height: int = 720
    seed: int | None = None


@dataclass(slots=True)
class RoughCutSegment:
    index: int
    start: float
    end: float
    slow_factor: float

    @property
    def is_slow(self) -> bool:
        return self.slow_factor > 1.01


def build_conflict_hook(transcript_text: str, title: str = "StoryCut AI") -> str:
    sentences = _split_hook_sentences(transcript_text)
    conflict_sentences = [
        sentence for sentence in sentences if _has_conflict_marker(sentence)
    ][:3]

    if not conflict_sentences:
        return (
            f"{title}\n"
            "Satu kejadian besar mengubah arah cerita.\n"
            "Dari sana, karakter utama harus menghadapi konflik yang semakin berbahaya."
        )

    lines = [title, "Hook konflik:"]
    for sentence in conflict_sentences:
        lines.append(_shorten_hook_line(sentence))
    return "\n".join(lines)


def detect_conflict_hook_segment(
    transcript_records: list[Any],
    video_path: str | Path,
    hook_seconds: int = 8,
) -> RoughCutSegment | None:
    metadata = read_video_metadata(video_path)
    duration = max(0.0, metadata.duration)
    if duration <= 0:
        return None

    hook_length = min(5.0, max(2.0, float(hook_seconds or 5)))
    candidates: list[tuple[float, float]] = []

    for record in transcript_records:
        text = _record_text(record)
        if not text or not _has_conflict_marker(text):
            continue
        start = max(0.0, _record_start(record) - 1.5)
        end = min(duration, start + hook_length)
        if end - start >= 1.0:
            score = _conflict_score(text)
            candidates.append((score, start))

    if candidates:
        _, start = max(candidates, key=lambda item: (item[0], -item[1]))
    else:
        start = 0.0

    start = min(max(0.0, start), max(0.0, duration - hook_length))
    return RoughCutSegment(index=0, start=start, end=min(duration, start + hook_length), slow_factor=1.0)


def build_rough_cut_plan(
    video_path: str | Path,
    config: RoughCutConfig,
) -> list[RoughCutSegment]:
    metadata = read_video_metadata(video_path)
    duration = max(0.0, metadata.duration)
    clip_seconds = min(5, max(1, int(config.clip_seconds)))
    sample_every = max(clip_seconds, int(config.sample_every_seconds))
    target_clip_count = _target_clip_count(config)
    max_clips = target_clip_count or max(1, int(config.max_clips))

    if duration <= clip_seconds:
        return [
            RoughCutSegment(
                index=1,
                start=0.0,
                end=duration,
                slow_factor=_slow_factor_for_index(1, config),
            )
        ]

    last_start = max(0.0, duration - clip_seconds)
    if target_clip_count:
        windows = _target_duration_windows(
            duration=duration,
            clip_seconds=clip_seconds,
            clip_count=target_clip_count,
        )
    else:
        windows = []
        cursor = 0.0
        while cursor <= last_start:
            window_end = min(cursor + sample_every - clip_seconds, last_start)
            if window_end < cursor:
                window_end = cursor
            windows.append((cursor, window_end))
            cursor += sample_every

    if len(windows) > max_clips:
        windows = _evenly_pick_windows(windows, max_clips)

    seed = config.seed
    if seed is None:
        seed = _default_seed(video_path, duration, config)
    rng = random.Random(seed)

    segments: list[RoughCutSegment] = []
    for index, (start_min, start_max) in enumerate(windows, start=1):
        if start_max <= start_min:
            start = start_min
        else:
            start = rng.uniform(start_min, start_max)
        start = min(max(0.0, start), last_start)
        end = min(duration, start + clip_seconds)
        segments.append(
            RoughCutSegment(
                index=index,
                start=start,
                end=end,
                slow_factor=_slow_factor_for_index(index, config),
            )
        )

    return sorted(segments, key=lambda segment: segment.start)


def export_story_rough_cut(
    video_path: str | Path,
    output_path: str | Path,
    hook_text: str,
    config: RoughCutConfig,
    hook_segment: RoughCutSegment | None = None,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    source = Path(video_path)
    target = Path(output_path)
    if not source.exists():
        raise FileNotFoundError(f"Video file does not exist: {source}")

    target.parent.mkdir(parents=True, exist_ok=True)
    work_dir = target.parent / f"{target.stem}_work"
    _recreate_work_dir(work_dir)

    metadata = read_video_metadata(source)
    source_duration = max(0.0, metadata.duration)
    include_audio = bool(config.keep_audio and metadata.has_audio)
    background_audio = _background_audio_path(config)
    segments = build_rough_cut_plan(source, config)
    if not segments:
        raise ValueError("No rough cut segments could be created from this video.")

    if progress_callback:
        progress_callback(f"Rough cut plan: {len(segments)} chronological clip(s).")

    clip_paths: list[Path] = []
    if config.use_video_hook and hook_segment is not None:
        hook_clip = work_dir / "000_video_hook.mp4"
        _render_segment_clip(
            source,
            hook_clip,
            hook_segment,
            config,
            progress_callback,
            force_duration=None,
            source_duration=source_duration,
            include_audio=include_audio,
        )
        clip_paths.append(hook_clip)
    elif hook_text.strip():
        hook_clip = work_dir / "000_hook.mp4"
        _render_hook_clip(hook_text, hook_clip, config, progress_callback, include_audio)
        clip_paths.append(hook_clip)

    for segment in segments:
        clip_path = work_dir / f"{segment.index:03d}_{_time_for_filename(segment.start)}.mp4"
        _render_segment_clip(
            source,
            clip_path,
            segment,
            config,
            progress_callback,
            source_duration=source_duration,
            include_audio=include_audio,
        )
        clip_paths.append(clip_path)

    concat_file = work_dir / "concat.txt"
    concat_file.write_text(
        "\n".join(_concat_line(path) for path in clip_paths),
        encoding="utf-8",
    )

    if progress_callback:
        progress_callback("Combining rough cut clips into one MP4...")

    target_final = max(0.0, float(config.target_final_seconds or 0))
    concat_target = work_dir / "combined.mp4" if target_final > 0 else target

    ffmpeg = resolve_media_tool("ffmpeg")
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
            str(concat_target),
        ]
    )

    if target_final > 0:
        _finalize_target_duration(
            concat_target,
            target,
            target_final,
            include_audio,
            progress_callback,
        )

    if background_audio:
        _replace_audio_with_background_track(
            target,
            background_audio,
            config.background_audio_volume,
            progress_callback,
        )

    if progress_callback:
        progress_callback(f"Rough cut exported: {target}")
    return target


def _render_hook_clip(
    hook_text: str,
    output_path: Path,
    config: RoughCutConfig,
    progress_callback: ProgressCallback | None,
    include_audio: bool = False,
) -> None:
    if progress_callback:
        progress_callback("Rendering conflict hook title card...")

    image_path = output_path.with_suffix(".png")
    _create_hook_image(hook_text, image_path, config.width, config.height)

    ffmpeg = resolve_media_tool("ffmpeg")
    command = [
        ffmpeg,
        "-y",
        "-loop",
        "1",
        "-i",
        str(image_path),
    ]
    if include_audio:
        command.extend(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"])
    command.extend(
        [
            "-t",
            str(max(1, config.hook_seconds)),
            "-r",
            "30",
            "-vf",
            "format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
        ]
    )
    if include_audio:
        command.extend(["-c:a", "aac", "-b:a", "160k", "-shortest"])
    else:
        command.append("-an")
    command.append(str(output_path))
    run_command(command)


def _render_segment_clip(
    source: Path,
    output_path: Path,
    segment: RoughCutSegment,
    config: RoughCutConfig,
    progress_callback: ProgressCallback | None,
    force_duration: float | None = None,
    source_duration: float = 0.0,
    include_audio: bool = False,
) -> None:
    if progress_callback:
        mode = "conflict hook" if segment.index == 0 else ("slowmo" if segment.is_slow else "normal")
        progress_callback(
            f"Rendering {mode} clip {segment.index}: "
            f"{format_duration(segment.start)} to {format_duration(segment.end)}"
        )

    target_duration = force_duration
    if target_duration is None and segment.index > 0:
        target_duration = max(0.0, float(config.scene_output_seconds or 0))

    base_duration = max(0.1, segment.end - segment.start) * max(1.0, segment.slow_factor)

    if (
        segment.index > 0
        and config.fill_with_neighbor_clips
        and target_duration
        and target_duration > base_duration + 0.2
    ):
        if _render_neighbor_scene_clip(
            source,
            output_path,
            segment,
            config,
            float(target_duration),
            source_duration,
            include_audio,
            progress_callback,
        ):
            return

    render_path = output_path
    if target_duration and target_duration > base_duration + 0.2:
        render_path = output_path.with_name(f"{output_path.stem}_base{output_path.suffix}")

    _render_single_source_clip(
        source,
        render_path,
        start=segment.start,
        duration=max(0.1, segment.end - segment.start),
        slow_factor=segment.slow_factor,
        clip_index=segment.index,
        config=config,
        include_audio=include_audio,
    )

    if render_path != output_path:
        _loop_clip_to_duration(
            render_path,
            output_path,
            float(target_duration),
            include_audio,
            progress_callback,
        )


def _render_neighbor_scene_clip(
    source: Path,
    output_path: Path,
    segment: RoughCutSegment,
    config: RoughCutConfig,
    target_duration: float,
    source_duration: float,
    include_audio: bool,
    progress_callback: ProgressCallback | None,
) -> bool:
    snippets = _build_neighbor_snippets(segment, config, target_duration, source_duration)
    if len(snippets) <= 1:
        return False

    if progress_callback:
        progress_callback(
            f"Filling scene {segment.index} with {len(snippets)} nearby video snippet(s), "
            "not a single repeated clip..."
        )

    scene_dir = output_path.with_suffix("")
    scene_dir.mkdir(parents=True, exist_ok=True)
    clip_paths: list[Path] = []

    for item_index, snippet in enumerate(snippets, start=1):
        clip_path = scene_dir / f"{item_index:02d}_{_time_for_filename(snippet.start)}.mp4"
        _render_single_source_clip(
            source,
            clip_path,
            start=snippet.start,
            duration=max(0.1, snippet.end - snippet.start),
            slow_factor=snippet.slow_factor,
            clip_index=snippet.index,
            config=config,
            include_audio=include_audio,
        )
        clip_paths.append(clip_path)

    concat_file = scene_dir / "scene_concat.txt"
    concat_file.write_text(
        "\n".join(_concat_line(path) for path in clip_paths),
        encoding="utf-8",
    )

    ffmpeg = resolve_media_tool("ffmpeg")
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
            "-t",
            f"{target_duration:.3f}",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    return True


def _render_single_source_clip(
    source: Path,
    output_path: Path,
    start: float,
    duration: float,
    slow_factor: float,
    clip_index: int,
    config: RoughCutConfig,
    include_audio: bool,
) -> None:
    video_filter = _source_video_filter(
        duration=duration,
        slow_factor=slow_factor,
        config=config,
        mirror=_should_mirror_clip(clip_index, config),
    )

    ffmpeg = resolve_media_tool("ffmpeg")
    command = [
        ffmpeg,
        "-y",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{max(0.1, duration):.3f}",
        "-i",
        str(source),
    ]

    if include_audio:
        audio_filter = _source_audio_filter(duration, slow_factor, config)
        command.extend(
            [
                "-filter_complex",
                f"[0:v]{video_filter}[v];[0:a]aresample=48000,aformat=channel_layouts=stereo,{audio_filter}[a]",
                "-map",
                "[v]",
                "-map",
                "[a]",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-shortest",
            ]
        )
    else:
        command.extend(["-vf", video_filter, "-an"])

    command.extend(
        [
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            str(output_path),
        ]
    )
    run_command(command)


def _create_hook_image(text: str, output_path: Path, width: int, height: int) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required to render the hook title card. "
            "Run setup_python311_env.cmd again or install requirements.txt."
        ) from exc

    image = Image.new("RGB", (width, height), (16, 18, 22))
    draw = ImageDraw.Draw(image)
    title_font = _load_font(ImageFont, 54)
    body_font = _load_font(ImageFont, 34)
    small_font = _load_font(ImageFont, 24)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = lines[0] if lines else "Hook konflik"
    body = lines[1:] or ["Konflik utama dimulai dari satu kejadian besar."]

    margin = 90
    y = 105
    draw.text((margin, y), title[:80], fill=(245, 245, 240), font=title_font)
    y += 86
    draw.line((margin, y, width - margin, y), fill=(230, 80, 64), width=4)
    y += 38

    for raw_line in body[:4]:
        for wrapped in textwrap.wrap(raw_line, width=46):
            draw.text((margin, y), wrapped, fill=(230, 232, 228), font=body_font)
            y += 46
        y += 12

    footer = "Rough cut visual untuk review/storytelling transformatif"
    draw.text((margin, height - 76), footer, fill=(170, 176, 180), font=small_font)
    image.save(output_path)


def _loop_clip_to_duration(
    source_clip: Path,
    output_path: Path,
    target_duration: float,
    include_audio: bool,
    progress_callback: ProgressCallback | None,
) -> None:
    if progress_callback:
        progress_callback(
            f"Looping scene clip to {format_duration(target_duration)} for narration pacing..."
        )

    ffmpeg = resolve_media_tool("ffmpeg")
    run_command(
        [
            ffmpeg,
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(source_clip),
            "-t",
            f"{target_duration:.3f}",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )


def _finalize_target_duration(
    source_video: Path,
    output_path: Path,
    target_seconds: float,
    include_audio: bool,
    progress_callback: ProgressCallback | None,
) -> None:
    if progress_callback:
        progress_callback(f"Finalizing rough cut to target duration: {format_duration(target_seconds)}")

    source_duration = read_video_metadata(source_video).duration
    if source_duration < target_seconds - 0.5 and progress_callback:
        progress_callback(
            "Generated rough cut is shorter than the target. Increase Max clips, lower "
            "Sample every, or lower Final scene duration if you need a closer match."
        )

    ffmpeg = resolve_media_tool("ffmpeg")
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source_video),
        "-t",
        f"{target_seconds:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-movflags",
        "+faststart",
    ]
    if include_audio:
        command.extend(["-c:a", "aac", "-b:a", "160k"])
    else:
        command.append("-an")
    command.append(str(output_path))
    run_command(command)


def _background_audio_path(config: RoughCutConfig) -> Path | None:
    raw_path = str(config.background_audio_path or "").strip().strip('"')
    if not raw_path:
        return None

    path = Path(raw_path)
    if not path.exists():
        raise FileNotFoundError(f"Background music file does not exist: {path}")
    return path


def _replace_audio_with_background_track(
    video_path: Path,
    background_audio: Path,
    volume: float,
    progress_callback: ProgressCallback | None,
) -> None:
    if progress_callback:
        progress_callback("Replacing source audio with selected background music...")

    temp_output = video_path.with_name(f"{video_path.stem}_with_music{video_path.suffix}")
    if temp_output.exists():
        temp_output.unlink()

    ffmpeg = resolve_media_tool("ffmpeg")
    safe_volume = min(1.0, max(0.0, float(volume or 0.0)))
    run_command(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-stream_loop",
            "-1",
            "-i",
            str(background_audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-shortest",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-af",
            f"volume={safe_volume:.3f}",
            "-movflags",
            "+faststart",
            str(temp_output),
        ]
    )
    temp_output.replace(video_path)


def _build_neighbor_snippets(
    segment: RoughCutSegment,
    config: RoughCutConfig,
    target_duration: float,
    source_duration: float,
) -> list[RoughCutSegment]:
    if source_duration <= 0:
        return [segment]

    clip_seconds = min(5.0, max(0.5, float(config.clip_seconds or 5)))
    slow_factor = max(1.0, float(segment.slow_factor))
    step = max(0.6, clip_seconds * 0.8)
    max_start = max(0.0, source_duration - 0.5)
    remaining_output = max(0.1, target_duration)
    starts: list[float] = []

    cursor = max(0.0, segment.start)
    while remaining_output > 0.25 and cursor < source_duration - 0.25:
        starts.append(cursor)
        remaining_output -= min(clip_seconds, max(0.1, source_duration - cursor)) * slow_factor
        cursor += step

    back_cursor = max(0.0, segment.start - step)
    while remaining_output > 0.25 and back_cursor >= 0:
        starts.insert(0, back_cursor)
        remaining_output -= min(clip_seconds, max(0.1, source_duration - back_cursor)) * slow_factor
        back_cursor -= step

    unique_starts = sorted({round(min(max_start, max(0.0, start)), 3) for start in starts})
    snippets: list[RoughCutSegment] = []
    output_so_far = 0.0
    for index, start in enumerate(unique_starts, start=1):
        if output_so_far >= target_duration - 0.05:
            break
        available = max(0.1, source_duration - start)
        needed_source_duration = max(0.1, (target_duration - output_so_far) / slow_factor)
        duration = min(clip_seconds, available, needed_source_duration)
        if duration <= 0.15:
            continue
        snippets.append(
            RoughCutSegment(
                index=segment.index * 100 + index,
                start=start,
                end=min(source_duration, start + duration),
                slow_factor=slow_factor,
            )
        )
        output_so_far += duration * slow_factor

    return snippets or [segment]


def _audio_tempo_filter(slow_factor: float) -> str:
    tempo = 1.0 / max(1.0, slow_factor)
    filters: list[str] = []
    while tempo < 0.5:
        filters.append("atempo=0.5")
        tempo /= 0.5
    while tempo > 2.0:
        filters.append("atempo=2.0")
        tempo /= 2.0
    filters.append(f"atempo={tempo:.5f}")
    return ",".join(filters)


def _source_video_filter(
    duration: float,
    slow_factor: float,
    config: RoughCutConfig,
    mirror: bool,
) -> str:
    zoom = 1.0 + (min(20, max(0, int(config.zoom_percent or 0))) / 100.0)
    filters = [
        (
            f"scale=ceil({config.width}*{zoom:.3f}/2)*2:"
            f"ceil({config.height}*{zoom:.3f}/2)*2:"
            "force_original_aspect_ratio=increase"
        ),
        f"crop={config.width}:{config.height}",
        "setsar=1",
    ]
    if mirror:
        filters.append("hflip")

    grade_filter = _color_grade_filter(config.color_grade)
    if grade_filter:
        filters.append(grade_filter)

    output_duration = max(0.1, duration * max(1.0, slow_factor))
    filters.append(f"setpts={max(1.0, slow_factor):.3f}*PTS")
    filters.extend(_fade_filters("video", output_duration, config.transition_seconds))
    filters.append("format=yuv420p")
    return ",".join(filters)


def _source_audio_filter(
    duration: float,
    slow_factor: float,
    config: RoughCutConfig,
) -> str:
    output_duration = max(0.1, duration * max(1.0, slow_factor))
    filters = [_audio_tempo_filter(max(1.0, slow_factor))]
    filters.extend(_fade_filters("audio", output_duration, config.transition_seconds))
    return ",".join(filters)


def _fade_filters(kind: str, duration: float, transition_seconds: float) -> list[str]:
    fade = min(max(0.0, float(transition_seconds or 0.0)), max(0.0, duration / 3.0))
    if fade <= 0.01:
        return []

    out_start = max(0.0, duration - fade)
    if kind == "audio":
        return [
            f"afade=t=in:st=0:d={fade:.3f}",
            f"afade=t=out:st={out_start:.3f}:d={fade:.3f}",
        ]
    return [
        f"fade=t=in:st=0:d={fade:.3f}",
        f"fade=t=out:st={out_start:.3f}:d={fade:.3f}",
    ]


def _color_grade_filter(color_grade: str) -> str:
    if color_grade == "review_warm":
        return "eq=contrast=1.06:saturation=1.12:gamma_r=1.03:gamma_b=0.96"
    if color_grade == "cinematic":
        return "eq=contrast=1.1:saturation=0.96:brightness=-0.015"
    if color_grade == "bright":
        return "eq=contrast=1.04:saturation=1.18:brightness=0.02"
    return ""


def _should_mirror_clip(index: int, config: RoughCutConfig) -> bool:
    every = int(config.mirror_every_n_clips or 0)
    if every <= 0:
        return False
    return index > 0 and index % every == 0


def _load_font(image_font_module: Any, size: int) -> Any:
    candidates = [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return image_font_module.truetype(str(path), size=size)
    return image_font_module.load_default()


def _split_hook_sentences(text: str) -> list[str]:
    import re

    prepared = " ".join(str(text or "").split())
    if not prepared:
        return []
    parts = re.split(r"(?<=[.!?])\s+", prepared)
    return [part.strip(" .!?") for part in parts if len(part.split()) >= 3]


def _has_conflict_marker(sentence: str) -> bool:
    lower = sentence.lower()
    return any(marker in lower for marker in CONFLICT_MARKERS)


def _conflict_score(text: str) -> float:
    lower = text.lower()
    score = 0.0
    for marker in CONFLICT_MARKERS:
        if marker in lower:
            score += 1.0
    score += min(2.0, len(text.split()) / 20)
    return score


def _record_text(record: Any) -> str:
    if isinstance(record, dict):
        return str(record.get("text") or "")
    return str(getattr(record, "text", "") or "")


def _record_start(record: Any) -> float:
    try:
        if isinstance(record, dict):
            return float(record.get("start", 0.0) or 0.0)
        return float(getattr(record, "start", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _shorten_hook_line(sentence: str) -> str:
    words = sentence.strip().split()
    if len(words) <= 18:
        return sentence.strip(" .")
    return " ".join(words[:18]).strip(" .") + "..."


def _slow_factor_for_index(index: int, config: RoughCutConfig) -> float:
    slow_every = int(config.slow_every_n_clips)
    if slow_every <= 0:
        return 1.0
    if index % slow_every == 0:
        return max(1.0, float(config.slow_factor))
    return 1.0


def _target_clip_count(config: RoughCutConfig) -> int:
    target_final = max(0, int(config.target_final_seconds or 0))
    if target_final <= 0:
        return 0

    hook_seconds = max(0, int(config.hook_seconds or 0)) if config.use_video_hook else 0
    scene_seconds = max(1, int(config.scene_output_seconds or config.clip_seconds or 5))
    available = max(1, target_final - hook_seconds)
    return max(1, math.ceil(available / scene_seconds))


def _target_duration_windows(
    duration: float,
    clip_seconds: float,
    clip_count: int,
) -> list[tuple[float, float]]:
    last_start = max(0.0, duration - clip_seconds)
    if clip_count <= 1:
        return [(0.0, last_start)]

    windows: list[tuple[float, float]] = []
    spacing = last_start / max(1, clip_count - 1)
    half_width = max(0.0, min(spacing * 0.35, max(0.0, clip_seconds * 0.8)))

    for index in range(clip_count):
        center = min(last_start, max(0.0, index * spacing))
        start_min = max(0.0, center - half_width)
        start_max = min(last_start, center + half_width)
        windows.append((start_min, start_max))
    return windows


def _evenly_pick_windows(
    windows: list[tuple[float, float]],
    max_clips: int,
) -> list[tuple[float, float]]:
    if max_clips >= len(windows):
        return windows
    if max_clips == 1:
        return [windows[0]]

    last = len(windows) - 1
    picked_indices = {
        round(index * last / (max_clips - 1))
        for index in range(max_clips)
    }
    return [windows[index] for index in sorted(picked_indices)]


def _default_seed(video_path: str | Path, duration: float, config: RoughCutConfig) -> int:
    payload = f"{Path(video_path).resolve()}|{duration:.3f}|{config.clip_seconds}|{config.sample_every_seconds}"
    digest = hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()
    return int(digest[:12], 16)


def _time_for_filename(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}-{minutes:02d}-{secs:02d}-{millis:03d}"


def _concat_line(path: Path) -> str:
    safe_path = path.resolve().as_posix().replace("'", "'\\''")
    return f"file '{safe_path}'"


def _recreate_work_dir(work_dir: Path) -> None:
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
