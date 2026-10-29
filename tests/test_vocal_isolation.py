from app.config import Settings
from app.main import create_app
from app import main as app_main
from app.transcriber import VocalIsolatingTranscriber, WhisperTranscriber

from .conftest import FakeTranscriber, make_tone_wav


def test_transcribes_isolated_vocals_and_cleans_up(tmp_path):
    song = make_tone_wav(tmp_path / "song.wav")
    inner = FakeTranscriber()
    wrapper = VocalIsolatingTranscriber(inner)

    def fake_isolate(audio_path, out_dir):
        return make_tone_wav(out_dir / "vocals.wav")

    wrapper.isolate = fake_isolate
    assert wrapper.transcribe(song).diagnostics["vocals_isolated"] is True

    assert inner.seen[0].name == "vocals.wav"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["song.wav"]


def test_falls_back_to_full_mix_when_demucs_fails(tmp_path):
    song = make_tone_wav(tmp_path / "song.wav")
    inner = FakeTranscriber()
    wrapper = VocalIsolatingTranscriber(inner)

    def broken_isolate(audio_path, out_dir):
        raise RuntimeError("demucs crashed")

    wrapper.isolate = broken_isolate
    transcript = wrapper.transcribe(song)

    assert inner.seen == [song]
    assert transcript.segments
    assert transcript.diagnostics["vocals_isolated"] is False


def _default_transcriber(monkeypatch, tmp_path, demucs: bool, isolate: bool):
    monkeypatch.setattr(app_main, "demucs_available", lambda: demucs)
    app = create_app(
        settings=Settings(work_dir=tmp_path, isolate_vocals=isolate, translator="none")
    )
    try:
        return app.state.jobs.transcriber
    finally:
        app.state.jobs.shutdown()


def test_app_uses_demucs_only_when_enabled_and_installed(monkeypatch, tmp_path):
    assert isinstance(
        _default_transcriber(monkeypatch, tmp_path, demucs=True, isolate=True),
        VocalIsolatingTranscriber,
    )
    assert isinstance(
        _default_transcriber(monkeypatch, tmp_path, demucs=False, isolate=True),
        WhisperTranscriber,
    )
    assert isinstance(
        _default_transcriber(monkeypatch, tmp_path, demucs=True, isolate=False),
        WhisperTranscriber,
    )
