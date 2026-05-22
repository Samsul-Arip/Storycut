from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .video_utils import VideoMetadata


PROJECT_EXTENSION = ".storycut.json"


@dataclass(slots=True)
class ProjectData:
    name: str
    project_dir: str
    database_path: str
    project_file: str
    video_path: str = ""
    audio_path: str = ""
    metadata: dict[str, Any] | None = None
    cut_list: list[dict[str, Any]] = field(default_factory=list)
    manual_clips: list[dict[str, Any]] = field(default_factory=list)
    timeline_clips: list[dict[str, Any]] = field(default_factory=list)
    checklist: list[dict[str, Any]] = field(default_factory=list)
    scene_notes: list[dict[str, Any]] = field(default_factory=list)
    script_text: str = ""
    script_language: str = "id"
    script_style: str = "recap"
    rough_hook_text: str = ""
    rough_cut_settings: dict[str, Any] = field(default_factory=dict)
    rough_cut_parts: list[dict[str, Any]] = field(default_factory=list)
    export_settings: dict[str, Any] = field(default_factory=dict)
    export_logs: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def set_metadata(self, metadata: VideoMetadata | None) -> None:
        self.metadata = metadata.to_dict() if metadata else None


class ProjectManager:
    def __init__(self, projects_root: str | Path) -> None:
        self.projects_root = Path(projects_root)
        self.projects_root.mkdir(parents=True, exist_ok=True)

    def create_project(self, name: str) -> ProjectData:
        clean_name = _safe_name(name)
        project_dir = _unique_project_dir(self.projects_root / clean_name)
        project_dir.mkdir(parents=True, exist_ok=False)
        _ensure_project_dirs(project_dir)

        project_file = project_dir / f"{project_dir.name}{PROJECT_EXTENSION}"
        data = ProjectData(
            name=name.strip() or project_dir.name,
            project_dir=str(project_dir),
            database_path=str(project_dir / "transcript.sqlite3"),
            project_file=str(project_file),
        )
        self.save_project(data)
        return data

    def create_project_at(self, name: str, project_file: str | Path) -> ProjectData:
        path = _with_project_extension(Path(project_file))
        project_dir = path.parent
        project_dir.mkdir(parents=True, exist_ok=True)
        _ensure_project_dirs(project_dir)

        data = ProjectData(
            name=name.strip() or _project_name_from_file(path),
            project_dir=str(project_dir),
            database_path=str(project_dir / "transcript.sqlite3"),
            project_file=str(path),
        )
        self.save_project(data)
        return data

    def load_project(self, project_file: str | Path) -> ProjectData:
        path = Path(project_file)
        if not path.exists():
            raise FileNotFoundError(f"Project file does not exist: {path}")

        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        project_dir = Path(payload.get("project_dir") or path.parent)
        database_path = Path(payload.get("database_path") or project_dir / "transcript.sqlite3")

        manual_clips = list(payload.get("manual_clips") or payload.get("cut_list") or [])
        return ProjectData(
            name=str(payload.get("name") or path.stem),
            project_dir=str(project_dir),
            database_path=str(database_path),
            project_file=str(path),
            video_path=str(payload.get("video_path") or ""),
            audio_path=str(payload.get("audio_path") or ""),
            metadata=payload.get("metadata"),
            cut_list=list(payload.get("cut_list") or manual_clips),
            manual_clips=manual_clips,
            timeline_clips=list(payload.get("timeline_clips") or []),
            checklist=list(payload.get("checklist") or []),
            scene_notes=list(payload.get("scene_notes") or []),
            script_text=str(payload.get("script_text") or ""),
            script_language=str(payload.get("script_language") or "id"),
            script_style=str(payload.get("script_style") or "recap"),
            rough_hook_text=str(payload.get("rough_hook_text") or ""),
            rough_cut_settings=dict(payload.get("rough_cut_settings") or {}),
            rough_cut_parts=list(payload.get("rough_cut_parts") or []),
            export_settings=dict(payload.get("export_settings") or {}),
            export_logs=list(payload.get("export_logs") or []),
            created_at=str(payload.get("created_at") or datetime.now().isoformat(timespec="seconds")),
            updated_at=str(payload.get("updated_at") or datetime.now().isoformat(timespec="seconds")),
        )

    def save_project(self, data: ProjectData) -> Path:
        data.updated_at = datetime.now().isoformat(timespec="seconds")
        project_dir = Path(data.project_dir)
        project_dir.mkdir(parents=True, exist_ok=True)
        path = Path(data.project_file)
        payload = asdict(data)

        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        return path


def _safe_name(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_. -]+", "", value.strip())
    clean = re.sub(r"\s+", "_", clean).strip("._ ")
    return clean or "StoryCut_Project"


def _ensure_project_dirs(project_dir: Path) -> None:
    (project_dir / "audio").mkdir(exist_ok=True)
    (project_dir / "clips").mkdir(exist_ok=True)
    (project_dir / "scene_frames").mkdir(exist_ok=True)
    (project_dir / "rough_cuts").mkdir(exist_ok=True)
    (project_dir / "thumbnails").mkdir(exist_ok=True)


def _with_project_extension(path: Path) -> Path:
    text = str(path)
    if text.lower().endswith(PROJECT_EXTENSION):
        return path
    return Path(f"{text}{PROJECT_EXTENSION}")


def _project_name_from_file(path: Path) -> str:
    name = path.name
    if name.lower().endswith(PROJECT_EXTENSION):
        name = name[: -len(PROJECT_EXTENSION)]
    return name or path.stem or "StoryCut_Project"


def _unique_project_dir(path: Path) -> Path:
    if not path.exists():
        return path

    index = 2
    while True:
        candidate = path.with_name(f"{path.name}_{index}")
        if not candidate.exists():
            return candidate
        index += 1
