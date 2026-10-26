import shutil

import pytest

from app import downloader, ffmpeg
from app.downloader import DownloadError, download_audio
from tests.conftest import make_tone_wav


@pytest.fixture(autouse=True)
def clear_cache():
    ffmpeg.ffmpeg_path.cache_clear()
    yield
    ffmpeg.ffmpeg_path.cache_clear()


def test_prefers_system_ffmpeg(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/ffmpeg")
    assert ffmpeg.ffmpeg_path() == "/usr/bin/ffmpeg"


def test_falls_back_to_bundled_ffmpeg(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    bundled = ffmpeg.ffmpeg_path()
    assert bundled and "imageio_ffmpeg" in bundled


def test_download_explains_missing_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "require_ffmpeg", lambda: (_ for _ in ()).throw(
        ffmpeg.FFmpegMissing(ffmpeg.INSTALL_HINT)))
    with pytest.raises(DownloadError, match="ffmpeg isn't installed"):
        download_audio("https://example.com/song", tmp_path, max_duration_seconds=60)


@pytest.mark.parametrize("system_ffmpeg", [True, False])
def test_probe_duration(monkeypatch, tmp_path, system_ffmpeg):
    if not system_ffmpeg:
        monkeypatch.setattr(shutil, "which", lambda name: None)
    elif shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    wav = make_tone_wav(tmp_path / "tone.wav", seconds=2.5)
    assert ffmpeg.probe_duration(wav) == pytest.approx(2.5, abs=0.05)


def test_probe_duration_unreadable_file(tmp_path):
    junk = tmp_path / "junk.mp3"
    junk.write_bytes(b"not audio")
    assert ffmpeg.probe_duration(junk) is None
