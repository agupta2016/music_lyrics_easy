"""Speech-to-text with Whisper (via faster-whisper, runs locally)."""

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    language: str
    segments: list[Segment]


class Transcriber(Protocol):
    def transcribe(self, audio_path: Path) -> Transcript: ...


class WhisperTranscriber:
    """Loads the Whisper model once, on first use, and reuses it across jobs."""

    def __init__(self, model_size: str = "small", device: str = "auto"):
        self.model_size = model_size
        self.device = device
        self._model = None
        self._lock = threading.Lock()

    def _get_model(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(self.model_size, device=self.device, compute_type="auto")
            return self._model

    def transcribe(self, audio_path: Path) -> Transcript:
        model = self._get_model()
        # vad_filter skips long instrumental stretches, which otherwise produce hallucinated text.
        segments, info = model.transcribe(str(audio_path), vad_filter=True, beam_size=5)
        result = [
            Segment(start=round(s.start, 2), end=round(s.end, 2), text=s.text.strip())
            for s in segments
            if s.text.strip()
        ]
        return Transcript(language=info.language, segments=result)
