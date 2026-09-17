"""Safe FFmpeg/FFprobe invocation.

User input is never interpolated into a shell: every call uses an argument list with
shell=False, stdin closed, a hard timeout, and (on POSIX) CPU/memory rlimits.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from functools import lru_cache

DEFAULT_TIMEOUT = 300
FFMPEG_THREADS = os.environ.get("FFMPEG_THREADS", "2")
# Soft resource ceilings for FFmpeg children on POSIX systems.
FFMPEG_MAX_MEMORY_MB = int(os.environ.get("FFMPEG_MAX_MEMORY_MB", "2048"))
FFMPEG_MAX_CPU_SECONDS = int(os.environ.get("FFMPEG_MAX_CPU_SECONDS", "600"))


@lru_cache(maxsize=1)
def ffmpeg_path() -> str | None:
    env = os.environ.get("FFMPEG_PATH")
    if env and os.path.isfile(env):
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


@lru_cache(maxsize=1)
def ffprobe_path() -> str | None:
    env = os.environ.get("FFPROBE_PATH")
    if env and os.path.isfile(env):
        return env
    return shutil.which("ffprobe")


def _preexec():  # pragma: no cover - POSIX only
    import resource

    mem = FFMPEG_MAX_MEMORY_MB * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    resource.setrlimit(resource.RLIMIT_CPU, (FFMPEG_MAX_CPU_SECONDS, FFMPEG_MAX_CPU_SECONDS))
    os.nice(5)


def run(args: list[str], timeout: float = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
    if not all(isinstance(a, str) for a in args):
        raise TypeError("subprocess arguments must be strings")
    kwargs: dict = dict(
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        shell=False,
        check=False,
    )
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.BELOW_NORMAL_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["preexec_fn"] = _preexec
    return subprocess.run(args, **kwargs)
