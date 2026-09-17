from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SONGSCOPE_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/songscope.db"
    data_dir: str = "./data"

    # limits
    max_upload_mb: int = 200
    max_duration_seconds: int = 900
    job_timeout_seconds: int = 1800
    max_concurrent_jobs: int = 2
    rate_limit_per_minute: int = 20

    # retention: processed audio is temporary; analysis results are kept
    audio_retention_minutes: int = 60
    keep_source_audio: bool = False
    cache_results: bool = True

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    embedded_worker: bool = True

    enable_youtube: bool = True
    youtube_cookies_file: str | None = None

    enable_stems: bool = True
    stems_model: str = "htdemucs"

    anthropic_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("SONGSCOPE_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
    )
    llm_model: str = "claude-opus-5"

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def jobs_path(self) -> Path:
        p = self.data_path / "jobs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    if s.database_url.startswith("sqlite:///./"):
        # resolve relative sqlite paths against the data dir's parent so all processes agree
        rel = s.database_url.removeprefix("sqlite:///./")
        s.database_url = "sqlite:///" + str((Path(os.getcwd()) / rel).resolve()).replace("\\", "/")
        Path(s.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return s
