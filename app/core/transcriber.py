from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


ProgressCallback = Callable[[str], None]


class TranscriptionError(RuntimeError):
    """Raised when local Whisper transcription cannot complete."""


@dataclass(slots=True)
class TranscriptSegment:
    start: float
    end: float
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WhisperTranscriber:
    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type

    def transcribe(
        self,
        audio_path: str | Path,
        language: str | None = None,
        task: str = "transcribe",
        condition_on_previous_text: bool = True,
        progress_callback: ProgressCallback | None = None,
    ) -> list[TranscriptSegment]:
        source = Path(audio_path)
        if not source.exists():
            raise FileNotFoundError(f"Audio file does not exist: {source}")

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscriptionError(
                "faster-whisper is not installed. Install requirements.txt first."
            ) from exc

        if progress_callback:
            progress_callback(f"Loading local Whisper model '{self.model_size}'...")

        try:
            model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
            segments_iter, info = model.transcribe(
                str(source),
                beam_size=5,
                language=language or None,
                task=task,
                vad_filter=True,
                condition_on_previous_text=condition_on_previous_text,
            )

            total_duration = float(getattr(info, "duration", 0.0) or 0.0)
            transcript: list[TranscriptSegment] = []
            for index, segment in enumerate(segments_iter, start=1):
                text = str(segment.text).strip()
                if not text:
                    continue
                transcript.append(
                    TranscriptSegment(
                        start=float(segment.start),
                        end=float(segment.end),
                        text=text,
                    )
                )
                if progress_callback:
                    if total_duration > 0:
                        pct = min(100.0, (float(segment.end) / total_duration) * 100)
                        progress_callback(f"Transcribing... {pct:.1f}% ({index} segments)")
                    elif index % 10 == 0:
                        progress_callback(f"Transcribing... {index} segments")

            if progress_callback:
                progress_callback(f"Transcription complete: {len(transcript)} segments.")
            return transcript
        except Exception as exc:
            if isinstance(exc, TranscriptionError):
                raise
            raise TranscriptionError(str(exc)) from exc
