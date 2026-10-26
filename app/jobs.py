"""In-memory job queue: download -> transcribe -> translate, run on a worker thread."""

import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .downloader import DownloadError
from .languages import base_code
from .transcriber import Transcriber
from .translator import TranslationError, Translator


@dataclass
class Line:
    start: float
    end: float
    text: str
    translation: Optional[str] = None


@dataclass
class Job:
    id: str
    source: str
    target_language: str
    # The language being sung, or None to let Whisper detect it.
    source_language: Optional[str] = None
    status: str = "queued"  # queued, downloading, transcribing, translating, done, error
    title: Optional[str] = None
    detected_language: Optional[str] = None
    lines: list[Line] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# Given (job, work_dir) returns the audio path, setting job.title if it learns one.
AudioFetcher = Callable[[Job, Path], Path]


class JobManager:
    def __init__(
        self,
        transcriber: Transcriber,
        translator: Translator,
        work_dir: Path,
        workers: int = 1,
    ):
        self.transcriber = transcriber
        self.translator = translator
        self.work_dir = work_dir
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        # One worker by default: Whisper already uses every CPU core.
        self._pool = ThreadPoolExecutor(max_workers=workers)

    def submit(
        self,
        source: str,
        target_language: str,
        fetch_audio: AudioFetcher,
        source_language: Optional[str] = None,
    ) -> Job:
        job = Job(
            id=uuid.uuid4().hex,
            source=source,
            target_language=target_language,
            source_language=source_language,
        )
        with self._lock:
            self._jobs[job.id] = job
        self._pool.submit(self._run, job, fetch_audio)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def _run(self, job: Job, fetch_audio: AudioFetcher) -> None:
        job_dir = self.work_dir / job.id
        try:
            job.status = "downloading"
            audio = fetch_audio(job, job_dir)

            job.status = "transcribing"
            language = base_code(job.source_language) if job.source_language else None
            transcript = self.transcriber.transcribe(audio, language)
            job.detected_language = transcript.language
            lines = [Line(s.start, s.end, s.text) for s in transcript.segments]

            target = job.target_language
            if lines and target != "original" and base_code(target) != base_code(transcript.language):
                job.status = "translating"
                translated = self.translator.translate(
                    [line.text for line in lines], transcript.language, target
                )
                for line, text in zip(lines, translated):
                    line.translation = text

            job.lines = lines
            job.status = "done"
        except (DownloadError, TranslationError) as exc:
            job.error = str(exc)
            job.status = "error"
        except Exception as exc:  # keep the worker alive and tell the user something
            job.error = f"Unexpected error: {exc}"
            job.status = "error"
        finally:
            # Audio is only needed while the job runs; don't keep it around.
            shutil.rmtree(job_dir, ignore_errors=True)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True)
