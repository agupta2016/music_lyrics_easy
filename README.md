# MusicLyricsEasy

Paste a link to a song or video (YouTube or any of the [sites yt-dlp supports](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)), pick a language, and get the lyrics. You can also upload an audio or video file directly.

How it works:

1. **Download** the audio with [yt-dlp](https://github.com/yt-dlp/yt-dlp) and convert it with ffmpeg.
2. **Isolate the vocals** with [Demucs](https://github.com/facebookresearch/demucs), so the instruments don't confuse transcription. This is optional and runs when Demucs is installed.
3. **Transcribe** it locally with [Whisper](https://github.com/openai/whisper), via [faster-whisper](https://github.com/SYSTRAN/faster-whisper). Whisper detects the sung language on its own.
4. **Translate** each line into the language you picked with Meta's open-source [NLLB-200](https://huggingface.co/facebook/nllb-200-distilled-600M) model, unless you chose "Original" or it is already in that language.

Every model runs on your own machine, so lyrics never leave it.

The result shows each line, with optional timestamps and the original text under the translation, and a Copy button.

## Run it locally

You need Python 3.10+. The app uses a bundled copy of ffmpeg (from `imageio-ffmpeg`) when ffmpeg isn't installed, so links work without extra setup. Installing ffmpeg system-wide is still recommended, because Demucs vocal isolation needs it on the PATH:

```bash
# macOS:   brew install ffmpeg
# Ubuntu:  sudo apt install ffmpeg
# Windows: winget install ffmpeg     (then open a new terminal so PATH updates)

git clone https://github.com/agupta2016/music_lyrics_easy.git
cd music_lyrics_easy
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-models.txt
uvicorn app.main:app --reload
```

`requirements-models.txt` adds PyTorch, NLLB and Demucs (about 2 GB). On a machine without an NVIDIA GPU, install the smaller CPU build of PyTorch first: `pip install torch --index-url https://download.pytorch.org/whl/cpu`. For a lighter setup, install only `requirements.txt` and set `TRANSLATOR=argos` (see Settings).

Open http://127.0.0.1:8000 and paste a link.

The first job downloads the Whisper model (about 460 MB for `small`), the NLLB model (about 2.5 GB) when it first translates, and the Demucs model (about 80 MB), so it takes longer than later ones. On a CPU, Demucs adds roughly a minute or two per song.

### Use your NVIDIA GPU (recommended)

On a GPU, the app uses Whisper `large-v3`, the most accurate open model for Hindi and English, and a song takes well under a minute. You don't need the full CUDA toolkit. Install NVIDIA's libraries with pip and the app finds them on its own:

```bash
pip install -r requirements-gpu.txt
```

Restart the app. The log line `Loading Whisper model large-v3 on auto` confirms it. Without a GPU, the app uses `medium`, which is slower and less accurate on Hindi.

### With Docker

```bash
docker build -t music-lyrics-easy .
docker run -p 8000:8000 music-lyrics-easy
```

## Settings

Set these as environment variables before starting the server.

| Variable | Default | What it does |
| --- | --- | --- |
| `WHISPER_MODEL` | `auto` | `auto` uses `large-v3` on an NVIDIA GPU and `medium` on a CPU. You can also set `tiny`, `base`, `small`, `medium`, `large-v3`, `large-v3-turbo`, or a local model folder. `large-v3` is the most accurate for Hindi; `large-v3-turbo` is faster but noticeably weaker on Hindi. |
| `WHISPER_DEVICE` | `auto` | `cpu`, `cuda`, or `auto`. If the GPU's CUDA libraries are missing, the app falls back to `cpu`. |
| `TRANSLATOR` | `nllb` | `nllb` is Meta's open-source NLLB-200 model, offline, and good with Indian and other non-European languages (needs `requirements-models.txt`). `argos` is also offline and lighter: run `pip install argostranslate`, and language packs download on first use. `google` uses Google Translate's free web endpoint, which sends lyrics to Google. `none` turns translation off. |
| `ISOLATE_VOCALS` | `true` | Run Demucs to separate the vocals before transcribing, when Demucs is installed. Set `false` to skip it for speed. |
| `MAX_DURATION_SECONDS` | `3600` | Longest audio accepted (1 hour). Whisper handles long audio fine; this only keeps one very long video from tying up the machine. |
| `MAX_UPLOAD_MB` | `50` | Largest upload accepted. |
| `BLOCK_PRIVATE_URLS` | `true` | Refuses links to localhost or private network addresses. |
| `WORK_DIR` | `data/work` | Where audio is kept while a job runs. It is deleted when the job finishes. |

## API

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| `GET` | `/api/languages` |  | `{code: name}` for the picker |
| `POST` | `/api/jobs` | JSON `{"url": "...", "target_language": "hi"}` | A job with status `queued` |
| `POST` | `/api/jobs/upload` | Form fields `file`, `target_language` | A job with status `queued` |
| `GET` | `/api/jobs/{id}` |  | The job: `status` (`queued`, `downloading`, `transcribing`, `translating`, `done`, `error`), `title`, `detected_language`, `lines[]` with `start`, `end`, `text`, `translation`, and `error` |

Use `"original"` as `target_language` to skip translation.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Tests use synthetic sine-wave audio and made-up transcription text, never real recordings or lyrics. One test runs yt-dlp and ffmpeg for real against a file served from localhost. A smoke test that runs the real Whisper model is skipped by default; turn it on with `RUN_WHISPER_TESTS=1` (it downloads the `tiny` model).

## Project layout

```
app/
  main.py         HTTP API and static UI
  jobs.py         Background job queue: download, transcribe, translate
  downloader.py   yt-dlp download, URL checks, duration limit
  transcriber.py  Whisper transcription, Demucs vocal isolation
  translator.py   NLLB / Argos / Google / no-op translation
  languages.py    Languages in the picker
  config.py       Environment settings
  static/         Web UI (plain HTML, CSS, JS)
tests/
```

## Troubleshooting

- **"ffmpeg isn't installed"**: run `pip install -r requirements.txt` again to get the bundled copy, or install ffmpeg as shown above.
- **"Audio is … long; the limit is …"**: the video is longer than `MAX_DURATION_SECONDS`. Raise it, for example `MAX_DURATION_SECONDS=7200 uvicorn app.main:app` (on Windows PowerShell: `$env:MAX_DURATION_SECONDS=7200` first).
- **"cublas64_12.dll is not found"** (or another CUDA library): Whisper found an NVIDIA GPU but not the CUDA 12 libraries. The app now switches to the CPU on its own. To skip the GPU attempt, set `WHISPER_DEVICE=cpu`. To use the GPU, run `pip install -r requirements-gpu.txt` and restart.
- **A site refuses the download**: update yt-dlp with `pip install -U yt-dlp`.
- **Lyrics are inaccurate** (missing or wrong words): in order of impact,
  1. Install ffmpeg system-wide so Demucs can strip the music out before transcription. The server log warns at startup when it can't.
  2. Pick the language being sung instead of "Detect automatically".
  3. Use the GPU so the app runs `large-v3` (see "Use your NVIDIA GPU"), or set `WHISPER_MODEL=large-v3` on a CPU if you can wait (about 3 GB, several minutes per song).

## Limitations

- Whisper transcribes sung vocals less accurately than speech, especially over loud instruments. A larger model helps.
- Jobs are kept in memory, so they disappear when the server restarts. One job runs at a time.
- Line breaks follow Whisper's segments, which don't always match the song's lines.
- The private-address check runs on the link you paste; it doesn't follow redirects. Don't expose the server to the public internet without putting it behind authentication.
- Some sites block automated downloads, and yt-dlp needs updating now and then (`pip install -U yt-dlp`).

## Responsible use

The NLLB model is licensed for non-commercial use only (CC BY-NC 4.0), which fits personal use with family and friends.

Only process audio you have the right to use. Downloading from some sites may break their terms of service, and lyrics are often copyrighted, so don't redistribute what the app produces without permission.
