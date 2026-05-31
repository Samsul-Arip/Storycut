from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from app.core.cutter import ClipItem


EditorState = dict[str, list[dict[str, Any]]]


@dataclass(frozen=True)
class TimelineDurationConfig:
    target_final_seconds: float = 0.0
    scene_output_seconds: float = 5.0
    hook_seconds: float = 5.0
    clip_seconds: float = 5.0


class EditorHistory:
    def __init__(self, limit: int = 80) -> None:
        self._limit = max(1, limit)
        self._undo_stack: list[EditorState] = []
        self._redo_stack: list[EditorState] = []

    def reset(self, state: EditorState) -> None:
        self._undo_stack = [_copy_editor_state(state)]
        self._redo_stack = []

    def push(self, state: EditorState) -> bool:
        snapshot = _copy_editor_state(state)
        if self._undo_stack and self._undo_stack[-1] == snapshot:
            return False
        self._undo_stack.append(snapshot)
        self._undo_stack = self._undo_stack[-self._limit :]
        self._redo_stack.clear()
        return True

    def undo(self) -> EditorState | None:
        if len(self._undo_stack) < 2:
            return None
        current = self._undo_stack.pop()
        self._redo_stack.append(current)
        return _copy_editor_state(self._undo_stack[-1])

    def redo(self) -> EditorState | None:
        if not self._redo_stack:
            return None
        state = self._redo_stack.pop()
        self._undo_stack.append(state)
        return _copy_editor_state(state)


class EditorViewModel:
    def __init__(self, history_limit: int = 80) -> None:
        self.history = EditorHistory(limit=history_limit)
        self._restoring_history = False

    @property
    def is_restoring_history(self) -> bool:
        return self._restoring_history

    @contextmanager
    def restoring_history(self) -> Iterator[None]:
        self._restoring_history = True
        try:
            yield
        finally:
            self._restoring_history = False

    def capture_state(
        self,
        manual_clips: list[dict[str, Any]],
        timeline_clips: list[dict[str, Any]],
    ) -> EditorState:
        return {
            "manual_clips": _copy_clip_list(manual_clips),
            "timeline_clips": _copy_clip_list(timeline_clips),
        }

    def timeline_with_output_durations(
        self,
        clips: list[dict[str, Any]],
        config: TimelineDurationConfig,
    ) -> list[dict[str, Any]]:
        if not clips:
            return []

        target_remaining = max(0.0, float(config.target_final_seconds or 0.0))
        scene_duration = max(
            0.1,
            float(config.scene_output_seconds or config.clip_seconds or 5.0),
        )
        hook_duration = max(0.1, float(config.hook_seconds or config.clip_seconds or 5.0))
        normalized: list[dict[str, Any]] = []

        for clip in clips:
            item = dict(clip)
            source_duration = self.clip_source_duration(item)
            output_duration = self.clip_output_duration(item)

            if output_duration <= 0:
                if str(item.get("kind") or "") == "rough":
                    role = str(item.get("timeline_role") or "")
                    is_hook = role == "hook" or bool(item.get("is_hook"))
                    planned = hook_duration if is_hook else scene_duration
                    if target_remaining > 0:
                        planned = min(planned, target_remaining)
                    output_duration = max(0.1, planned)
                else:
                    output_duration = max(0.1, source_duration)

            if str(item.get("kind") or "") == "rough" and target_remaining > 0:
                target_remaining = max(0.0, target_remaining - output_duration)

            item["output_duration"] = round(max(0.1, output_duration), 3)
            normalized.append(item)

        return normalized

    def timeline_total_duration(self, clips: list[dict[str, Any]]) -> float:
        total = 0.0
        for clip in clips:
            output_duration = self.clip_output_duration(clip)
            if output_duration <= 0:
                output_duration = self.clip_source_duration(clip)
            total += max(0.0, output_duration)
        return total

    def clip_source_duration(self, clip: dict[str, Any]) -> float:
        if self.is_photo_clip(clip):
            return self.clip_output_duration(clip) or 3.0
        try:
            item = ClipItem.from_dict(clip)
            return max(0.0, item.end - item.start)
        except (TypeError, ValueError):
            return 0.0

    def clip_output_duration(self, clip: dict[str, Any]) -> float:
        for key in ("output_duration", "output_duration_seconds"):
            try:
                value = float(clip.get(key, 0.0) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        if self.is_photo_clip(clip):
            return 3.0
        try:
            slowmo = float(clip.get("slowmo_factor", 1.0) or 1.0)
        except (TypeError, ValueError):
            slowmo = 1.0
        if slowmo > 1.0:
            return self.clip_source_duration(clip) * slowmo
        return 0.0

    @staticmethod
    def is_photo_clip(clip: dict[str, Any]) -> bool:
        kind = str(clip.get("media_type") or clip.get("kind") or "").strip().lower()
        return kind in {"photo", "still", "image"} or bool(clip.get("image_path"))


def safe_project_filename(name: str) -> str:
    clean = "".join(char if char.isalnum() or char in " ._-" else "_" for char in name.strip())
    clean = "_".join(clean.split()).strip("._- ")
    return clean or "StoryCut_Project"


def time_for_filename(seconds: float) -> str:
    total = int(round(max(0.0, seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}-{minutes:02d}-{secs:02d}"


def _copy_editor_state(state: EditorState) -> EditorState:
    return {
        "manual_clips": _copy_clip_list(state.get("manual_clips", [])),
        "timeline_clips": _copy_clip_list(state.get("timeline_clips", [])),
    }


def _copy_clip_list(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(item) for item in items]

