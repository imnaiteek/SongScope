"""YouTube URL validation and audio download via yt-dlp.

Only a canonical URL rebuilt from a validated 11-character video ID is ever passed to yt-dlp;
the user's raw string never reaches the downloader. Downloads go to the job's temporary
directory and are removed by the retention janitor.
"""

from __future__ import annotations

import os
import re
from urllib.parse import parse_qs, urlparse

from songscope_engine.errors import EngineError

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com",
                 "www.youtube-nocookie.com"}
SHORT_HOSTS = {"youtu.be", "www.youtu.be"}


class YouTubeError(EngineError):
    code = "youtube_error"


def parse_video_id(url: str) -> str:
    """Return the video ID for supported YouTube URL shapes or raise YouTubeError."""
    if not url or len(url) > 2048:
        raise YouTubeError("Please paste a valid YouTube URL.", "invalid_url")
    raw = url.strip()
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except ValueError:
        raise YouTubeError("Please paste a valid YouTube URL.", "invalid_url")
    if parsed.scheme.lower() not in ("http", "https"):
        raise YouTubeError("Only http(s) YouTube links are supported.", "invalid_url")
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    vid = None
    if host in SHORT_HOSTS:
        vid = path.lstrip("/").split("/")[0]
    elif host in YOUTUBE_HOSTS:
        if path == "/watch":
            vid = (parse_qs(parsed.query).get("v") or [None])[0]
        else:
            m = re.match(r"^/(shorts|embed|live|v)/([^/?#]+)", path)
            if m:
                vid = m.group(2)
            elif path.startswith("/playlist"):
                raise YouTubeError("Playlists are not supported — paste a link to a single video.", "unsupported_url")
    else:
        raise YouTubeError("This doesn't look like a YouTube link.", "unsupported_url")
    if not vid or not VIDEO_ID_RE.match(vid):
        raise YouTubeError("Could not find a valid video ID in this YouTube URL.", "invalid_url")
    return vid


def canonical_url(video_id: str) -> str:
    assert VIDEO_ID_RE.match(video_id)
    return f"https://www.youtube.com/watch?v={video_id}"


_ERROR_MAP = [
    (r"private video", "video_private", "This video is private."),
    (r"(age.restricted|confirm your age|inappropriate for some users)", "age_restricted",
     "This video is age-restricted and cannot be downloaded without signing in."),
    (r"(available in your country|geo.?restrict|blocked it in your country|not available in your region)", "region_restricted",
     "This video is not available in the server's region."),
    (r"(sign in to confirm you.?re not a bot|confirm you are not a robot)", "bot_check",
     "YouTube requested a bot check for this server. Configure SONGSCOPE_YOUTUBE_COOKIES_FILE or upload the audio file instead."),
    (r"(members-only|join this channel)", "members_only", "This video is for channel members only."),
    (r"(premieres in|live event will begin|is not yet available)", "not_started", "This video has not been released yet."),
    (r"(video unavailable|has been removed|does not exist|no longer available|account .* terminated)", "video_unavailable",
     "This video is unavailable."),
    (r"(copyright)", "video_unavailable", "This video was removed for copyright reasons."),
    (r"file is larger than max-filesize|max.?filesize", "too_large", "The audio stream exceeds the maximum file size."),
    (r"(duration|longer than)", "duration_limit", "The video is longer than the maximum allowed duration."),
]


def map_error(message: str) -> YouTubeError:
    low = message.lower()
    for pattern, code, friendly in _ERROR_MAP:
        if re.search(pattern, low):
            return YouTubeError(friendly, code)
    return YouTubeError("Downloading audio from YouTube failed. The video may be unavailable or restricted.",
                        "download_failed")


def download_audio(video_id: str, dest_dir: str, *, max_bytes: int, max_duration: int,
                   cookies_file: str | None = None, force_ipv4: bool = True,
                   progress=None) -> tuple[str, dict]:
    import yt_dlp

    url = canonical_url(video_id)

    def duration_filter(info, *, incomplete):
        dur = info.get("duration")
        if dur and dur > max_duration + 1:
            return f"Video duration {dur}s is longer than the limit"
        if info.get("is_live"):
            return "Live streams are not supported"
        return None

    def hook(d):
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                progress(min(0.99, d.get("downloaded_bytes", 0) / total))

    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best[height<=360]",
        "outtmpl": os.path.join(dest_dir, "source.%(ext)s"),
        "noplaylist": True,
        "max_filesize": max_bytes,
        "match_filter": duration_filter,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": 20,
        # YouTube needs a JavaScript runtime to solve its player challenges (solver: yt-dlp-ejs);
        # the highest-priority runtime that is installed is used.
        "js_runtimes": {"deno": {}, "node": {}},
        "retries": 2,
        "fragment_retries": 2,
        "concurrent_fragment_downloads": 1,
        "progress_hooks": [hook],
        "restrictfilenames": True,
        "windowsfilenames": True,
        "overwrites": True,
        "cachedir": False,
        "logger": _SilentLogger(),
    }
    if force_ipv4:
        # Many networks advertise IPv6 but cannot route it to YouTube; yt-dlp then hangs on
        # connection retries instead of falling back to IPv4.
        opts["source_address"] = "0.0.0.0"
    if cookies_file and os.path.isfile(cookies_file):
        opts["cookiefile"] = cookies_file
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        raise map_error(str(exc)) from exc
    except yt_dlp.utils.ExtractorError as exc:
        raise map_error(str(exc)) from exc
    if info is None:
        raise YouTubeError("The video could not be downloaded (it may exceed the duration limit).", "download_failed")
    files = [f for f in os.listdir(dest_dir) if f.startswith("source.") and not f.endswith((".part", ".ytdl"))]
    if not files:
        reason = "The video is longer than the maximum allowed duration." if (info.get("duration") or 0) > max_duration \
            else "Downloading audio from YouTube failed."
        raise YouTubeError(reason, "download_failed")
    path = os.path.join(dest_dir, files[0])
    meta = {
        "video_id": video_id,
        "url": url,
        "title": info.get("track") or info.get("title"),
        "video_title": info.get("title"),
        "artist": info.get("artist") or info.get("creator"),
        "channel": info.get("channel") or info.get("uploader"),
        "album": info.get("album"),
        "duration": info.get("duration"),
        "upload_date": info.get("upload_date"),
        "view_count": info.get("view_count"),
        "thumbnail": info.get("thumbnail"),
        "license": info.get("license"),
    }
    return path, meta


class _SilentLogger:
    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass
