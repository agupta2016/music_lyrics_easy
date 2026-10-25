"""Runs yt-dlp + ffmpeg for real against a synthetic file served from localhost."""

import functools
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.downloader import DownloadError, download_audio
from tests.conftest import make_tone_wav

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


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


def test_downloads_and_converts_direct_audio_link(served_dir, tmp_path):
    root, base = served_dir
    make_tone_wav(root / "tone.wav", seconds=2)
    audio, title = download_audio(f"{base}/tone.wav", tmp_path / "out", max_duration_seconds=60)
    assert audio.name == "audio.mp3"
    assert audio.stat().st_size > 0
    assert title


def test_rejects_audio_over_duration_limit(served_dir, tmp_path):
    root, base = served_dir
    make_tone_wav(root / "long.wav", seconds=3)
    with pytest.raises(DownloadError):
        download_audio(f"{base}/long.wav", tmp_path / "out", max_duration_seconds=1)
