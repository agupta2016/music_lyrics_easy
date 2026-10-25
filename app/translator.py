"""Translate transcribed lines into the language the user picked."""

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


def make_translator(name: str) -> Translator:
    name = (name or "none").lower()
    if name == "google":
        return GoogleTranslator()
    if name == "argos":
        return ArgosTranslator()
    if name == "none":
        return NoopTranslator()
    raise ValueError(f"Unknown TRANSLATOR '{name}'. Use google, argos, or none.")
