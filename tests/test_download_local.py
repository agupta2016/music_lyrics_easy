"""Runs yt-dlp + ffmpeg for real against a synthetic file served from localhost."""

import functools
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import ffmpeg
from app.downloader import DownloadError, download_audio, download_video
from tests.conftest import make_tone_wav



class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(params=["system", "bundled"])
def ffmpeg_source(request, monkeypatch):
    """Run each test with the system ffmpeg and with the bundled imageio-ffmpeg copy."""
    ffmpeg.ffmpeg_path.cache_clear()
    if request.param == "system":
        if shutil.which("ffmpeg") is None:
            pytest.skip("ffmpeg not installed")
    else:
        real_which = shutil.which
        monkeypatch.setattr(
            shutil, "which", lambda name, *a, **k: None if name in {"ffmpeg", "ffprobe"} else real_which(name, *a, **k)
        )
        # yt-dlp looks ffmpeg up on PATH too, so hide the system one from it.
        monkeypatch.setenv("PATH", "/nonexistent")
    yield request.param
    ffmpeg.ffmpeg_path.cache_clear()


@pytest.fixture
def served_dir(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    handler = functools.partial(QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield root, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_downloads_and_converts_direct_audio_link(ffmpeg_source, served_dir, tmp_path):
    root, base = served_dir
    make_tone_wav(root / "tone.wav", seconds=2)
    audio, title = download_audio(f"{base}/tone.wav", tmp_path / "out", max_duration_seconds=60)
    assert audio.name == "audio.mp3"
    assert audio.stat().st_size > 0
    assert title


def test_rejects_audio_over_duration_limit(ffmpeg_source, served_dir, tmp_path):
    root, base = served_dir
    make_tone_wav(root / "long.wav", seconds=3)
    with pytest.raises(DownloadError, match="limit"):
        download_audio(f"{base}/long.wav", tmp_path / "out", max_duration_seconds=1)


def make_test_video(path, seconds: int = 2):
    """A synthetic test-pattern video with a tone, made with ffmpeg."""
    import subprocess

    subprocess.run(
        [
            ffmpeg.ffmpeg_path(), "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=10:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )
    return path


def test_downloads_direct_video_link(ffmpeg_source, served_dir, tmp_path):
    root, base = served_dir
    make_test_video(root / "clip.mp4")
    seen = []
    video, title = download_video(
        f"{base}/clip.mp4", tmp_path / "out", max_duration_seconds=60, on_progress=seen.append
    )
    assert video.name == "video.mp4"
    assert video.stat().st_size > 0
    assert title
    assert ffmpeg.probe_duration(video) == pytest.approx(2, abs=0.5)


def test_rejects_video_over_duration_limit(ffmpeg_source, served_dir, tmp_path):
    root, base = served_dir
    make_test_video(root / "long.mp4", seconds=3)
    with pytest.raises(DownloadError, match="limit"):
        download_video(f"{base}/long.mp4", tmp_path / "out", max_duration_seconds=1)
