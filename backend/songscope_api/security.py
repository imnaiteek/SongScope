"""Input validation: filenames, extensions, magic bytes, rate limiting."""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from collections import defaultdict, deque

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".aif", ".aiff"}
MIME_BY_KIND = {
    "wav": "audio/wav", "aiff": "audio/aiff", "flac": "audio/flac", "ogg": "audio/ogg", "mp3": "audio/mpeg",
    "mp4": "audio/mp4", "aac": "audio/aac",
}
# which sniffed container kinds are acceptable for each extension
EXT_KINDS = {
    ".mp3": {"mp3"}, ".wav": {"wav"}, ".flac": {"flac"}, ".m4a": {"mp4"}, ".aac": {"aac", "mp4"},
    ".ogg": {"ogg"}, ".oga": {"ogg"}, ".opus": {"ogg"}, ".aif": {"aiff"}, ".aiff": {"aiff"},
}


def sanitize_filename(name: str | None, max_len: int = 120) -> str:
    name = (name or "audio").replace("\\", "/").split("/")[-1]
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[^\w.\- ()\[\]]+", "_", name, flags=re.UNICODE).strip(" ._")
    if not name:
        name = "audio"
    stem, dot, ext = name.rpartition(".")
    if dot and len(ext) <= 5:
        return stem[: max_len - len(ext) - 1] + "." + ext.lower()
    return name[:max_len]


def extension_of(name: str) -> str:
    idx = name.rfind(".")
    return name[idx:].lower() if idx >= 0 else ""


def sniff_audio(head: bytes) -> str | None:
    """Identify the container from magic bytes. Returns a kind or None."""
    if len(head) < 12:
        return None
    if head[:4] in (b"RIFF", b"RF64") and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:4] == b"OggS":
        return "ogg"
    if head[4:8] == b"ftyp":
        return "mp4"
    if head[:3] == b"ID3":
        # ID3v2 header: skip the tag and look at what follows
        size = (head[6] << 21) | (head[7] << 14) | (head[8] << 7) | head[9]
        rest = head[10 + size :]
        if rest[:4] == b"fLaC":
            return "flac"
        if len(rest) >= 2 and rest[0] == 0xFF and (rest[1] & 0xF6) == 0xF0:
            return "aac"
        return "mp3"
    if head[0] == 0xFF and (head[1] & 0xF6) == 0xF0:
        return "aac"  # ADTS
    if head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        return "mp3"  # MPEG audio frame sync
    return None


class RateLimiter:
    """Sliding-window limiter keyed by client address (in-process)."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if self.per_minute <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True
