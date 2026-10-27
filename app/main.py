"""HTTP API and static web UI."""

import logging
import shutil
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Settings, get_settings
from .downloader import (
    VIDEO_QUALITIES,
    DownloadError,
    download_audio,
    download_video,
    too_long_message,
    validate_url,
)
from .ffmpeg import INSTALL_HINT, ffmpeg_path, probe_duration
from .jobs import Job, JobManager
from .languages import LANGUAGES
from .transcriber import (
    LanguageRoutingTranscriber,
    Transcriber,
    VocalIsolatingTranscriber,
    WhisperTranscriber,
    demucs_available,
    parse_language_models,
)
from .translator import Translator, make_translator
from .videos import VideoDownload, VideoDownloadManager

STATIC_DIR = Path(__file__).parent / "static"
log = logging.getLogger(__name__)


class LinkRequest(BaseModel):
    url: str
    target_language: str = "original"
    source_language: str = "auto"


class VideoRequest(BaseModel):
    url: str
    quality: str = "best"


def create_app(
    settings: Optional[Settings] = None,
    transcriber: Optional[Transcriber] = None,
    translator: Optional[Translator] = None,
) -> FastAPI:
    settings = settings or get_settings()
    if ffmpeg_path() is None:
        log.warning("Links won't work until ffmpeg is available. %s", INSTALL_HINT)
    if transcriber is None:
        transcriber = WhisperTranscriber(
            settings.whisper_model, settings.whisper_device, vad=settings.whisper_vad
        )
        language_models = parse_language_models(settings.whisper_language_models)
        if language_models:
            transcriber = LanguageRoutingTranscriber(
                transcriber,
                {
                    lang: WhisperTranscriber(model, settings.whisper_device, vad=settings.whisper_vad)
                    for lang, model in language_models.items()
                },
            )
        if settings.isolate_vocals and demucs_available():
            if shutil.which("ffmpeg") is None:
                log.warning(
                    "Demucs needs ffmpeg installed system-wide to isolate vocals; without it "
                    "songs are transcribed with the music in, which is less accurate."
                )
            transcriber = VocalIsolatingTranscriber(transcriber)
    manager = JobManager(
        transcriber=transcriber,
        translator=translator or make_translator(settings.translator),
        work_dir=settings.work_dir,
    )

    videos = VideoDownloadManager(
        work_dir=settings.work_dir / "videos", keep_seconds=settings.video_keep_minutes * 60
    )

    app = FastAPI(title="MusicLyricsEasy")
    app.state.jobs = manager
    app.state.videos = videos

    def check_language(code: str) -> None:
        if code not in LANGUAGES:
            raise HTTPException(400, f"Unsupported language '{code}'.")

    def sung_language(code: str) -> Optional[str]:
        if code in ("", "auto"):
            return None
        if code not in LANGUAGES or code == "original":
            raise HTTPException(400, f"Unsupported sung language '{code}'.")
        return code

    @app.get("/api/languages")
    def languages() -> dict[str, str]:
        return LANGUAGES

    @app.post("/api/jobs", status_code=202)
    def create_job_from_link(req: LinkRequest) -> dict:
        check_language(req.target_language)
        source_language = sung_language(req.source_language)
        try:
            url = validate_url(req.url, settings.block_private_urls)
        except DownloadError as exc:
            raise HTTPException(400, str(exc)) from exc

        def fetch(job: Job, job_dir: Path) -> Path:
            audio, title = download_audio(url, job_dir, settings.max_duration_seconds)
            job.title = title
            return audio

        return manager.submit(url, req.target_language, fetch, source_language).to_dict()

    @app.post("/api/jobs/upload", status_code=202)
    async def create_job_from_upload(
        file: UploadFile = File(...),
        target_language: str = Form("original"),
        source_language: str = Form("auto"),
    ) -> dict:
        check_language(target_language)
        sung = sung_language(source_language)
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
                raise DownloadError(too_long_message(duration, settings.max_duration_seconds))
            job.title = name
            return path

        return manager.submit(name, target_language, fetch, sung).to_dict()

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found.")
        return job.to_dict()

    @app.post("/api/videos", status_code=202)
    def create_video_download(req: VideoRequest) -> dict:
        if req.quality not in VIDEO_QUALITIES:
            raise HTTPException(400, f"Unsupported video quality '{req.quality}'.")
        try:
            url = validate_url(req.url, settings.block_private_urls)
        except DownloadError as exc:
            raise HTTPException(400, str(exc)) from exc

        def fetch(item: VideoDownload, item_dir: Path) -> tuple[Path, str]:
            def on_progress(percent: Optional[float]) -> None:
                item.progress = percent

            return download_video(
                url, item_dir, settings.max_duration_seconds, req.quality, on_progress
            )

        return videos.submit(url, req.quality, fetch).to_dict()

    @app.get("/api/videos/{download_id}")
    def get_video_download(download_id: str) -> dict:
        item = videos.get(download_id)
        if item is None:
            raise HTTPException(404, "Download not found.")
        return item.to_dict()

    @app.get("/api/videos/{download_id}/file")
    def get_video_file(download_id: str) -> FileResponse:
        item = videos.get(download_id)
        if item is None or item.status != "done" or item.path is None or not item.path.exists():
            raise HTTPException(404, "That video isn't available. It may have expired; download it again.")
        return FileResponse(item.path, filename=item.filename(), media_type="application/octet-stream")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
