import pytest

from app import main as app_main
from app.config import Settings
from app.main import create_app
from app.transcriber import (
    LanguageRoutingTranscriber,
    VocalIsolatingTranscriber,
    WhisperTranscriber,
    parse_language_models,
)
from tests.conftest import FakeTranscriber


def test_parse_language_models():
    assert parse_language_models("") == {}
    assert parse_language_models(" HI = models/whisper-hindi , ta=x ") == {
        "hi": "models/whisper-hindi",
        "ta": "x",
    }
    with pytest.raises(ValueError):
        parse_language_models("models/whisper-hindi")


def test_routes_chosen_language_to_its_model(tmp_path):
    default, hindi = FakeTranscriber(), FakeTranscriber()
    router = LanguageRoutingTranscriber(default, {"hi": hindi})
    song = tmp_path / "song.wav"
    song.write_bytes(b"")

    router.transcribe(song, "hi")
    router.transcribe(song, "en")
    router.transcribe(song, None)

    assert hindi.languages == ["hi"]
    assert default.languages == ["en", None]


def test_app_builds_language_models_inside_vocal_isolation(monkeypatch, tmp_path):
    monkeypatch.setattr(app_main, "demucs_available", lambda: True)
    settings = Settings(
        work_dir=tmp_path, translator="none", whisper_language_models="hi=models/whisper-hindi"
    )
    app = create_app(settings=settings)
    try:
        outer = app.state.jobs.transcriber
        assert isinstance(outer, VocalIsolatingTranscriber)
        router = outer.inner
        assert isinstance(router, LanguageRoutingTranscriber)
        assert isinstance(router.by_language["hi"], WhisperTranscriber)
        assert router.by_language["hi"].model_size == "models/whisper-hindi"
    finally:
        app.state.jobs.shutdown()
