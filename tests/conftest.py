import math
import struct
import time
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.transcriber import Segment, Transcript


def make_tone_wav(path: Path, seconds: float = 1.0, freq: float = 440.0, rate: int = 16000) -> Path:
    """Write a synthetic sine-wave WAV file. Used instead of any real recording."""
    frames = b"".join(
        struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / rate)))
        for i in range(int(seconds * rate))
    )
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return path


class FakeTranscriber:
    """Returns fixed, made-up lines and records which files it was given."""

    def __init__(self, language: str = "en", lines: list[str] | None = None):
        self.language = language
        self.lines = lines if lines is not None else ["first test line", "second test line"]
        self.seen: list[Path] = []
        self.languages: list = []

    def transcribe(self, audio_path: Path, language=None) -> Transcript:
        assert audio_path.exists(), "audio should exist while transcribing"
        self.seen.append(audio_path)
        self.languages.append(language)
        return Transcript(
            language=self.language,
            segments=[Segment(float(i), float(i + 1), text) for i, text in enumerate(self.lines)],
        )


class FakeTranslator:
    def __init__(self):
        self.calls: list[tuple[list[str], str, str]] = []

    def translate(self, lines, source, target):
        self.calls.append((list(lines), source, target))
        return [f"[{target}] {line}" for line in lines]


@pytest.fixture
def tone_wav(tmp_path) -> Path:
    return make_tone_wav(tmp_path / "tone.wav")


@pytest.fixture
def fakes():
    return FakeTranscriber(), FakeTranslator()


@pytest.fixture
def client(tmp_path, fakes):
    transcriber, translator = fakes
    settings = Settings(work_dir=tmp_path / "work", block_private_urls=False, max_upload_mb=1)
    app = create_app(settings=settings, transcriber=transcriber, translator=translator)
    with TestClient(app) as c:
        yield c
    app.state.jobs.shutdown()


def wait_for_job(client: TestClient, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"done", "error"}:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish")
