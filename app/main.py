"""HTTP API and static web UI."""

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Settings, get_settings
from .downloader import DownloadError, download_audio, probe_duration, validate_url
from .jobs import Job, JobManager
from .languages import LANGUAGES
from .transcriber import Transcriber, VocalIsolatingTranscriber, WhisperTranscriber, demucs_available
from .translator import Translator, make_translator

STATIC_DIR = Path(__file__).parent / "static"


class LinkRequest(BaseModel):
    url: str
    target_language: str = "original"


def create_app(
    settings: Optional[Settings] = None,
    transcriber: Optional[Transcriber] = None,
    translator: Optional[Translator] = None,
) -> FastAPI:
    settings = settings or get_settings()
    if transcriber is None:
        transcriber = WhisperTranscriber(settings.whisper_model, settings.whisper_device)
        if settings.isolate_vocals and demucs_available():
            transcriber = VocalIsolatingTranscriber(transcriber)
    manager = JobManager(
        transcriber=transcriber,
        translator=translator or make_translator(settings.translator),
        work_dir=settings.work_dir,
    )

    app = FastAPI(title="MusicLyricsEasy")
    app.state.jobs = manager

    def check_language(code: str) -> None:
        if code not in LANGUAGES:
            raise HTTPException(400, f"Unsupported language '{code}'.")

    @app.get("/api/languages")
    def languages() -> dict[str, str]:
        return LANGUAGES

    @app.post("/api/jobs", status_code=202)
    def create_job_from_link(req: LinkRequest) -> dict:
        check_language(req.target_language)
        try:
            url = validate_url(req.url, settings.block_private_urls)
        except DownloadError as exc:
            raise HTTPException(400, str(exc)) from exc

        def fetch(job: Job, job_dir: Path) -> Path:
            audio, title = download_audio(url, job_dir, settings.max_duration_seconds)
            job.title = title
            return audio

        return manager.submit(url, req.target_language, fetch).to_dict()

    @app.post("/api/jobs/upload", status_code=202)
    async def create_job_from_upload(
        file: UploadFile = File(...), target_language: str = Form("original")
    ) -> dict:
        check_language(target_language)
        limit = settings.max_upload_mb * 1024 * 1024
        data = await file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB.")
        if not data:
            raise HTTPException(400, "The uploaded file is empty.")
        name = Path(file.filename or "upload").name

        def fetch(job: Job, job_dir: Path) -> Path:
            job_dir.mkdir(parents=True, exist_ok=True)
            path = job_dir / f"upload{Path(name).suffix[:10]}"
            path.write_bytes(data)
            duration = probe_duration(path)
            if duration is not None and duration > settings.max_duration_seconds:
                raise DownloadError(
                    f"Audio is {int(duration)}s long; the limit is {settings.max_duration_seconds}s."
                )
            job.title = name
            return path

        return manager.submit(name, target_language, fetch).to_dict()

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found.")
        return job.to_dict()

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
