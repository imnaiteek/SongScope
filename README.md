# SongScope — Technical Music Analysis

**Understand any song.** Upload an audio file or paste a YouTube link and SongScope analyses the *actual audio* to estimate
tempo, meter, key, chords, progressions, song structure, beats, drum pattern, melodic pitch, loudness (LUFS),
frequency balance and — optionally — separated stems. Every result carries a confidence score and is labelled
**detected**, **estimated**, **inferred** or **uncertain**; weak results are reported as undetermined instead of guessed.

```
Browser (Next.js · React · WaveSurfer.js · canvas charts)
   │  REST (JSON), XHR upload with progress, range-request audio
   ▼
FastAPI  ──►  DB-backed job queue (PostgreSQL or SQLite)  ──►  worker processes (spawned, killable)
                                                                  │
                                    yt-dlp (YouTube) ─► FFmpeg (probe / normalise / playback copy)
                                                                  │
                                         songscope_engine (librosa · NumPy · SciPy · pyloudnorm · Demucs)
                                                                  │
                                                        analysis JSON  ─►  results API / exports / LLM explanations
```

## Project structure

```
songscope/
├── audio-engine/            Python DSP package `songscope_engine` (no web dependencies)
│   ├── songscope_engine/
│   │   ├── decode.py        probe (ffprobe or ffmpeg), tags, normalisation, HPSS, waveform peaks
│   │   ├── tempo.py         5 tempo estimators, octave-aware selection, beats, stability, tempo map
│   │   ├── meter.py         accent-pattern meter scoring, simple/compound subdivision, downbeat HMM
│   │   ├── features.py      tuning-aware CQT chroma (full / bass / treble)
│   │   ├── chords.py        beat-synced templates + bass evidence, HMM Viterbi + forward-backward
│   │   ├── key.py           4 key profiles + chord fit + bass + cadence fusion, modulations
│   │   ├── progression.py   recurring progressions, Roman numerals, per-section chords
│   │   ├── structure.py     self-similarity novelty, repetition groups, inferred section labels
│   │   ├── pitch.py         predominant-melody salience tracker (mix) / pYIN (stems)
│   │   ├── loudness.py      BS.1770-4 LUFS, momentary/short-term, LRA, true peak, DR
│   │   ├── spectral.py      spectral descriptors, LTAS, band balance, playback-synced band spectrogram
│   │   ├── drums.py         estimated kick/snare/hi-hat pattern on a 16th grid
│   │   ├── separation.py    optional Demucs separation + per-stem analysis
│   │   ├── summary.py       template summary built only from detected values
│   │   ├── pipeline.py      staged orchestration, real progress, per-stage fault isolation
│   │   └── synth.py         synthetic songs with exact ground truth (tests / demos)
│   └── tests/               accuracy tests against ground truth
├── backend/                 FastAPI app `songscope_api`
│   ├── songscope_api/       routes, config, models, dispatcher, worker process, YouTube, exports, LLM
│   └── tests/               API, validation, security and end-to-end job tests
├── frontend/                Next.js 16 · React 19 · TypeScript · Tailwind CSS 4
│   ├── app/                 landing page, /analysis/[id] dashboard
│   ├── components/          AudioUploader, YouTubeInput, AnalysisProgress, AudioPlayer, Waveform,
│   │                        OverviewCards, ChordTimeline, RhythmSection (BeatGrid, DrumPattern),
│   │                        SongStructure, HarmonySection, charts/ (Pitch, Spectrum, Loudness,
│   │                        Chromagram, TempoCurve), ConfidenceBadge & AnalysisSection (ui.tsx) …
│   ├── hooks/               usePlayer (shared audio + time/view stores), useAnalysis (polling)
│   ├── lib/                 API client, formatting
│   └── types/               result types (mirrors shared schema)
├── shared/analysis-result.schema.json   JSON Schema of the result (validated in tests)
├── docker/                  backend & frontend Dockerfiles
├── scripts/generate_samples.py          renders synthetic test songs + ground truth
├── docker-compose.yml       postgres + api + worker + frontend
└── .env.example
```

## Running locally

Requirements: **Python 3.11+** (developed on 3.14), **Node.js 20+**. FFmpeg is optional — if it is not on `PATH`,
the bundled `imageio-ffmpeg` binary is used automatically.

```bash
# 1. Python environment (from the repo root)
python -m venv .venv
.venv/Scripts/activate            # Windows (bash);  source .venv/bin/activate on macOS/Linux
pip install -e audio-engine -e backend
pip install pytest jsonschema     # tests

# optional: source separation (~1 GB; CPU build of PyTorch)
pip install --extra-index-url https://download.pytorch.org/whl/cpu torch demucs

# 2. API + embedded worker  (http://localhost:8000, docs at /docs)
cp .env.example .env
uvicorn songscope_api.main:app --port 8000

# 3. Frontend  (http://localhost:3000)
cd frontend && npm install && npm run dev
```

The first analysis after start-up is slower (~20 s extra) while Numba compiles librosa kernels.

### Docker

```bash
cp .env.example .env
docker compose up --build                      # PostgreSQL, API, separate worker, frontend
INSTALL_STEMS=true docker compose up --build   # include PyTorch + Demucs in the images
```

The API runs with `SONGSCOPE_EMBEDDED_WORKER=false`; analysis happens in the `worker` service
(`python -m songscope_api.worker`). Scale workers with `docker compose up --scale worker=3`.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `SONGSCOPE_DATABASE_URL` | `sqlite:///./data/songscope.db` | SQLAlchemy URL (`postgresql+psycopg://…` in Docker) |
| `SONGSCOPE_DATA_DIR` | `./data` | temporary per-job audio |
| `SONGSCOPE_MAX_UPLOAD_MB` | `200` | upload size limit |
| `SONGSCOPE_MAX_DURATION_SECONDS` | `900` | audio / video duration limit |
| `SONGSCOPE_JOB_TIMEOUT_SECONDS` | `1800` | hard kill for stuck jobs |
| `SONGSCOPE_MAX_CONCURRENT_JOBS` | `2` | worker processes per dispatcher |
| `SONGSCOPE_RATE_LIMIT_PER_MINUTE` | `20` | per-IP limit on analysis endpoints |
| `SONGSCOPE_AUDIO_RETENTION_MINUTES` | `60` | audio is deleted after this; results are kept |
| `SONGSCOPE_KEEP_SOURCE_AUDIO` | `false` | keep originals when a playback copy was transcoded |
| `SONGSCOPE_CACHE_RESULTS` | `true` | reuse results for identical content hash / YouTube video ID |
| `SONGSCOPE_CORS_ORIGINS` | `http://localhost:3000,…` | allowed frontend origins |
| `SONGSCOPE_EMBEDDED_WORKER` | `true` | run jobs from the API process (false → standalone worker) |
| `SONGSCOPE_ENABLE_YOUTUBE` | `true` | enable YouTube input |
| `SONGSCOPE_YOUTUBE_COOKIES_FILE` | – | cookies file if YouTube demands a bot check |
| `SONGSCOPE_ENABLE_STEMS` / `SONGSCOPE_STEMS_MODEL` | `true` / `htdemucs` | source separation |
| `ANTHROPIC_API_KEY` | – | enables optional AI explanations |
| `SONGSCOPE_LLM_MODEL` | `claude-opus-5` | model for explanations |
| `FFMPEG_PATH`, `FFPROBE_PATH`, `FFMPEG_THREADS` | auto / `2` | FFmpeg binaries & threads |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | where the browser reaches the API |

## API

| Method & path | Description |
|---|---|
| `POST /api/analyze/upload` | multipart `file` (+ `force`) → `202 {analysis_id, cached}` |
| `POST /api/analyze/youtube` | `{url, force}` → `202 {analysis_id, cached}` |
| `GET /api/analyze/{id}` | status + metadata + results + audio/stems info |
| `GET /api/analyze/{id}/status` | lightweight progress (stage, per-stage states, %) |
| `GET /api/analyze/{id}/results` | result JSON (409 until complete) |
| `POST /api/analyze/{id}/cancel` · `DELETE /api/analyze/{id}` | cancel (kills the worker process) · delete record + audio |
| `GET /api/analyze/{id}/audio` | playback audio (HTTP range requests) |
| `POST /api/analyze/{id}/stems` · `GET …/stems/{stem}/audio` | optional Demucs separation |
| `GET /api/analyze/{id}/export?format=json\|csv\|txt\|pdf` | downloads |
| `POST /api/analyze/{id}/explain` | `{audience}` → LLM explanation of the computed results |
| `GET /api/analyses` · `GET /api/health` | recent analyses · capabilities & limits |

Errors have the shape `{"error": {"code": "...", "message": "..."}}` (e.g. `invalid_url`, `video_private`,
`age_restricted`, `region_restricted`, `bot_check`, `file_too_large`, `invalid_audio`, `duration_limit`, `decode_failed`).

## Tests

```bash
cd audio-engine && python -m pytest     # 23 tests: DSP accuracy vs. ground truth, schema
cd backend && python -m pytest          # 35 tests: API, validation, security, end-to-end jobs
cd frontend && npx tsc --noEmit && npx eslint . && npx next build
python scripts/generate_samples.py      # writes samples/*.wav + *.truth.json
```

Measured on the synthetic ground-truth songs (drums, bass, chord pads, vocal-like lead):

| | Pop, E major, 124 BPM, 4/4 | Waltz, G major, 150 BPM, 3/4 | A minor, 96 BPM, 4/4 |
|---|---|---|---|
| Tempo | 124.0 (conf. 0.90) | 149.9 (0.93) | 96.0 (0.90) |
| Meter | 4/4 (0.88) | 3/4 (0.87) | 4/4 (0.86) |
| Key | E major | G major | A minor |
| Chord accuracy (root + maj/min, 100 ms frames) | 98.6 % | 98.2 % | 96.7 % |
| Structure | all 8 boundaries within 0.1 s; Intro/Verse/Chorus/Bridge/Final Chorus/Outro | – | – |
| Drum pattern | kick 1, 3 · snare 2, 4 | kick 1 · snare 2, 3 | kick 1, 3 · snare 2, 4 |

Synthetic audio is far cleaner than commercial mixes — treat these as regression tests, not real-world accuracy.

### Adding your own test audio

Put files you have the rights to use in `samples/` (ignored by git) and upload them through the UI, or
`curl -F file=@samples/track.mp3 localhost:8000/api/analyze/upload`. No copyrighted audio is bundled.

## Security & privacy

* Extension allow-list **and** magic-byte sniffing (extension must match content), then FFmpeg probing; size is checked
  from `Content-Length` before the body is read and again while streaming.
* Filenames are sanitised and never used on disk (files are stored as `source.<ext>` in a per-job directory).
* YouTube: only a canonical URL rebuilt from a validated 11-character video ID reaches yt-dlp; playlists rejected.
* Subprocesses use argument lists (`shell=False`), closed stdin, timeouts, below-normal priority, and on POSIX
  `RLIMIT_AS`/`RLIMIT_CPU` limits. Jobs run in separate processes with a wall-clock timeout.
* Audio is temporary (deleted after the retention window, on failure/cancel and on delete); results persist.
* Per-IP rate limiting, CORS allow-list, `nosniff`/`no-referrer` headers, path-traversal-safe file serving.

## Known limitations

* **Meter** is hard on real recordings: odd meters and 2/4-vs-4/4 or 3/4-vs-6/8 distinctions are often ambiguous; the
  UI reports "could not be determined reliably" below the confidence threshold.
* **Chords** use a conservative vocabulary (maj, min, 7, maj7, m7, sus2/4, dim, aug) without inversions/slash chords;
  dense arrangements, distortion and detuned instruments reduce accuracy.
* **Section names** are heuristics from repetition and energy — no lyric/vocal awareness. Songs without clear
  repetition (film score, ambient, DJ mixes) fall back to plain "Section A/B/…".
* **Melody pitch on a full mix** follows the most salient harmonic line and can lock onto accompaniment; separate
  stems (vocals → pYIN) for reliable melody.
* **Drum pattern** is inferred from band-limited onsets; hi-hat/snare leakage and fills blur it (drum stem helps).
* Key profiles assume Western tonal music; modal, atonal and microtonal music will score low confidence.
* Stem separation on CPU takes roughly 0.5–2× the track duration. YouTube may require cookies (bot check) and
  downloading is subject to YouTube's terms and copyright.
* SQLite is fine for a single machine; use PostgreSQL for multiple workers/hosts (they must share `DATA_DIR`).
* Essentia is not used (no Windows wheels); its key/HPCP ideas are implemented with librosa CQT chroma instead.

## Recommended next improvements

1. Evaluate on public annotated datasets (GiantSteps tempo/key, Isophonics/Billboard chords, SALAMI structure,
   Ballroom/GTZAN rhythm) and calibrate confidence scores on them.
2. Learned models where they clearly win: madmom/Beat This! downbeat tracking, CREMA or BTC chord recognition,
   neural key estimation — kept behind the same confidence interface.
3. Use the vocal stem automatically for melody, vocal-activity detection (true "Instrumental" labels) and lyric
   alignment with Whisper to name sections from repeated lyrics.
4. Beat-synchronous chord inversions/slash chords and capo/transposition helpers for guitarists.
5. Redis/RQ or Celery queue with object storage for multi-host deployments; WebSocket/SSE progress instead of polling.
6. User accounts, saved libraries, comparison between tracks, MIDI/MusicXML export of chords and melody.
