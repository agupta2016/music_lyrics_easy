"""Fetch the audio track from a link (YouTube or any site yt-dlp supports)."""

import ipaddress
import json
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse


class DownloadError(Exception):
    """Raised when a link can't be turned into an audio file."""


def validate_url(url: str, block_private: bool = True) -> str:
    """Accept only http(s) links, and optionally refuse ones pointing at private hosts."""
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise DownloadError("Please paste a full http:// or https:// link.")

    if block_private:
        try:
            infos = socket.getaddrinfo(parsed.hostname, None)
        except socket.gaierror as exc:
            raise DownloadError(f"Couldn't resolve host '{parsed.hostname}'.") from exc
        for info in infos:
            addr = ipaddress.ip_address(info[4][0])
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                raise DownloadError("Links to local or private network addresses aren't allowed.")
    return url


def download_audio(url: str, dest_dir: Path, max_duration_seconds: int) -> tuple[Path, str]:
    """Download the best audio stream and convert it to mp3.

    Returns the audio file path and the media title.
    """
    import yt_dlp  # imported lazily so the API can start without it in tests

    dest_dir.mkdir(parents=True, exist_ok=True)

    def too_long(info, *, incomplete):
        duration = info.get("duration")
        if duration and duration > max_duration_seconds:
            return f"Audio is {int(duration)}s long; the limit is {max_duration_seconds}s."
        return None

    options = {
        "format": "bestaudio/best",
        "outtmpl": str(dest_dir / "audio.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "match_filter": too_long,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}
        ],
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(str(exc).replace("ERROR: ", "")) from exc

    if info is None:
        raise DownloadError("Nothing could be downloaded from that link.")

    audio = dest_dir / "audio.mp3"
    if not audio.exists():
        # match_filter rejections finish without a file.
        raise DownloadError(
            f"The audio was skipped. It may be longer than {max_duration_seconds}s."
        )
    # Direct file links often report no duration up front, so check the real file too.
    duration = probe_duration(audio)
    if duration is not None and duration > max_duration_seconds:
        raise DownloadError(
            f"Audio is {int(duration)}s long; the limit is {max_duration_seconds}s."
        )
    return audio, info.get("title") or "Untitled"


def probe_duration(path: Path) -> float | None:
    """Duration in seconds according to ffprobe, or None if it can't tell."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout
        return float(json.loads(out)["format"]["duration"])
    except (OSError, subprocess.SubprocessError, KeyError, ValueError):
        return None
