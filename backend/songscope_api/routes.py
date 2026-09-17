from __future__ import annotations

import hashlib
import os
import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from songscope_engine import ENGINE_VERSION
from songscope_engine.errors import EngineError

from . import exports, llm, security, storage, youtube
from .config import get_settings
from .db import get_session
from .models import Analysis, Job, new_id
from .pipeline_helpers import stage_list

router = APIRouter(prefix="/api")
_limiter = None


def rate_limit(request: Request) -> None:
    global _limiter
    if _limiter is None:
        _limiter = security.RateLimiter(get_settings().rate_limit_per_minute)
    client = request.client.host if request.client else "unknown"
    if not _limiter.allow(client):
        raise HTTPException(429, detail={"code": "rate_limited", "message": "Too many analysis requests. Please wait a minute."})


def error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


def _get(session: Session, analysis_id: str) -> Analysis:
    if not analysis_id.isalnum() or len(analysis_id) > 32:
        raise error(404, "not_found", "Analysis not found.")
    a = session.get(Analysis, analysis_id)
    if a is None:
        raise error(404, "not_found", "Analysis not found.")
    return a


def _audio_available(a: Analysis) -> bool:
    if not a.audio_file or not a.audio_expires_at:
        return False
    exp = a.audio_expires_at if a.audio_expires_at.tzinfo else a.audio_expires_at.replace(tzinfo=timezone.utc)
    return exp > datetime.now(timezone.utc) and storage.safe_child(a.id, a.audio_file) is not None


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def _status_payload(a: Analysis) -> dict:
    return {
        "id": a.id,
        "status": a.status,
        "source_type": a.source_type,
        "source": a.source_ref,
        "stage": a.stage,
        "stage_label": a.stage_label,
        "stage_progress": a.stage_progress,
        "progress": a.progress,
        "message": a.message,
        "error": {"code": a.error_code, "message": a.error_message} if a.status == "failed" else None,
        "stages": stage_list(a.stage, a.status),
        "title": (a.metadata_json or {}).get("title") or a.source_ref,
        "created_at": _iso(a.created_at),
        "completed_at": _iso(a.completed_at),
    }


def _stems_payload(a: Analysis) -> dict:
    return {"status": a.stems_status, "progress": a.stems_progress, "message": a.stems_message, "results": a.stems_json}


def _find_cached(session: Session, source_hash: str) -> Analysis | None:
    if not get_settings().cache_results:
        return None
    return (
        session.query(Analysis)
        .filter(Analysis.source_hash == source_hash, Analysis.engine_version == ENGINE_VERSION,
                Analysis.status.in_(["completed", "queued", "processing"]))
        .order_by(Analysis.created_at.desc())
        .first()
    )


def _enqueue(session: Session, a: Analysis, kind: str = "analysis") -> None:
    session.add(Job(analysis_id=a.id, kind=kind))


# --------------------------------------------------------------------------------------------
@router.get("/health")
def health():
    from songscope_engine import ffmpeg
    from songscope_engine.separation import is_available

    s = get_settings()
    stems_ok, stems_reason = is_available() if s.enable_stems else (False, "Disabled by configuration.")
    return {
        "status": "ok",
        "engine_version": ENGINE_VERSION,
        "capabilities": {
            "ffmpeg": ffmpeg.ffmpeg_path() is not None,
            "ffprobe": ffmpeg.ffprobe_path() is not None,
            "youtube": s.enable_youtube,
            "stems": stems_ok,
            "stems_reason": stems_reason,
            "llm": bool(s.anthropic_api_key),
            "llm_audiences": list(llm.AUDIENCES),
        },
        "limits": {
            "max_upload_mb": s.max_upload_mb,
            "max_duration_seconds": s.max_duration_seconds,
            "audio_retention_minutes": s.audio_retention_minutes,
            "formats": sorted(e.lstrip(".") for e in security.ALLOWED_EXTENSIONS),
        },
    }


@router.post("/analyze/upload", status_code=202, dependencies=[Depends(rate_limit)])
async def analyze_upload(file: UploadFile = File(...), force: bool = Form(False), session: Session = Depends(get_session)):
    s = get_settings()
    name = security.sanitize_filename(file.filename)
    ext = security.extension_of(name)
    if ext not in security.ALLOWED_EXTENSIONS:
        raise error(415, "unsupported_format",
                    f"Unsupported file type '{ext or 'unknown'}'. Supported: MP3, WAV, FLAC, M4A, AAC, OGG, AIFF.")

    analysis = Analysis(id=new_id(), source_type="upload", source_ref=name, source_hash="", engine_version=ENGINE_VERSION)
    work = storage.job_dir(analysis.id)
    stored_name = f"source{ext}"
    dest = work / stored_name
    sha = hashlib.sha256()
    size = 0
    head = b""
    try:
        with open(dest, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > s.max_upload_bytes:
                    raise error(413, "file_too_large", f"File exceeds the {s.max_upload_mb} MB limit.")
                if len(head) < 4096:
                    head += chunk[: 4096 - len(head)]
                sha.update(chunk)
                out.write(chunk)
        if size == 0:
            raise error(400, "empty_file", "The uploaded file is empty.")
        kind = security.sniff_audio(head)
        if kind is None or kind not in security.EXT_KINDS[ext]:
            raise error(415, "invalid_audio",
                        "The file content does not match a supported audio format." if kind is None
                        else f"The file extension '{ext}' does not match its content ({kind}).")
        from songscope_engine.decode import probe

        try:
            info = await run_in_threadpool(probe, str(dest))
        except EngineError as exc:
            raise error(415, exc.code, exc.message)
        if not info.duration or info.duration < 1:
            raise error(422, "too_short", "Audio is too short or its duration could not be read.")
        if info.duration > s.max_duration_seconds + 1:
            raise error(413, "duration_limit",
                        f"Audio is {info.duration / 60:.1f} min long; the limit is {s.max_duration_seconds // 60} min.")
    except HTTPException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise

    source_hash = sha.hexdigest()
    cached = None if force else _find_cached(session, source_hash)
    if cached is not None:
        if cached.status == "completed" and not _audio_available(cached) and ext.lstrip(".") in ("mp3", "m4a", "aac", "ogg", "wav", "flac", "opus", "oga"):
            # re-attach the freshly uploaded audio for playback instead of re-analysing
            target = storage.job_dir(cached.id) / stored_name
            shutil.move(str(dest), target)
            cached.audio_file = stored_name
            cached.audio_expires_at = storage.retention_deadline()
            session.commit()
        shutil.rmtree(work, ignore_errors=True)
        return {"analysis_id": cached.id, "status": cached.status, "cached": True}

    analysis.source_hash = source_hash
    analysis.metadata_json = {"filename": name, "stored_name": stored_name, "format": ext.lstrip(".").upper(),
                              "file_size": size, "mime": security.MIME_BY_KIND.get(kind)}
    session.add(analysis)
    session.flush()
    _enqueue(session, analysis)
    session.commit()
    return {"analysis_id": analysis.id, "status": analysis.status, "cached": False}


class YouTubeRequest(BaseModel):
    url: str = Field(..., max_length=2048)
    force: bool = False


@router.post("/analyze/youtube", status_code=202, dependencies=[Depends(rate_limit)])
def analyze_youtube(req: YouTubeRequest, session: Session = Depends(get_session)):
    s = get_settings()
    if not s.enable_youtube:
        raise error(403, "youtube_disabled", "YouTube analysis is disabled on this server.")
    try:
        vid = youtube.parse_video_id(req.url)
    except EngineError as exc:
        raise error(422, exc.code, exc.message)
    source_hash = hashlib.sha256(f"youtube:{vid}".encode()).hexdigest()
    cached = None if req.force else _find_cached(session, source_hash)
    if cached is not None:
        return {"analysis_id": cached.id, "status": cached.status, "cached": True}
    url = youtube.canonical_url(vid)
    a = Analysis(source_type="youtube", source_ref=url, source_hash=source_hash, engine_version=ENGINE_VERSION,
                 metadata_json={"youtube": {"video_id": vid, "url": url}, "title": None})
    session.add(a)
    session.flush()
    _enqueue(session, a)
    session.commit()
    return {"analysis_id": a.id, "status": a.status, "cached": False}


@router.get("/analyses")
def list_analyses(limit: int = Query(12, ge=1, le=50), session: Session = Depends(get_session)):
    rows = session.query(Analysis).order_by(Analysis.created_at.desc()).limit(limit).all()
    out = []
    for a in rows:
        ov = (a.results_json or {}).get("overview") or {}
        out.append({**_status_payload(a), "overview": ov, "artist": (a.metadata_json or {}).get("artist")})
    return {"items": out}


@router.get("/analyze/{analysis_id}")
def get_analysis(analysis_id: str, session: Session = Depends(get_session)):
    a = _get(session, analysis_id)
    return {
        **_status_payload(a),
        "metadata": a.metadata_json,
        "results": a.results_json if a.status == "completed" else None,
        "audio": {"available": _audio_available(a),
                  "expires_at": _iso(a.audio_expires_at),
                  "url": f"/api/analyze/{a.id}/audio" if _audio_available(a) else None},
        "stems": _stems_payload(a),
        "explanations": a.explanations_json or {},
    }


@router.get("/analyze/{analysis_id}/status")
def get_status(analysis_id: str, session: Session = Depends(get_session)):
    a = _get(session, analysis_id)
    return {**_status_payload(a), "stems": {k: v for k, v in _stems_payload(a).items() if k != "results"}}


@router.get("/analyze/{analysis_id}/results")
def get_results(analysis_id: str, session: Session = Depends(get_session)):
    a = _get(session, analysis_id)
    if a.status != "completed":
        raise error(409, "not_ready", f"Analysis is {a.status}.")
    return a.results_json


@router.post("/analyze/{analysis_id}/cancel")
def cancel(analysis_id: str, session: Session = Depends(get_session)):
    a = _get(session, analysis_id)
    jobs = session.query(Job).filter(Job.analysis_id == a.id, Job.status.in_(["queued", "running"])).all()
    for j in jobs:
        if j.status == "queued":
            j.status = "cancelled"
            if j.kind == "analysis":
                a.status, a.message = "cancelled", "Analysis was cancelled."
            else:
                a.stems_status = "cancelled"
        else:
            j.cancel_requested = True
    session.commit()
    return {"id": a.id, "cancelled": len(jobs)}


@router.delete("/analyze/{analysis_id}", status_code=204)
def delete_analysis(analysis_id: str, session: Session = Depends(get_session)):
    a = _get(session, analysis_id)
    for j in session.query(Job).filter(Job.analysis_id == a.id).all():
        if j.status == "running":
            j.cancel_requested = True
    session.commit()
    # the dispatcher terminates running processes once their job rows disappear
    session.query(Job).filter(Job.analysis_id == a.id, Job.status != "running").delete()
    session.delete(a)
    session.commit()
    storage.remove_job_dir(analysis_id)
    return Response(status_code=204)


@router.get("/analyze/{analysis_id}/audio")
def get_audio(analysis_id: str, session: Session = Depends(get_session)):
    a = _get(session, analysis_id)
    if not _audio_available(a):
        raise error(410, "audio_expired", "Audio for this analysis is no longer stored. Re-upload to listen.")
    path = storage.safe_child(a.id, a.audio_file)
    media = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg", ".oga": "audio/ogg",
             ".opus": "audio/ogg", ".webm": "audio/webm", ".wav": "audio/wav", ".flac": "audio/flac"}
    return FileResponse(path, media_type=media.get(path.suffix.lower(), "application/octet-stream"),
                        headers={"Cache-Control": "private, max-age=600"})


@router.post("/analyze/{analysis_id}/stems", status_code=202, dependencies=[Depends(rate_limit)])
def start_stems(analysis_id: str, session: Session = Depends(get_session)):
    from songscope_engine.separation import is_available

    s = get_settings()
    a = _get(session, analysis_id)
    ok, reason = is_available() if s.enable_stems else (False, "Stem separation is disabled on this server.")
    if not ok:
        raise error(501, "stems_unavailable", reason)
    if a.status != "completed":
        raise error(409, "not_ready", "Wait for the main analysis to finish first.")
    if not _audio_available(a):
        raise error(410, "audio_expired", "The audio for this analysis has expired. Re-analyse to separate stems.")
    if a.stems_status in ("queued", "processing"):
        return {"status": a.stems_status}
    a.stems_status, a.stems_progress, a.stems_message, a.stems_json = "queued", 0.0, "Waiting for a worker", None
    _enqueue(session, a, "stems")
    session.commit()
    return {"status": "queued"}


@router.get("/analyze/{analysis_id}/stems/{stem}/audio")
def stem_audio(analysis_id: str, stem: str, session: Session = Depends(get_session)):
    a = _get(session, analysis_id)
    info = ((a.stems_json or {}).get("stems") or {}).get(stem)
    if not info or not _audio_available(a):
        raise error(404, "not_found", "Stem audio not available.")
    path = storage.safe_child(a.id, info["audio_file"])
    if path is None:
        raise error(410, "audio_expired", "Stem audio has expired.")
    return FileResponse(path, media_type="audio/mp4" if path.suffix == ".m4a" else "audio/wav")


@router.get("/analyze/{analysis_id}/export")
def export(analysis_id: str, format: str = Query("json", pattern="^(json|csv|txt|pdf)$"),
           session: Session = Depends(get_session)):
    a = _get(session, analysis_id)
    if a.status != "completed":
        raise error(409, "not_ready", "Analysis is not complete.")
    r = a.results_json
    name = f"songscope-{exports.slug((r.get('metadata') or {}).get('title'))}"
    if format == "json":
        body, media = exports.to_json(r), "application/json"
    elif format == "csv":
        body, media = exports.to_csv(r), "text/csv; charset=utf-8"
    elif format == "txt":
        body, media = exports.to_text(r).encode("utf-8"), "text/plain; charset=utf-8"
    else:
        body, media = exports.to_pdf(r), "application/pdf"
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}.{format}"'})


class ExplainRequest(BaseModel):
    audience: str = Field(..., max_length=32)
    refresh: bool = False


@router.post("/analyze/{analysis_id}/explain", dependencies=[Depends(rate_limit)])
async def explain(analysis_id: str, req: ExplainRequest, session: Session = Depends(get_session)):
    s = get_settings()
    a = _get(session, analysis_id)
    if a.status != "completed":
        raise error(409, "not_ready", "Analysis is not complete.")
    if req.audience not in llm.AUDIENCES:
        raise error(422, "invalid_audience", f"Audience must be one of: {', '.join(llm.AUDIENCES)}.")
    cache = dict(a.explanations_json or {})
    if req.audience in cache and not req.refresh:
        return {"audience": req.audience, "text": cache[req.audience], "cached": True, "model": s.llm_model}
    try:
        text = await run_in_threadpool(llm.explain, a.results_json, req.audience, s.anthropic_api_key, s.llm_model)
    except llm.LLMUnavailable as exc:
        raise error(503, "llm_unavailable", str(exc))
    cache[req.audience] = text
    a.explanations_json = cache
    session.commit()
    return {"audience": req.audience, "text": text, "cached": False, "model": s.llm_model}
