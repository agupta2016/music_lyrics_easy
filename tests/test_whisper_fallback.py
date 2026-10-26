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

        return segments(), SimpleNamespace(language="en")


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
