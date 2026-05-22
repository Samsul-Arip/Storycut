from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .transcriber import TranscriptSegment


ProgressCallback = Callable[[str], None]


class TranslationError(RuntimeError):
    """Raised when local translation to Indonesian cannot complete."""


@dataclass(slots=True)
class TranslationConfig:
    source_language: str = "en"
    target_language: str = "id"
    chunk_words: int = 90


class LocalIndonesianTranslator:
    """Offline translator wrapper. Uses Argos Translate when its model is installed."""

    def __init__(self, config: TranslationConfig | None = None) -> None:
        self.config = config or TranslationConfig()
        self._translation: object | None = None

    def translate_segments(
        self,
        segments: list[TranscriptSegment],
        progress_callback: ProgressCallback | None = None,
    ) -> list[TranscriptSegment]:
        if not segments:
            return []

        if progress_callback:
            progress_callback("Loading local English to Indonesian translation model...")
        self._translation = _get_argos_translation(self.config)

        translated: list[TranscriptSegment] = []
        for index, segment in enumerate(segments, start=1):
            text = self.translate_text(segment.text)
            translated.append(TranscriptSegment(start=segment.start, end=segment.end, text=text))
            if progress_callback and (index == 1 or index % 10 == 0):
                progress_callback(f"Translating to Indonesian... {index}/{len(segments)} segments")

        if progress_callback:
            progress_callback(f"Translation complete: {len(translated)} Indonesian segments.")
        return translated

    def translate_text(self, text: str) -> str:
        chunks = _chunk_text(text, self.config.chunk_words)
        if self._translation is None:
            self._translation = _get_argos_translation(self.config)
        translated_chunks = [
            _translate_with_argos(chunk, self._translation)
            for chunk in chunks
        ]
        return " ".join(chunk for chunk in translated_chunks if chunk).strip()


def _get_argos_translation(config: TranslationConfig) -> object:
    try:
        import argostranslate.translate
    except ImportError as exc:
        raise TranslationError(_install_help("Argos Translate is not installed.")) from exc

    try:
        languages = argostranslate.translate.get_installed_languages()
        source = next(
            (language for language in languages if language.code == config.source_language),
            None,
        )
        target = next(
            (language for language in languages if language.code == config.target_language),
            None,
        )
        if source is None or target is None:
            raise TranslationError(
                _install_help(
                    "The English to Indonesian translation model is not installed."
                )
            )
        return source.get_translation(target)
    except Exception as exc:
        if isinstance(exc, TranslationError):
            raise
        raise TranslationError(
            _install_help(
                "The English to Indonesian translation model is not installed or could not run."
            )
        ) from exc


def _translate_with_argos(text: str, translation: object) -> str:
    try:
        translated = translation.translate(text)
    except Exception as exc:
        raise TranslationError(
            _install_help("The English to Indonesian translation model could not translate text.")
        ) from exc

    translated = " ".join(translated.split())
    if not translated:
        raise TranslationError("Translation returned empty text.")
    return translated


def _chunk_text(text: str, chunk_words: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    size = max(20, chunk_words)
    return [" ".join(words[index : index + size]) for index in range(0, len(words), size)]


def _install_help(reason: str) -> str:
    return (
        f"{reason}\n\n"
        "Install local translation support first:\n"
        "1. Close StoryCut AI.\n"
        "2. Double-click install_translation_support.cmd in the storycut_ai folder.\n"
        "3. Restart StoryCut AI.\n\n"
        "This downloads an offline English -> Indonesian translation model for Argos Translate."
    )
