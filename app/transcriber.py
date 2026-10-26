"""Speech-to-text with Whisper (via faster-whisper, runs locally)."""

import logging
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol


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
    def transcribe(self, audio_path: Path, language: Optional[str] = None) -> Transcript: ...


class WhisperTranscriber:
    """Loads the Whisper model once, on first use, and reuses it across jobs.

    If the GPU is picked but its CUDA libraries are missing (common on Windows
    machines with an NVIDIA card but no CUDA toolkit), it switches to the CPU.
    """

    def __init__(self, model_size: str = "small", device: str = "auto"):
        self.model_size = model_size
        self.device = device
        self._model = None
        self._lock = threading.Lock()

    def _load_model(self, device: str):
        from faster_whisper import WhisperModel

        # int8 is the fast choice on CPU; "auto" picks the best type for the GPU.
        compute_type = "int8" if device == "cpu" else "auto"
        return WhisperModel(self.model_size, device=device, compute_type=compute_type)

    def _get_model(self):
        with self._lock:
            if self._model is None:
                try:
                    self._model = self._load_model(self.device)
                except Exception as exc:
                    if not self._switch_to_cpu(exc):
                        raise
                    self._model = self._load_model("cpu")
            return self._model

    def _switch_to_cpu(self, exc: Exception) -> bool:
        """Fall back to the CPU for good if ``exc`` is a GPU library problem."""
        if self.device == "cpu" or not _is_gpu_error(exc):
            return False
        log.warning("GPU unavailable (%s); running Whisper on the CPU instead.", exc)
        self.device = "cpu"
        self._model = None
        return True

    def _run(self, audio_path: Path, language: Optional[str]) -> Transcript:
        model = self._get_model()
        segments, info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=5,
            # Skips long instrumental stretches, which otherwise produce made-up text.
            vad_filter=True,
            # Feeding earlier lines back in makes Whisper repeat choruses and loop on songs.
            condition_on_previous_text=False,
        )
        # Segments are generated lazily, so GPU errors surface while iterating.
        result = [
            Segment(start=round(s.start, 2), end=round(s.end, 2), text=s.text.strip())
            for s in segments
            if s.text.strip()
        ]
        return Transcript(language=info.language, segments=remove_overlaps(result))

    def transcribe(self, audio_path: Path, language: Optional[str] = None) -> Transcript:
        try:
            return self._run(audio_path, language)
        except Exception as exc:
            with self._lock:
                if not self._switch_to_cpu(exc):
                    raise
            return self._run(audio_path, language)


def remove_overlaps(segments: list[Segment]) -> list[Segment]:
    """Drop lines that repeat the previous one at the same moment, and stop times running backwards."""
    cleaned: list[Segment] = []
    for seg in segments:
        if cleaned:
            prev = cleaned[-1]
            if seg.text.lower() == prev.text.lower() and seg.start < prev.end:
                prev.end = max(prev.end, seg.end)
                continue
            if seg.start < prev.end:
                seg = Segment(prev.end, max(seg.end, prev.end), seg.text)
        cleaned.append(seg)
    return cleaned


_GPU_ERROR_HINTS = ("cublas", "cudnn", "cuda", "libcu", "nvrtc", "gpu")


def _is_gpu_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(hint in text for hint in _GPU_ERROR_HINTS)


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

    def transcribe(self, audio_path: Path, language: Optional[str] = None) -> Transcript:
        out_dir = Path(tempfile.mkdtemp(prefix="demucs-", dir=audio_path.parent))
        try:
            try:
                vocals = self.isolate(audio_path, out_dir)
            except Exception as exc:
                log.warning("Vocal isolation failed, using the full mix: %s", exc)
                return self.inner.transcribe(audio_path, language)
            return self.inner.transcribe(vocals, language)
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
