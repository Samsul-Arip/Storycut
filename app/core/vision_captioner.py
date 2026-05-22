from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .translator import LocalIndonesianTranslator, TranslationError


ProgressCallback = Callable[[str], None]


class VisionCaptionError(RuntimeError):
    """Raised when local visual captioning cannot run."""


DEFAULT_VISION_MODEL = "Salesforce/blip-image-captioning-base"


@dataclass(slots=True)
class VisionCaptionConfig:
    model_name_or_path: str = DEFAULT_VISION_MODEL
    max_new_tokens: int = 36
    target_language: str = "id"
    fill_empty_only: bool = True
    local_files_only: bool = True


def auto_caption_scene_notes(
    notes: list[dict[str, Any]],
    config: VisionCaptionConfig | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[dict[str, Any]]:
    cfg = config or VisionCaptionConfig(
        model_name_or_path=os.environ.get(
            "STORYCUT_VISION_MODEL",
            DEFAULT_VISION_MODEL,
        ),
        local_files_only=os.environ.get("STORYCUT_ALLOW_MODEL_DOWNLOAD", "").lower()
        not in {"1", "true", "yes"},
    )

    updated = [dict(note) for note in notes]
    candidates = [
        (index, note)
        for index, note in enumerate(updated)
        if _should_caption(note, cfg.fill_empty_only)
    ]
    if not candidates:
        return updated

    if progress_callback:
        progress_callback("Loading local visual scene caption model...")
    captioner = LocalVisionCaptioner(cfg)

    translator: LocalIndonesianTranslator | None = None
    translation_failed = False
    if cfg.target_language == "id":
        try:
            translator = LocalIndonesianTranslator()
        except Exception:
            translator = None

    total = len(candidates)
    for number, (index, note) in enumerate(candidates, start=1):
        image_path = str(note.get("image_path") or "")
        if progress_callback:
            progress_callback(f"Describing scene frame... {number}/{total}")

        caption = captioner.caption_image(image_path)
        caption = _clean_caption(caption)
        note_text = caption

        if cfg.target_language == "id" and translator is not None:
            try:
                note_text = translator.translate_text(caption)
            except TranslationError:
                translation_failed = True
                translator = None

        updated[index]["note"] = _clean_note(note_text)
        updated[index]["auto_note"] = True
        updated[index]["caption_source"] = "blip"

    if progress_callback:
        if translation_failed:
            progress_callback(
                "Visual notes were generated, but Indonesian translation was unavailable; "
                "some notes may remain in English."
            )
        progress_callback(f"Auto visual notes complete: {total} frame(s) described.")

    return updated


class LocalVisionCaptioner:
    def __init__(self, config: VisionCaptionConfig) -> None:
        self.config = config
        try:
            import torch
            from transformers import BlipForConditionalGeneration, BlipProcessor
        except ImportError as exc:
            raise VisionCaptionError(
                _install_help("Local vision dependencies are not installed.")
            ) from exc

        self._torch = torch
        try:
            self._processor = BlipProcessor.from_pretrained(
                config.model_name_or_path,
                local_files_only=config.local_files_only,
            )
            self._model = BlipForConditionalGeneration.from_pretrained(
                config.model_name_or_path,
                local_files_only=config.local_files_only,
            )
        except OSError as exc:
            raise VisionCaptionError(
                _install_help("The local BLIP vision model was not found.")
            ) from exc

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._model.to(self._device)
        self._model.eval()

    def caption_image(self, image_path: str | Path) -> str:
        try:
            from PIL import Image
        except ImportError as exc:
            raise VisionCaptionError(
                _install_help("Pillow is not installed, so images cannot be opened.")
            ) from exc

        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Scene frame does not exist: {path}")

        image = Image.open(path).convert("RGB")
        inputs = self._processor(image, return_tensors="pt").to(self._device)
        with self._torch.inference_mode():
            output = self._model.generate(
                **inputs,
                max_new_tokens=self.config.max_new_tokens,
            )
        return str(self._processor.decode(output[0], skip_special_tokens=True))


def _should_caption(note: dict[str, Any], fill_empty_only: bool) -> bool:
    image_path = str(note.get("image_path") or "")
    if not image_path or not Path(image_path).exists():
        return False
    if not fill_empty_only:
        return True
    return not str(note.get("note") or "").strip()


def _clean_caption(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip(" .")
    prefixes = (
        "a picture of ",
        "a photo of ",
        "an image of ",
        "there is ",
        "there are ",
    )
    lowered = cleaned.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break
    return cleaned.strip(" .") or "a scene from the video"


def _clean_note(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip(" .")
    return cleaned[:1].lower() + cleaned[1:] if cleaned else ""


def _install_help(reason: str) -> str:
    return (
        f"{reason}\n\n"
        "Install local vision support first:\n"
        "1. Close StoryCut AI.\n"
        "2. Double-click install_vision_support.cmd in the storycut_ai folder.\n"
        "3. Restart StoryCut AI.\n\n"
        "This installs local image captioning dependencies and downloads the BLIP model "
        "so frame descriptions can run locally."
    )
