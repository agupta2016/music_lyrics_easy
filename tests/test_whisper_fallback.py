from types import SimpleNamespace

import pytest

from app.transcriber import WhisperTranscriber


class FakeModel:
    def __init__(self, device, fail_with=None):
        self.device = device
        self.fail_with = fail_with

    def transcribe(self, path, **kwargs):
        def segments():
            # Real faster-whisper raises GPU errors lazily, while segments are generated.
            if self.fail_with:
                raise self.fail_with
            yield SimpleNamespace(start=0.0, end=1.0, text=" hello ")

        return segments(), SimpleNamespace(language="en", duration=240.0, duration_after_vad=200.0)


class FakeWhisper(WhisperTranscriber):
    def __init__(self, device, gpu_error=None, load_error=None):
        super().__init__("tiny", device)
        self.gpu_error = gpu_error
        self.load_error = load_error
        self.loaded = []

    def _load_model(self, device):
        self.loaded.append(device)
        if device != "cpu" and self.load_error:
            raise self.load_error
        return FakeModel(device, self.gpu_error if device != "cpu" else None)


CUBLAS = RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")


def test_falls_back_to_cpu_when_cuda_libraries_are_missing(tmp_path):
    whisper = FakeWhisper("auto", gpu_error=CUBLAS)

    transcript = whisper.transcribe(tmp_path / "song.mp3")

    assert transcript.segments[0].text == "hello"
    assert whisper.loaded == ["auto", "cpu"]
    # Later jobs go straight to the CPU model.
    whisper.transcribe(tmp_path / "song.mp3")
    assert whisper.loaded == ["auto", "cpu"]


def test_falls_back_when_the_gpu_model_fails_to_load(tmp_path):
    whisper = FakeWhisper("cuda", load_error=RuntimeError("CUDA driver version is insufficient"))

    assert whisper.transcribe(tmp_path / "song.mp3").segments
    assert whisper.loaded == ["cuda", "cpu"]


def test_other_errors_are_not_hidden(tmp_path):
    whisper = FakeWhisper("auto", gpu_error=ValueError("bad audio file"))

    with pytest.raises(ValueError, match="bad audio"):
        whisper.transcribe(tmp_path / "song.mp3")
    assert whisper.loaded == ["auto"]


def test_cpu_errors_are_raised(tmp_path):
    whisper = FakeWhisper("cpu")
    whisper._load_model = lambda device: (_ for _ in ()).throw(CUBLAS)

    with pytest.raises(RuntimeError):
        whisper.transcribe(tmp_path / "song.mp3")


def test_whisper_is_told_not_to_reuse_earlier_lines(tmp_path):
    calls = []

    class Recording(FakeModel):
        def transcribe(self, path, **kwargs):
            calls.append(kwargs)
            return super().transcribe(path, **kwargs)

    whisper = FakeWhisper("cpu")
    whisper._load_model = lambda device: Recording(device)

    whisper.transcribe(tmp_path / "song.mp3", language="hi")

    assert calls[0]["language"] == "hi"
    assert calls[0]["condition_on_previous_text"] is False
    assert calls[0]["vad_filter"] is True
    assert calls[0]["vad_parameters"]["threshold"] < 0.5
    assert calls[0]["no_speech_threshold"] > 0.6

    calls.clear()
    whisper.vad = False
    whisper.transcribe(tmp_path / "song.mp3")
    assert calls[0]["vad_filter"] is False and calls[0]["vad_parameters"] is None


def test_transcript_reports_what_ran(tmp_path):
    whisper = FakeWhisper("cpu")
    d = whisper.transcribe(tmp_path / "song.mp3").diagnostics
    assert d == {
        "model": "tiny",
        "device": "cpu",
        "audio_seconds": 240.0,
        "heard_seconds": 200.0,
        "last_line_ends": 1.0,
        "hint": None,
        "dropped_lines": 0,
    }


def test_hint_is_sent_as_hotwords(tmp_path):
    calls = []

    class Recording(FakeModel):
        def transcribe(self, path, **kwargs):
            calls.append(kwargs)
            return super().transcribe(path, **kwargs)

    whisper = FakeWhisper("cpu")
    whisper._load_model = lambda device: Recording(device)

    transcript = whisper.transcribe(tmp_path / "song.mp3", "hi", "करूं नित नित तेरा ध्यान")

    assert calls[0]["hotwords"] == "करूं नित नित तेरा ध्यान"
    assert transcript.diagnostics["hint"] == "करूं नित नित तेरा ध्यान"
