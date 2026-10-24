import pytest

from app.languages import base_code
from app.translator import ArgosTranslator, GoogleTranslator, NoopTranslator, make_translator


def test_make_translator_names():
    assert isinstance(make_translator("google"), GoogleTranslator)
    assert isinstance(make_translator("argos"), ArgosTranslator)
    assert isinstance(make_translator("none"), NoopTranslator)
    with pytest.raises(ValueError):
        make_translator("bogus")


def test_noop_returns_copy():
    lines = ["a", "b"]
    out = NoopTranslator().translate(lines, "en", "fr")
    assert out == lines and out is not lines


def test_base_code():
    assert base_code("zh-CN") == "zh"
    assert base_code("hi") == "hi"
