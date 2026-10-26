from pathlib import Path

import app.main as main_module
from app.downloader import DownloadError
from tests.conftest import make_tone_wav, wait_for_job


def test_languages_lists_original_and_common_languages(client):
    languages = client.get("/api/languages").json()
    assert "original" in languages
    assert languages["hi"] == "Hindi"
    assert languages["es"] == "Spanish"


def test_index_serves_ui(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "MusicLyricsEasy" in res.text


def test_link_job_transcribes_and_translates(client, fakes, monkeypatch, tmp_path):
    transcriber, translator = fakes

    def fake_download(url, dest_dir, max_duration_seconds):
        dest_dir.mkdir(parents=True, exist_ok=True)
        return make_tone_wav(dest_dir / "audio.wav"), "Synthetic Tone"

    monkeypatch.setattr(main_module, "download_audio", fake_download)

    res = client.post("/api/jobs", json={"url": "https://example.com/v/1", "target_language": "fr"})
    assert res.status_code == 202
    job = wait_for_job(client, res.json()["id"])

    assert job["status"] == "done", job
    assert job["title"] == "Synthetic Tone"
    assert job["detected_language"] == "en"
    assert [l["text"] for l in job["lines"]] == ["first test line", "second test line"]
    assert [l["translation"] for l in job["lines"]] == [
        "[fr] first test line",
        "[fr] second test line",
    ]
    assert translator.calls[0][1:] == ("en", "fr")
    # Temporary audio is cleaned up after the job.
    assert not transcriber.seen[0].exists()


def test_original_language_skips_translation(client, fakes, tone_wav):
    _, translator = fakes
    with tone_wav.open("rb") as f:
        res = client.post(
            "/api/jobs/upload",
            files={"file": ("tone.wav", f, "audio/wav")},
            data={"target_language": "original"},
        )
    job = wait_for_job(client, res.json()["id"])
    assert job["status"] == "done"
    assert job["title"] == "tone.wav"
    assert all(l["translation"] is None for l in job["lines"])
    assert translator.calls == []


def test_same_language_as_detected_skips_translation(client, fakes, tone_wav):
    _, translator = fakes
    with tone_wav.open("rb") as f:
        res = client.post(
            "/api/jobs/upload",
            files={"file": ("tone.wav", f, "audio/wav")},
            data={"target_language": "en"},
        )
    job = wait_for_job(client, res.json()["id"])
    assert job["status"] == "done"
    assert translator.calls == []


def test_download_error_is_reported_on_job(client, monkeypatch):
    def failing_download(url, dest_dir, max_duration_seconds):
        raise DownloadError("Video unavailable")

    monkeypatch.setattr(main_module, "download_audio", failing_download)
    res = client.post("/api/jobs", json={"url": "https://example.com/missing"})
    job = wait_for_job(client, res.json()["id"])
    assert job["status"] == "error"
    assert job["error"] == "Video unavailable"


def test_rejects_non_http_link(client):
    res = client.post("/api/jobs", json={"url": "file:///etc/passwd"})
    assert res.status_code == 400


def test_rejects_unknown_language(client):
    res = client.post("/api/jobs", json={"url": "https://example.com/a", "target_language": "xx"})
    assert res.status_code == 400


def test_rejects_oversized_upload(client):
    big = b"\0" * (1024 * 1024 + 10)
    res = client.post("/api/jobs/upload", files={"file": ("big.wav", big, "audio/wav")})
    assert res.status_code == 413


def test_rejects_empty_upload(client):
    res = client.post("/api/jobs/upload", files={"file": ("empty.wav", b"", "audio/wav")})
    assert res.status_code == 400


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/does-not-exist").status_code == 404


def test_rejects_upload_over_duration_limit(tmp_path, fakes):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    transcriber, translator = fakes
    settings = Settings(work_dir=tmp_path / "work", max_duration_seconds=1)
    app = create_app(settings=settings, transcriber=transcriber, translator=translator)
    wav = make_tone_wav(tmp_path / "long.wav", seconds=3)
    with TestClient(app) as c, wav.open("rb") as f:
        res = c.post("/api/jobs/upload", files={"file": ("long.wav", f, "audio/wav")})
        job = wait_for_job(c, res.json()["id"])
    app.state.jobs.shutdown()
    assert job["status"] == "error"
    assert "limit" in job["error"]
    assert transcriber.seen == []


def test_sung_language_is_passed_to_whisper(client, fakes, monkeypatch):
    transcriber, _ = fakes

    def fake_download(url, dest_dir, max_duration_seconds):
        dest_dir.mkdir(parents=True, exist_ok=True)
        return make_tone_wav(dest_dir / "audio.wav"), "Song"

    monkeypatch.setattr(main_module, "download_audio", fake_download)

    for sung, expected in [("hi", "hi"), ("zh-CN", "zh"), ("auto", None)]:
        res = client.post(
            "/api/jobs",
            json={"url": "https://example.com/v", "target_language": "original", "source_language": sung},
        )
        assert wait_for_job(client, res.json()["id"])["status"] == "done"
        assert transcriber.languages[-1] == expected


def test_sung_language_defaults_to_detection_for_uploads(client, fakes, tone_wav):
    transcriber, _ = fakes
    with tone_wav.open("rb") as f:
        res = client.post("/api/jobs/upload", files={"file": ("t.wav", f, "audio/wav")})
    assert wait_for_job(client, res.json()["id"])["status"] == "done"
    assert transcriber.languages == [None]


def test_rejects_unknown_sung_language(client):
    for bad in ("xx", "original"):
        res = client.post(
            "/api/jobs",
            json={"url": "https://example.com/a", "target_language": "en", "source_language": bad},
        )
        assert res.status_code == 400
