import time
from pathlib import Path

import app.main as main_module
from app.downloader import DownloadError
from app.videos import VideoDownload


def wait_for_video(client, download_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        item = client.get(f"/api/videos/{download_id}").json()
        if item["status"] in {"done", "error"}:
            return item
        time.sleep(0.02)
    raise AssertionError(f"download {download_id} did not finish")


def fake_video(url, dest_dir, max_duration_seconds, quality="best", on_progress=None):
    dest_dir.mkdir(parents=True, exist_ok=True)
    if on_progress:
        on_progress(50.0)
    path = dest_dir / "video.mp4"
    path.write_bytes(b"not really a video")
    return path, 'My: Song / "Live"'


def test_video_download_can_be_saved(client, monkeypatch, fakes):
    transcriber, _ = fakes
    monkeypatch.setattr(main_module, "download_video", fake_video)

    res = client.post("/api/videos", json={"url": "https://example.com/v/1", "quality": "720"})
    assert res.status_code == 202
    item = wait_for_video(client, res.json()["id"])

    assert item["status"] == "done", item
    assert item["title"] == 'My: Song / "Live"'
    assert item["quality"] == "720"
    assert item["size_bytes"] == len(b"not really a video")
    assert item["filename"] == "My Song Live.mp4"

    file = client.get(f"/api/videos/{item['id']}/file")
    assert file.status_code == 200
    assert file.content == b"not really a video"
    assert "attachment" in file.headers["content-disposition"]
    # Downloading a video doesn't transcribe anything.
    assert transcriber.seen == []


def test_video_download_error_is_reported(client, monkeypatch):
    def failing(*args, **kwargs):
        raise DownloadError("Video unavailable")

    monkeypatch.setattr(main_module, "download_video", failing)
    res = client.post("/api/videos", json={"url": "https://example.com/missing"})
    item = wait_for_video(client, res.json()["id"])
    assert item["status"] == "error"
    assert item["error"] == "Video unavailable"
    assert client.get(f"/api/videos/{item['id']}/file").status_code == 404


def test_video_rejects_bad_input(client):
    assert client.post("/api/videos", json={"url": "file:///etc/passwd"}).status_code == 400
    res = client.post("/api/videos", json={"url": "https://example.com/a", "quality": "8k"})
    assert res.status_code == 400
    assert client.get("/api/videos/nope").status_code == 404
    assert client.get("/api/videos/nope/file").status_code == 404


def test_old_videos_are_deleted(tmp_path):
    from app.videos import VideoDownloadManager

    manager = VideoDownloadManager(tmp_path / "videos", keep_seconds=0)

    def fetch(item: VideoDownload, item_dir: Path):
        item_dir.mkdir(parents=True)
        path = item_dir / "video.mp4"
        path.write_bytes(b"x")
        return path, "t"

    first = manager.submit("a", "best", fetch)
    deadline = time.time() + 5
    while first.status != "done" and time.time() < deadline:
        time.sleep(0.01)
    assert first.path.exists()
    time.sleep(0.01)
    manager.prune()
    assert manager.get(first.id) is None
    assert not first.path.exists()
    manager.shutdown()
