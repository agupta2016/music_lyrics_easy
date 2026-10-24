"""Translate transcribed lines into the language the user picked."""

import threading
from typing import Protocol

from .languages import base_code


class TranslationError(Exception):
    pass


class Translator(Protocol):
    def translate(self, lines: list[str], source: str, target: str) -> list[str]: ...


class NoopTranslator:
    def translate(self, lines: list[str], source: str, target: str) -> list[str]:
        return list(lines)


class GoogleTranslator:
    """Free Google Translate web endpoint via deep-translator. Needs internet, no API key."""

    def translate(self, lines: list[str], source: str, target: str) -> list[str]:
        from deep_translator import GoogleTranslator as _Google

        try:
            client = _Google(source="auto", target=target)
            return [client.translate(line) or line if line else line for line in lines]
        except Exception as exc:  # deep-translator raises many different types
            raise TranslationError(f"Translation failed: {exc}") from exc


class ArgosTranslator:
    """Offline translation with Argos Translate. Language packages download on first use."""

    def translate(self, lines: list[str], source: str, target: str) -> list[str]:
        try:
            import argostranslate.package
            import argostranslate.translate
        except ImportError as exc:
            raise TranslationError(
                "Argos Translate isn't installed. Run: pip install argostranslate"
            ) from exc

        src, dst = base_code(source), base_code(target)
        if not self._has_pair(argostranslate.translate, src, dst):
            argostranslate.package.update_package_index()
            for pkg in argostranslate.package.get_available_packages():
                if pkg.from_code == src and pkg.to_code == dst:
                    argostranslate.package.install_from_path(pkg.download())
                    break
            else:
                raise TranslationError(f"No offline model for {src} -> {dst}.")
        return [argostranslate.translate.translate(line, src, dst) for line in lines]

    @staticmethod
    def _has_pair(module, src: str, dst: str) -> bool:
        installed = {lang.code: lang for lang in module.get_installed_languages()}
        return src in installed and dst in installed and installed[src].get_translation(installed[dst]) is not None


# ISO 639-1 (what Whisper reports and the picker uses) -> NLLB's FLORES-200 codes.
NLLB_CODES: dict[str, str] = {
    "af": "afr_Latn", "am": "amh_Ethi", "ar": "arb_Arab", "as": "asm_Beng",
    "az": "azj_Latn", "be": "bel_Cyrl", "bg": "bul_Cyrl", "bn": "ben_Beng",
    "bs": "bos_Latn", "ca": "cat_Latn", "cs": "ces_Latn", "cy": "cym_Latn",
    "da": "dan_Latn", "de": "deu_Latn", "el": "ell_Grek", "en": "eng_Latn",
    "es": "spa_Latn", "et": "est_Latn", "fa": "pes_Arab", "fi": "fin_Latn",
    "fr": "fra_Latn", "ga": "gle_Latn", "gl": "glg_Latn", "gu": "guj_Gujr",
    "ha": "hau_Latn", "he": "heb_Hebr", "hi": "hin_Deva", "hr": "hrv_Latn",
    "hu": "hun_Latn", "hy": "hye_Armn", "id": "ind_Latn", "is": "isl_Latn",
    "it": "ita_Latn", "ja": "jpn_Jpan", "jw": "jav_Latn", "ka": "kat_Geor",
    "kk": "kaz_Cyrl", "km": "khm_Khmr", "kn": "kan_Knda", "ko": "kor_Hang",
    "lo": "lao_Laoo", "lt": "lit_Latn", "lv": "lvs_Latn", "mk": "mkd_Cyrl",
    "ml": "mal_Mlym", "mn": "khk_Cyrl", "mr": "mar_Deva", "ms": "zsm_Latn",
    "my": "mya_Mymr", "ne": "npi_Deva", "nl": "nld_Latn", "no": "nob_Latn",
    "pa": "pan_Guru", "pl": "pol_Latn", "ps": "pbt_Arab", "pt": "por_Latn",
    "ro": "ron_Latn", "ru": "rus_Cyrl", "sd": "snd_Arab", "si": "sin_Sinh",
    "sk": "slk_Latn", "sl": "slv_Latn", "so": "som_Latn", "sq": "als_Latn",
    "sr": "srp_Cyrl", "sv": "swe_Latn", "sw": "swh_Latn", "ta": "tam_Taml",
    "te": "tel_Telu", "tg": "tgk_Cyrl", "th": "tha_Thai", "tl": "tgl_Latn",
    "tr": "tur_Latn", "uk": "ukr_Cyrl", "ur": "urd_Arab", "uz": "uzn_Latn",
    "vi": "vie_Latn", "yo": "yor_Latn", "zh": "zho_Hans",
}


def nllb_code(code: str) -> str:
    try:
        return NLLB_CODES[base_code(code)]
    except KeyError:
        raise TranslationError(f"The offline translator doesn't support language '{code}'.") from None


class NllbTranslator:
    """Offline translation with Meta's open-source NLLB-200 model (200 languages).

    The model (about 2.5 GB for the 600M version) downloads on first use and
    is reused across jobs.
    """

    def __init__(self, model_name: str = "facebook/nllb-200-distilled-600M", batch_size: int = 16):
        self.model_name = model_name
        self.batch_size = batch_size
        self._tokenizer = None
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                try:
                    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
                except ImportError as exc:
                    raise TranslationError(
                        "NLLB needs extra packages. Run: pip install -r requirements-models.txt"
                    ) from exc
                self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                self._model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name)
            return self._tokenizer, self._model

    def translate(self, lines: list[str], source: str, target: str) -> list[str]:
        src, dst = nllb_code(source), nllb_code(target)
        tokenizer, model = self._load()
        tokenizer.src_lang = src
        out: list[str] = []
        try:
            for i in range(0, len(lines), self.batch_size):
                batch = lines[i : i + self.batch_size]
                inputs = tokenizer(batch, return_tensors="pt", padding=True, truncation=True)
                generated = model.generate(
                    **inputs,
                    forced_bos_token_id=tokenizer.convert_tokens_to_ids(dst),
                    max_new_tokens=256,
                )
                out.extend(tokenizer.batch_decode(generated, skip_special_tokens=True))
        except Exception as exc:
            raise TranslationError(f"Translation failed: {exc}") from exc
        return out


def make_translator(name: str) -> Translator:
    name = (name or "none").lower()
    if name == "nllb":
        return NllbTranslator()
    if name == "google":
        return GoogleTranslator()
    if name == "argos":
        return ArgosTranslator()
    if name == "none":
        return NoopTranslator()
    raise ValueError(f"Unknown TRANSLATOR '{name}'. Use nllb, argos, google, or none.")
