"""Languages offered in the target-language picker (ISO 639-1 codes)."""

LANGUAGES: dict[str, str] = {
    "original": "Original (no translation)",
    "ar": "Arabic",
    "bn": "Bengali",
    "zh-CN": "Chinese (Simplified)",
    "nl": "Dutch",
    "en": "English",
    "fr": "French",
    "de": "German",
    "el": "Greek",
    "gu": "Gujarati",
    "he": "Hebrew",
    "hi": "Hindi",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "kn": "Kannada",
    "ko": "Korean",
    "ml": "Malayalam",
    "mr": "Marathi",
    "fa": "Persian",
    "pl": "Polish",
    "pt": "Portuguese",
    "pa": "Punjabi",
    "ru": "Russian",
    "es": "Spanish",
    "sv": "Swedish",
    "ta": "Tamil",
    "te": "Telugu",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "vi": "Vietnamese",
}


def base_code(code: str) -> str:
    """'zh-CN' -> 'zh'. Whisper and Argos use bare codes."""
    return code.split("-")[0].lower()
