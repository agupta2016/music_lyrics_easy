"""Runtime settings, read from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Whisper model size: tiny, base, small, medium, large-v3. Bigger is slower but more accurate.
    whisper_model: str = field(default_factory=lambda: os.getenv("WHISPER_MODEL", "small"))
    # "cpu" or "cuda". "auto" lets faster-whisper decide.
    whisper_device: str = field(default_factory=lambda: os.getenv("WHISPER_DEVICE", "auto"))
    # "nllb" (open-source, offline), "argos" (offline, lighter), "google" (free web
    # translation, sends lyrics to Google), or "none".
    translator: str = field(default_factory=lambda: os.getenv("TRANSLATOR", "nllb"))
    # Separate the vocals from the music with Demucs before transcribing, when it's installed.
    isolate_vocals: bool = field(default_factory=lambda: _env_bool("ISOLATE_VOCALS", True))
    # Longest audio we accept, in seconds.
    max_duration_seconds: int = field(
        default_factory=lambda: int(os.getenv("MAX_DURATION_SECONDS", "900"))
    )
    # Largest upload we accept, in megabytes.
    max_upload_mb: int = field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_MB", "50")))
    # Refuse links that resolve to localhost or private network addresses.
    block_private_urls: bool = field(
        default_factory=lambda: _env_bool("BLOCK_PRIVATE_URLS", True)
    )
    # Where downloaded and uploaded audio is kept while a job runs.
    work_dir: Path = field(
        default_factory=lambda: Path(os.getenv("WORK_DIR", "data/work")).resolve()
    )


def get_settings() -> Settings:
    return Settings()
