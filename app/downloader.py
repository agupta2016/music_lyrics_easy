"""Fetch audio or video from a link (YouTube or any site yt-dlp supports)."""

import ipaddress
import re
import socket
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from .ffmpeg import FFmpegMissing, probe_duration, require_ffmpeg

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


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

    try:
        ffmpeg = require_ffmpeg()
    except FFmpegMissing as exc:
        raise DownloadError(str(exc)) from exc
    dest_dir.mkdir(parents=True, exist_ok=True)
    rejected: list[str] = []

    def too_long(info, *, incomplete):
        duration = info.get("duration")
        if duration and duration > max_duration_seconds:
            reason = too_long_message(duration, max_duration_seconds)
            rejected.append(reason)
            return reason
        return None

    options = {
        "format": "bestaudio/best",
        "outtmpl": str(dest_dir / "audio.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "color": {"stdout": "no_color", "stderr": "no_color"},
        "ffmpeg_location": ffmpeg,
        "match_filter": too_long,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}
        ],
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(_ANSI.sub("", str(exc)).replace("ERROR: ", "").strip()) from exc

    if rejected:
        # match_filter rejections finish without an error or a file.
        raise DownloadError(rejected[0])
    if info is None:
        raise DownloadError("Nothing could be downloaded from that link.")

    audio = dest_dir / "audio.mp3"
    if not audio.exists():
        raise DownloadError("The download finished but no audio file was produced.")
    # Direct file links often report no duration up front, so check the real file too.
    duration = probe_duration(audio)
    if duration is not None and duration > max_duration_seconds:
        raise DownloadError(too_long_message(duration, max_duration_seconds))
    return audio, info.get("title") or "Untitled"


# Video heights offered in the UI. "best" takes whatever the site's best is.
VIDEO_QUALITIES = {"best": None, "1080": 1080, "720": 720, "480": 480, "360": 360}

ProgressCallback = Callable[[Optional[float]], None]


def _video_format(height: Optional[int]) -> str:
    """Prefer H.264 + AAC in mp4 so the file plays everywhere, then fall back to anything."""
    cap = f"[height<={height}]" if height else ""
    return (
        f"bv*{cap}[vcodec^=avc1]+ba[ext=m4a]/"
        f"b{cap}[ext=mp4]/"
        f"bv*{cap}+ba/"
        f"b{cap}/"
        "bv*+ba/b"
    )


def download_video(
    url: str,
    dest_dir: Path,
    max_duration_seconds: int,
    quality: str = "best",
    on_progress: Optional[ProgressCallback] = None,
) -> tuple[Path, str]:
    """Download the video itself (picture and sound), merged into one file.

    Returns the video file path and the media title. on_progress gets a 0-100
    percentage, or None while the size isn't known yet.
    """
    import yt_dlp  # imported lazily so the API can start without it in tests

    if quality not in VIDEO_QUALITIES:
        raise DownloadError(f"Unsupported video quality '{quality}'.")
    try:
        ffmpeg = require_ffmpeg()
    except FFmpegMissing as exc:
        raise DownloadError(str(exc)) from exc
    dest_dir.mkdir(parents=True, exist_ok=True)
    rejected: list[str] = []

    def too_long(info, *, incomplete):
        duration = info.get("duration")
        if duration and duration > max_duration_seconds:
            reason = too_long_message(duration, max_duration_seconds)
            rejected.append(reason)
            return reason
        return None

    def progress(status: dict) -> None:
        if on_progress is None or status.get("status") != "downloading":
            return
        total = status.get("total_bytes") or status.get("total_bytes_estimate")
        done = status.get("downloaded_bytes")
        on_progress(min(100.0, 100.0 * done / total) if total and done is not None else None)

    options = {
        "format": _video_format(VIDEO_QUALITIES[quality]),
        "merge_output_format": "mp4",
        "outtmpl": str(dest_dir / "video.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "color": {"stdout": "no_color", "stderr": "no_color"},
        "ffmpeg_location": ffmpeg,
        "match_filter": too_long,
        "progress_hooks": [progress],
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(_ANSI.sub("", str(exc)).replace("ERROR: ", "").strip()) from exc

    if rejected:
        raise DownloadError(rejected[0])
    if info is None:
        raise DownloadError("Nothing could be downloaded from that link.")

    files = [p for p in dest_dir.glob("video.*") if p.suffix not in {".part", ".ytdl"}]
    if not files:
        raise DownloadError("The download finished but no video file was produced.")
    video = max(files, key=lambda p: p.stat().st_size)
    duration = probe_duration(video)
    if duration is not None and duration > max_duration_seconds:
        raise DownloadError(too_long_message(duration, max_duration_seconds))
    return video, info.get("title") or "Untitled"


def too_long_message(duration: float, limit: int) -> str:
    return (
        f"Audio is {_minutes(duration)} long; the limit is {_minutes(limit)}. "
        "Raise MAX_DURATION_SECONDS to allow longer audio."
    )


def _minutes(seconds: float) -> str:
    return f"{int(seconds)} s" if seconds < 120 else f"{int(seconds) // 60} min"
