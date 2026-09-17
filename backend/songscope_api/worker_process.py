"""Job execution inside an isolated child process.

Running each job in its own process keeps CPU-heavy DSP off the API process, lets several
analyses run independently, and allows hard cancellation/timeouts by terminating the process.
"""

from __future__ import annotations

import logging
import os
import time
import traceback
from datetime import datetime, timezone

log = logging.getLogger("songscope.worker")


class _Throttle:
    def __init__(self, interval: float):
        self.interval = interval
        self.last = 0.0
        self.last_key = None

    def ready(self, key=None) -> bool:
        now = time.monotonic()
        if key != self.last_key or now - self.last >= self.interval:
            self.last, self.last_key = now, key
            return True
        return False


def run_job(job_id: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from .db import session_scope
    from .models import Analysis, Job

    with session_scope() as s:
        job = s.get(Job, job_id)
        if job is None:
            return
        kind, analysis_id = job.kind, job.analysis_id
    try:
        if kind == "analysis":
            _run_analysis(job_id, analysis_id)
        else:
            _run_stems(job_id, analysis_id)
        _finish_job(job_id, "done")
    except Exception as exc:  # noqa: BLE001 - every failure must be recorded
        from songscope_engine.errors import CancelledError, EngineError

        if isinstance(exc, CancelledError):
            _finish_job(job_id, "cancelled")
            _set_analysis(analysis_id, kind, status="cancelled", message="Analysis was cancelled.")
            return
        if isinstance(exc, EngineError):
            code, message = exc.code, exc.message
        else:
            log.error("job %s crashed: %s", job_id, traceback.format_exc())
            code, message = "internal_error", "An unexpected error occurred while analysing the audio."
        _finish_job(job_id, "failed", f"{code}: {message}")
        _set_analysis(analysis_id, kind, status="failed", error_code=code, error_message=message)
        if kind == "analysis":
            from .storage import remove_job_dir

            remove_job_dir(analysis_id)


def _finish_job(job_id: str, status: str, error: str | None = None) -> None:
    from .db import session_scope
    from .models import Job

    with session_scope() as s:
        job = s.get(Job, job_id)
        if job is not None and job.status == "running":
            job.status = status
            job.error = error
            job.finished_at = datetime.now(timezone.utc)


def _set_analysis(analysis_id: str, kind: str, **fields) -> None:
    from .db import session_scope
    from .models import Analysis

    with session_scope() as s:
        a = s.get(Analysis, analysis_id)
        if a is None:
            return
        if kind == "stems":
            a.stems_status = fields.get("status", a.stems_status)
            a.stems_message = fields.get("error_message") or fields.get("message")
            return
        for k, v in fields.items():
            setattr(a, k, v)


def _cancel_checker(job_id: str):
    from .db import session_scope
    from .models import Job

    throttle = _Throttle(1.0)
    state = {"cancel": False}

    def check() -> bool:
        if throttle.ready():
            with session_scope() as s:
                job = s.get(Job, job_id)
                state["cancel"] = job is None or job.cancel_requested
        return state["cancel"]

    return check


def _run_analysis(job_id: str, analysis_id: str) -> None:
    from songscope_engine.decode import prepare_playback, probe
    from songscope_engine.errors import DurationLimitError
    from songscope_engine.pipeline import STAGES, run_analysis

    from .config import get_settings
    from .db import session_scope
    from .models import Analysis
    from .storage import job_dir, retention_deadline
    from .youtube import download_audio

    settings = get_settings()
    labels = {k: label for k, label, _ in STAGES}
    work = job_dir(analysis_id)
    should_cancel = _cancel_checker(job_id)
    throttle = _Throttle(0.4)

    def report(stage: str, stage_fraction: float, overall: float, message: str | None = None) -> None:
        if not throttle.ready(stage) and stage_fraction not in (0.0, 1.0):
            return
        with session_scope() as s:
            a = s.get(Analysis, analysis_id)
            if a is None:
                return
            a.status = "processing"
            a.stage, a.stage_label = stage, labels.get(stage, stage)
            a.stage_progress = round(stage_fraction, 3)
            a.progress = round(max(a.progress or 0.0, overall), 4)
            a.message = message

    with session_scope() as s:
        a = s.get(Analysis, analysis_id)
        source_type, source_ref, meta = a.source_type, a.source_ref, dict(a.metadata_json or {})

    report("loading", 0.0, 0.0, "Preparing audio")
    if source_type == "youtube":
        from .pipeline_helpers import loading_overall

        def dl_progress(frac: float) -> None:
            report("loading", frac * 0.9, loading_overall(frac * 0.9), "Downloading audio from YouTube")
            if should_cancel():
                from songscope_engine.errors import CancelledError

                raise CancelledError("Analysis was cancelled.")

        source_path, yt = download_audio(
            meta["youtube"]["video_id"], str(work), max_bytes=settings.max_upload_bytes,
            max_duration=settings.max_duration_seconds, cookies_file=settings.youtube_cookies_file,
            progress=dl_progress,
        )
        meta.update({"title": yt.get("title"), "artist": yt.get("artist") or yt.get("channel"),
                     "album": yt.get("album"), "youtube": yt, "upload_date": yt.get("upload_date"),
                     "format": os.path.splitext(source_path)[1].lstrip(".").upper()})
    else:
        source_path = str(work / meta["stored_name"])

    info = probe(source_path)
    if info.duration and info.duration > settings.max_duration_seconds + 1:
        raise DurationLimitError(
            f"Audio is {info.duration / 60:.1f} min long; the limit is {settings.max_duration_seconds / 60:.0f} min."
        )
    meta["source_type"] = source_type
    results = run_analysis(
        source_path, str(work), source_meta=meta, max_duration=settings.max_duration_seconds,
        progress=lambda st, f, o: report(st, f, o), should_cancel=should_cancel, probe_info=info,
    )
    playback = prepare_playback(source_path, str(work / "playback.m4a"))
    if playback != source_path and not settings.keep_source_audio:
        os.remove(source_path)

    with session_scope() as s:
        a = s.get(Analysis, analysis_id)
        if a is None:
            return
        a.results_json = results
        a.metadata_json = results["metadata"]
        a.status = "completed"
        a.stage, a.stage_label, a.stage_progress, a.progress = "report", labels["report"], 1.0, 1.0
        a.message = None
        a.audio_file = os.path.basename(playback)
        a.audio_expires_at = retention_deadline()
        a.completed_at = datetime.now(timezone.utc)


def _run_stems(job_id: str, analysis_id: str) -> None:
    from songscope_engine.separation import analyze_stems

    from .config import get_settings
    from .db import session_scope
    from .models import Analysis
    from .storage import job_dir, retention_deadline, safe_child

    settings = get_settings()
    should_cancel = _cancel_checker(job_id)
    throttle = _Throttle(0.5)
    with session_scope() as s:
        a = s.get(Analysis, analysis_id)
        audio = safe_child(analysis_id, a.audio_file) if a.audio_file else None
        key = (a.results_json or {}).get("key") or {}
        tempo = (a.results_json or {}).get("tempo") or {}
        a.stems_status, a.stems_progress, a.stems_message = "processing", 0.0, "Loading separation model"
    if audio is None:
        from songscope_engine.errors import EngineError

        raise EngineError("The audio for this analysis has expired. Re-analyse the track to separate stems.",
                          "audio_expired")

    def progress(fraction: float, message: str) -> None:
        if should_cancel():
            from songscope_engine.errors import CancelledError

            raise CancelledError("Stem separation was cancelled.")
        if throttle.ready(message) or fraction >= 1.0:
            with session_scope() as s:
                a = s.get(Analysis, analysis_id)
                if a is not None:
                    a.stems_progress, a.stems_message = round(fraction, 3), message

    stems = analyze_stems(str(audio), str(job_dir(analysis_id) / "stems"), model_name=settings.stems_model,
                          progress=progress, key_tonic=key.get("tonic_pc"), key_mode=key.get("mode"),
                          reference_bpm=tempo.get("bpm"))
    with session_scope() as s:
        a = s.get(Analysis, analysis_id)
        if a is not None:
            a.stems_json = stems
            a.stems_status, a.stems_progress, a.stems_message = "completed", 1.0, None
            a.audio_expires_at = retention_deadline()
