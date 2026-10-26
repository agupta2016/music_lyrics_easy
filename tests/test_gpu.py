import os

from app import gpu
from app.transcriber import WhisperTranscriber


def _fake_site(tmp_path):
    for lib, dll in [("cublas", "cublas64_12.dll"), ("cudnn", "cudnn64_9.dll")]:
        folder = tmp_path / "nvidia" / lib / "bin"
        folder.mkdir(parents=True)
        (folder / dll).write_bytes(b"")
    return tmp_path


def test_registers_nvidia_dll_folders_on_windows(monkeypatch, tmp_path):
    site_dir = _fake_site(tmp_path)
    monkeypatch.setattr(gpu.sys, "platform", "win32")
    monkeypatch.setattr(gpu.site, "getsitepackages", lambda: [str(site_dir)])
    monkeypatch.setattr(gpu.site, "getusersitepackages", lambda: str(tmp_path / "user"))
    added, loaded = [], []
    monkeypatch.setattr(gpu.os, "add_dll_directory", added.append, raising=False)
    monkeypatch.setattr(gpu.ctypes, "CDLL", loaded.append)
    monkeypatch.setenv("PATH", "original")

    dirs = gpu.register_nvidia_libraries()

    expected = [str(site_dir / "nvidia" / "cublas" / "bin"), str(site_dir / "nvidia" / "cudnn" / "bin")]
    assert dirs == expected and added == expected
    assert os.environ["PATH"].split(os.pathsep) == expected + ["original"]
    assert [os.path.basename(p) for p in loaded] == ["cublas64_12.dll", "cudnn64_9.dll"]


def test_does_nothing_off_windows(monkeypatch):
    monkeypatch.setattr(gpu.sys, "platform", "linux")
    assert gpu.register_nvidia_libraries() == []


def test_auto_model_is_large_on_gpu_and_medium_on_cpu(monkeypatch):
    whisper = WhisperTranscriber("auto", "auto")
    monkeypatch.setattr(gpu, "cuda_available", lambda: True)
    assert whisper.model_for("auto") == "large-v3"
    assert whisper.model_for("cpu") == "medium"
    monkeypatch.setattr(gpu, "cuda_available", lambda: False)
    assert whisper.model_for("auto") == "medium"
    assert whisper.model_for("cuda") == "large-v3"


def test_explicit_model_is_kept(monkeypatch):
    monkeypatch.setattr(gpu, "cuda_available", lambda: True)
    assert WhisperTranscriber("small", "auto").model_for("cpu") == "small"
