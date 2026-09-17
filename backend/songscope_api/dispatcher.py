"""Database-backed job queue dispatcher.

Queued jobs are claimed atomically (UPDATE ... WHERE status='queued'), so several dispatchers
(the API's embedded one and/or standalone `python -m songscope_api.worker` processes) can share
one database safely. Each job runs in a spawned child process that can be terminated for
cancellation or timeout.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import update

from .config import get_settings
from .db import session_scope
from .models import Analysis, Job
from .storage import purge_expired_audio, remove_job_dir

log = logging.getLogger("songscope.dispatcher")


@dataclass
class _Running:
    process: mp.Process
    started: float
    analysis_id: str
    kind: str


class Dispatcher(threading.Thread):
    def __init__(self, poll_interval: float = 0.5):
        super().__init__(daemon=True, name="songscope-dispatcher")
        self.settings = get_settings()
        self.poll_interval = poll_interval
        self.worker_name = f"{socket.gethostname()}:{os.getpid()}"
        self.running: dict[str, _Running] = {}
        self._stop = threading.Event()
        self._ctx = mp.get_context("spawn")
        self._last_janitor = 0.0

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for job_id, r in list(self.running.items()):
            if r.process.is_alive():
                r.process.terminate()
            self._mark(job_id, r, "failed", "Server shut down during processing.", "server_shutdown")
        self.join(timeout)

    def run(self) -> None:
        self._recover_orphans()
        while not self._stop.is_set():
            try:
                self._reap()
                self._claim()
                if time.monotonic() - self._last_janitor > 60:
                    self._last_janitor = time.monotonic()
                    purge_expired_audio()
            except Exception:  # pragma: no cover - keep the loop alive
                log.exception("dispatcher iteration failed")
            self._stop.wait(self.poll_interval)

    # ------------------------------------------------------------------------------------
    def _recover_orphans(self) -> None:
        """Jobs left 'running' by a crashed server can never finish; fail them cleanly."""
        with session_scope() as s:
            for job in s.query(Job).filter(Job.status == "running").all():
                if job.worker and job.worker.split(":")[0] == socket.gethostname():
                    job.status = "failed"
                    job.error = "Server restarted during processing."
                    job.finished_at = datetime.now(timezone.utc)
                    a = s.get(Analysis, job.analysis_id)
                    if a is not None:
                        if job.kind == "analysis" and a.status in ("queued", "processing"):
                            a.status, a.error_code = "failed", "server_restart"
                            a.error_message = "The server restarted during analysis. Please try again."
                        elif job.kind == "stems":
                            a.stems_status, a.stems_message = "failed", "The server restarted during separation."

    def _claim(self) -> None:
        while len(self.running) < self.settings.max_concurrent_jobs and not self._stop.is_set():
            with session_scope() as s:
                job = s.query(Job).filter(Job.status == "queued").order_by(Job.created_at).first()
                if job is None:
                    return
                claimed = s.execute(
                    update(Job)
                    .where(Job.id == job.id, Job.status == "queued")
                    .values(status="running", worker=self.worker_name, started_at=datetime.now(timezone.utc),
                            attempts=Job.attempts + 1)
                ).rowcount
                job_id, analysis_id, kind = job.id, job.analysis_id, job.kind
            if claimed != 1:
                continue
            from .worker_process import run_job

            proc = self._ctx.Process(target=run_job, args=(job_id,), name=f"songscope-job-{job_id[:8]}", daemon=True)
            proc.start()
            self.running[job_id] = _Running(proc, time.monotonic(), analysis_id, kind)
            log.info("started %s job %s (analysis %s) pid=%s", kind, job_id, analysis_id, proc.pid)

    def _reap(self) -> None:
        for job_id, r in list(self.running.items()):
            with session_scope() as s:
                job = s.get(Job, job_id)
                cancel = job is None or job.cancel_requested
                status = job.status if job else None
            if not r.process.is_alive():
                r.process.join(1)
                if status == "running":  # the child died without recording an outcome
                    self._mark(job_id, r, "failed", f"Worker process exited unexpectedly (code {r.process.exitcode}).",
                               "worker_crashed")
                del self.running[job_id]
            elif cancel:
                self._kill(r)
                self._mark(job_id, r, "cancelled", "Analysis was cancelled.", "cancelled")
                del self.running[job_id]
            elif time.monotonic() - r.started > self.settings.job_timeout_seconds:
                self._kill(r)
                self._mark(job_id, r, "failed",
                           f"Processing exceeded the {self.settings.job_timeout_seconds // 60} minute time limit.",
                           "timeout")
                del self.running[job_id]

    @staticmethod
    def _kill(r: _Running) -> None:
        r.process.terminate()
        r.process.join(5)
        if r.process.is_alive():
            r.process.kill()
            r.process.join(2)

    def _mark(self, job_id: str, r: _Running, status: str, message: str, code: str) -> None:
        with session_scope() as s:
            job = s.get(Job, job_id)
            if job is not None:
                job.status, job.error, job.finished_at = status, message, datetime.now(timezone.utc)
            a = s.get(Analysis, r.analysis_id)
            if a is None:
                return
            if r.kind == "analysis":
                if a.status not in ("completed",):
                    a.status = status
                    a.error_code = None if status == "cancelled" else code
                    a.error_message = None if status == "cancelled" else message
                    a.message = message if status == "cancelled" else None
            else:
                a.stems_status, a.stems_message = status, message
        if r.kind == "analysis" and status in ("failed", "cancelled"):
            remove_job_dir(r.analysis_id)
