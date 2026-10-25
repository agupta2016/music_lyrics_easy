"""Speech-to-text with Whisper (via faster-whisper, runs locally)."""

import logging
import shutil
import subprocess
import sys
import tempfile
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


log = logging.getLogger(__name__)


def demucs_available() -> bool:
    try:
        import demucs  # noqa: F401
    except ImportError:
        return False
    return True


class VocalIsolatingTranscriber:
    """Runs Demucs to strip the music out, then hands the vocals to another transcriber.

    Whisper is much more accurate on a clean vocal track than on a full mix.
    If Demucs fails, it falls back to transcribing the original audio.
    """

    def __init__(self, inner: Transcriber, model: str = "htdemucs"):
        self.inner = inner
        self.model = model

    def isolate(self, audio_path: Path, out_dir: Path) -> Path:
        subprocess.run(
            [sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", self.model,
             "-o", str(out_dir), str(audio_path)],
            check=True,
            capture_output=True,
        )
        vocals = out_dir / self.model / audio_path.stem / "vocals.wav"
        if not vocals.exists():
            raise RuntimeError(f"Demucs did not produce {vocals}")
        return vocals

    def transcribe(self, audio_path: Path) -> Transcript:
        out_dir = Path(tempfile.mkdtemp(prefix="demucs-", dir=audio_path.parent))
        try:
            try:
                vocals = self.isolate(audio_path, out_dir)
            except Exception as exc:
                log.warning("Vocal isolation failed, using the full mix: %s", exc)
                return self.inner.transcribe(audio_path)
            return self.inner.transcribe(vocals)
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
