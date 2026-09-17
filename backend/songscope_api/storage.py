"""Temporary per-analysis working directories and retention cleanup."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import get_settings

log = logging.getLogger("songscope.storage")


def job_dir(analysis_id: str, create: bool = True) -> Path:
    if not analysis_id.isalnum():
        raise ValueError("invalid analysis id")
    p = get_settings().jobs_path / analysis_id
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def safe_child(analysis_id: str, relative: str) -> Path | None:
    """Resolve a stored relative path inside the job directory, refusing traversal."""
    base = job_dir(analysis_id, create=False).resolve()
    target = (base / relative).resolve()
    if base not in target.parents and target != base:
        return None
    return target if target.is_file() else None


def remove_job_dir(analysis_id: str) -> None:
    p = job_dir(analysis_id, create=False)
    shutil.rmtree(p, ignore_errors=True)


def retention_deadline() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=get_settings().audio_retention_minutes)


def purge_expired_audio() -> int:
    """Delete audio whose retention window has passed. Results in the database are kept."""
    from .db import session_scope
    from .models import Analysis

    now = datetime.now(timezone.utc)
    removed = 0
    with session_scope() as s:
        expired = (
            s.query(Analysis)
            .filter(Analysis.audio_expires_at.isnot(None), Analysis.audio_expires_at < now)
            .filter(Analysis.status.notin_(["queued", "processing"]))
            .filter(Analysis.stems_status.notin_(["queued", "processing"]))
            .all()
        )
        for a in expired:
            remove_job_dir(a.id)
            a.audio_file = None
            a.audio_expires_at = None
            if a.stems_json:
                a.stems_json = {**a.stems_json, "audio_available": False}
            removed += 1
        # failed / cancelled jobs never keep audio
        for a in s.query(Analysis).filter(Analysis.status.in_(["failed", "cancelled"])).all():
            if job_dir(a.id, create=False).exists():
                remove_job_dir(a.id)
    if removed:
        log.info("purged audio for %d analyses", removed)
    return removed
