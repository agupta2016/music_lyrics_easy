"""Optional: runs the real Whisper model on a synthetic tone. Downloads the 'tiny' model.

Enable with RUN_WHISPER_TESTS=1.
"""

import os

import pytest

from app.transcriber import WhisperTranscriber

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_WHISPER_TESTS") != "1", reason="set RUN_WHISPER_TESTS=1 to run"
)


def test_whisper_runs_on_synthetic_audio(tone_wav):
    transcript = WhisperTranscriber("tiny", "cpu").transcribe(tone_wav)
    assert isinstance(transcript.language, str)
    assert isinstance(transcript.segments, list)
