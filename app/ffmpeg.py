"""Locate ffmpeg: the system install if there is one, else the copy bundled with imageio-ffmpeg."""

import functools
import re
import shutil
import subprocess
from pathlib import Path


class FFmpegMissing(Exception):
    pass


INSTALL_HINT = (
    "ffmpeg isn't installed. Run: pip install imageio-ffmpeg "
    "(or install ffmpeg: winget install ffmpeg / brew install ffmpeg / sudo apt install ffmpeg)."
)


@functools.lru_cache(maxsize=1)
def ffmpeg_path() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except RuntimeError:
        return None


def require_ffmpeg() -> str:
    path = ffmpeg_path()
    if path is None:
        raise FFmpegMissing(INSTALL_HINT)
    return path


_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def probe_duration(path: Path) -> float | None:
    """Duration in seconds, read from ffmpeg's file info, or None if it can't tell."""
    exe = ffmpeg_path()
    if exe is None:
        return None
    try:
        # With no output file ffmpeg exits non-zero, but it still prints the file info.
        stderr = subprocess.run(
            [exe, "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=30
        ).stderr
    except (OSError, subprocess.SubprocessError):
        return None
    match = _DURATION.search(stderr)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
