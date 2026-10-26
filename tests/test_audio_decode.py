"""Whisper decodes audio with PyAV; check that the installed versions work together."""

from faster_whisper.audio import decode_audio

from tests.conftest import make_tone_wav


def test_faster_whisper_can_decode_audio(tmp_path):
    wav = make_tone_wav(tmp_path / "tone.wav", seconds=1.0)
    samples = decode_audio(str(wav))
    assert samples.shape == (16000,)
