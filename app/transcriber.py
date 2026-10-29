"""Speech-to-text with Whisper (via faster-whisper, runs locally)."""

import logging
import re
import unicodedata
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
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
    # What actually ran, shown under the lyrics so problems can be traced:
    # model, device, audio_seconds, heard_seconds, vocals_isolated.
    diagnostics: dict = field(default_factory=dict)


class Transcriber(Protocol):
    def transcribe(
        self, audio_path: Path, language: Optional[str] = None, hint: Optional[str] = None
    ) -> Transcript: ...


# Silero VAD settings for singing: lower confidence bar, longer padding around
# detected vocals, and only treat 3 s+ gaps as breaks between lines.
SONG_VAD = {"threshold": 0.25, "min_silence_duration_ms": 3000, "speech_pad_ms": 800}


class WhisperTranscriber:
    """Loads the Whisper model once, on first use, and reuses it across jobs.

    If the GPU is picked but its CUDA libraries are missing (common on Windows
    machines with an NVIDIA card but no CUDA toolkit), it switches to the CPU.
    """

    def __init__(self, model_size: str = "auto", device: str = "auto", vad: bool = True):
        self.model_size = model_size
        self.device = device
        self.vad = vad
        self._model = None
        self._lock = threading.Lock()

    def model_for(self, device: str) -> str:
        """'auto' means large-v2 on a GPU and medium on a CPU.

        large-v2 rather than v3: v3 is more prone to dropping or hallucinating
        lines over music, which matters more for songs than its gains on speech.
        """
        if self.model_size != "auto":
            return self.model_size
        from .gpu import cuda_available

        on_gpu = device == "cuda" or (device == "auto" and cuda_available())
        return "large-v2" if on_gpu else "medium"

    def _load_model(self, device: str):
        from faster_whisper import WhisperModel

        from .gpu import register_nvidia_libraries

        register_nvidia_libraries()
        model = self.model_for(device)
        log.info("Loading Whisper model %s on %s", model, device)
        # int8 is the fast choice on CPU; "auto" picks the best type for the GPU.
        compute_type = "int8" if device == "cpu" else "auto"
        return WhisperModel(model, device=device, compute_type=compute_type)

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

    def _run(self, audio_path: Path, language: Optional[str], hint: Optional[str]) -> Transcript:
        model = self._get_model()
        segments, info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=5,
            # Skips long instrumental stretches, which otherwise produce made-up text.
            # The speech detector is tuned for talking, so loosen it or it drops sung lines.
            vad_filter=self.vad,
            vad_parameters=SONG_VAD if self.vad else None,
            # Whisper rates sung lines over music as "probably not speech"; only skip
            # a window when it is very sure.
            no_speech_threshold=0.85,
            # Feeding earlier lines back in makes Whisper repeat choruses and loop on songs.
            condition_on_previous_text=False,
            # Words the song is likely to contain (from its title). Unlike initial_prompt,
            # faster-whisper feeds hotwords to every 30 s window, so it steers spelling throughout.
            hotwords=hint,
        )
        # Segments are generated lazily, so GPU errors surface while iterating.
        result = [
            Segment(start=round(s.start, 2), end=round(s.end, 2), text=s.text.strip())
            for s in segments
            if s.text.strip()
        ]
        diagnostics = {
            "model": self.model_for(self.device),
            "device": self.device,
            "audio_seconds": round(info.duration, 1),
            # With the speech detector on, only these seconds reach Whisper.
            "heard_seconds": round(getattr(info, "duration_after_vad", None) or info.duration, 1),
            "last_line_ends": result[-1].end if result else 0.0,
            "hint": hint,
        }
        return Transcript(
            language=info.language, segments=remove_overlaps(result), diagnostics=diagnostics
        )

    def transcribe(
        self, audio_path: Path, language: Optional[str] = None, hint: Optional[str] = None
    ) -> Transcript:
        try:
            return self._run(audio_path, language, hint)
        except Exception as exc:
            with self._lock:
                if not self._switch_to_cpu(exc):
                    raise
            return self._run(audio_path, language, hint)


_NOISE_WORDS = re.compile(
    r"\b(official|video|audio|lyrics?|lyrical|full song|song|hd|4k|music|shorts?|status)\b",
    re.IGNORECASE,
)


# Sung languages normally written in a non-Latin script.
_NON_LATIN_LANGUAGES = {
    "ar", "bn", "el", "fa", "gu", "he", "hi", "ja", "kn", "ko", "ml", "mr", "pa",
    "ru", "ta", "te", "th", "uk", "ur", "zh",
}


def _non_latin_letter(char: str) -> bool:
    return char.isalpha() and not unicodedata.name(char, "").startswith("LATIN")


def title_hint(title: Optional[str], language: Optional[str] = None) -> Optional[str]:
    """Turn a video title or file name into words to prime Whisper with.

    'करूं नित नित तेरा ध्यान | Disciple's Prayer | #Bhajan' -> 'करूं नित नित तेरा ध्यान'
    For songs in a non-Latin script, only the parts of the title in that script are
    kept, so English descriptions don't pull Whisper towards English.
    """
    if not title:
        return None
    text = re.sub(r"#\S+", " ", title)
    text = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", text)
    text = re.sub(r"\.(mp3|m4a|wav|mp4|webm|ogg|flac|aac|opus)$", "", text, flags=re.IGNORECASE)
    parts = [p.strip() for p in re.split(r"[|/:\-–—,]+", text) if p.strip()]
    if language and language != "en":
        native = [p for p in parts if any(_non_latin_letter(c) for c in p)]
        # A title only in English letters (e.g. "Tum Hi Ho") would nudge Whisper
        # into writing a Hindi song in English letters, so give no hint then.
        if not native and language in _NON_LATIN_LANGUAGES:
            return None
        if native:
            parts = native
    hint = " ".join(_NOISE_WORDS.sub(" ", p) for p in parts)
    hint = re.sub(r"\s+", " ", hint).strip()
    return hint[:120] or None


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


class LanguageRoutingTranscriber:
    """Sends songs in some languages to a dedicated model, such as one fine-tuned on Hindi.

    Routing only happens when the user picks the language being sung; with
    "Detect automatically" the default model is used.
    """

    def __init__(self, default: Transcriber, by_language: dict[str, Transcriber]):
        self.default = default
        self.by_language = by_language

    def transcribe(
        self, audio_path: Path, language: Optional[str] = None, hint: Optional[str] = None
    ) -> Transcript:
        model = self.by_language.get(language or "", self.default)
        return model.transcribe(audio_path, language, hint)


def parse_language_models(value: str) -> dict[str, str]:
    """'hi=models/whisper-hindi, ta=other' -> {'hi': 'models/whisper-hindi', 'ta': 'other'}"""
    models: dict[str, str] = {}
    for item in value.split(","):
        if not item.strip():
            continue
        lang, sep, model = item.partition("=")
        if not sep or not lang.strip() or not model.strip():
            raise ValueError(f"WHISPER_LANGUAGE_MODELS entry {item.strip()!r} should look like hi=path/to/model")
        models[lang.strip().lower()] = model.strip()
    return models


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

    def transcribe(
        self, audio_path: Path, language: Optional[str] = None, hint: Optional[str] = None
    ) -> Transcript:
        out_dir = Path(tempfile.mkdtemp(prefix="demucs-", dir=audio_path.parent))
        try:
            try:
                vocals = self.isolate(audio_path, out_dir)
            except Exception as exc:
                log.warning("Vocal isolation failed, using the full mix: %s", exc)
                transcript = self.inner.transcribe(audio_path, language, hint)
                transcript.diagnostics["vocals_isolated"] = False
                return transcript
            transcript = self.inner.transcribe(vocals, language, hint)
            transcript.diagnostics["vocals_isolated"] = True
            return transcript
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
