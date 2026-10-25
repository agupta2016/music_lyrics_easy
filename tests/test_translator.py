import pytest

from app.languages import base_code
from app.translator import (
    ArgosTranslator,
    GoogleTranslator,
    NllbTranslator,
    NoopTranslator,
    TranslationError,
    make_translator,
    nllb_code,
)
from app.languages import LANGUAGES


def test_make_translator_names():
    assert isinstance(make_translator("nllb"), NllbTranslator)
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


def test_every_picker_language_has_an_nllb_code():
    for code in LANGUAGES:
        if code != "original":
            assert nllb_code(code)


def test_nllb_code_rejects_unknown_language():
    with pytest.raises(TranslationError):
        nllb_code("xx")


class _FakeTokenizer:
    """Stands in for the Hugging Face tokenizer: 'encodes' text and records the languages."""

    src_lang = None

    def __call__(self, batch, **kwargs):
        self.last_src = self.src_lang
        return {"batch": list(batch)}

    def convert_tokens_to_ids(self, token):
        return token

    def batch_decode(self, generated, skip_special_tokens):
        return generated


class _FakeModel:
    def __init__(self):
        self.calls = []

    def generate(self, batch, forced_bos_token_id, max_new_tokens):
        self.calls.append(len(batch))
        return [f"{forced_bos_token_id}:{text}" for text in batch]


def test_nllb_translate_batches_and_maps_codes():
    translator = NllbTranslator(batch_size=2)
    tokenizer, model = _FakeTokenizer(), _FakeModel()
    translator._tokenizer, translator._model = tokenizer, model

    out = translator.translate(["a", "b", "c"], source="en", target="zh-CN")

    assert out == ["zho_Hans:a", "zho_Hans:b", "zho_Hans:c"]
    assert tokenizer.last_src == "eng_Latn"
    assert model.calls == [2, 1]
