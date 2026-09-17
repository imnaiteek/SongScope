from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, JSONType, utcnow


def new_id() -> str:
    return uuid.uuid4().hex


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    source_type: Mapped[str] = mapped_column(String(16))  # upload | youtube
    source_ref: Mapped[str] = mapped_column(String(512))  # sanitized filename or canonical URL
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    engine_version: Mapped[str] = mapped_column(String(16))

    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stage_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage_progress: Mapped[float] = mapped_column(Float, default=0.0)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    results_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    explanations_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    audio_file: Mapped[str | None] = mapped_column(String(256), nullable=True)
    audio_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    stems_status: Mapped[str] = mapped_column(String(16), default="none")
    stems_progress: Mapped[float] = mapped_column(Float, default=0.0)
    stems_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    stems_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    analysis_id: Mapped[str] = mapped_column(String(32), ForeignKey("analyses.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # analysis | stems
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued|running|done|failed|cancelled
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    worker: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
