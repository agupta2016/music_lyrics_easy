"""Video downloads: fetch the video from a link and keep it until the user saves it."""

import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .downloader import DownloadError

_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


@dataclass
class VideoDownload:
    id: str
    source: str
    quality: str = "best"
    status: str = "queued"  # queued, downloading, done, error
    title: Optional[str] = None
    progress: Optional[float] = None  # 0-100 while downloading, when the size is known
    size_bytes: Optional[int] = None
    error: Optional[str] = None
    path: Optional[Path] = None
    finished_at: Optional[float] = field(default=None, repr=False)

    def filename(self) -> str:
        """A name that's safe to save on Windows, macOS and Linux."""
        stem = " ".join(_UNSAFE_FILENAME.sub(" ", self.title or "video").split())
        stem = stem.strip(" .")[:150] or "video"
        suffix = self.path.suffix if self.path else ".mp4"
        return f"{stem}{suffix}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "quality": self.quality,
            "status": self.status,
            "title": self.title,
            "progress": self.progress,
            "size_bytes": self.size_bytes,
            "filename": self.filename() if self.status == "done" else None,
            "error": self.error,
        }


# Given (download, work_dir) returns (video path, title).
VideoFetcher = Callable[[VideoDownload, Path], tuple[Path, str]]


class VideoDownloadManager:
    """Runs downloads on their own threads, so they don't wait behind transcription."""

    def __init__(self, work_dir: Path, keep_seconds: int = 3600, workers: int = 2):
        self.work_dir = work_dir
        self.keep_seconds = keep_seconds
        self._items: dict[str, VideoDownload] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers)
        # Downloads live in memory, so files left by an earlier run can't be fetched anymore.
        shutil.rmtree(work_dir, ignore_errors=True)

    def submit(self, source: str, quality: str, fetch: VideoFetcher) -> VideoDownload:
        self.prune()
        item = VideoDownload(id=uuid.uuid4().hex, source=source, quality=quality)
        with self._lock:
            self._items[item.id] = item
        self._pool.submit(self._run, item, fetch)
        return item

    def get(self, download_id: str) -> Optional[VideoDownload]:
        with self._lock:
            return self._items.get(download_id)

    def _run(self, item: VideoDownload, fetch: VideoFetcher) -> None:
        item_dir = self.work_dir / item.id
        try:
            item.status = "downloading"
            path, title = fetch(item, item_dir)
            item.title = title
            item.path = path
            item.size_bytes = path.stat().st_size
            item.progress = 100.0
            item.status = "done"
        except DownloadError as exc:
            item.error = str(exc)
            item.status = "error"
        except Exception as exc:  # keep the worker alive and tell the user something
            item.error = f"Unexpected error: {exc}"
            item.status = "error"
        finally:
            item.finished_at = time.time()
            if item.status != "done":
                shutil.rmtree(item_dir, ignore_errors=True)

    def prune(self) -> None:
        """Delete finished videos older than keep_seconds, so the disk doesn't fill up."""
        cutoff = time.time() - self.keep_seconds
        with self._lock:
            old = [i for i in self._items.values() if i.finished_at and i.finished_at < cutoff]
            for item in old:
                del self._items[item.id]
        for item in old:
            shutil.rmtree(self.work_dir / item.id, ignore_errors=True)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True)
