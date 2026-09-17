import io

import numpy as np
import pytest
import soundfile as sf

from songscope_api import security, youtube
from songscope_engine.errors import EngineError


# --- YouTube URL validation --------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
    "https://youtu.be/dQw4w9WgXcQ?si=abc",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RDAMVM",
])
def test_youtube_valid_urls(url):
    assert youtube.parse_video_id(url) == "dQw4w9WgXcQ"
    assert youtube.canonical_url("dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.parametrize("url,code", [
    ("", "invalid_url"),
    ("https://vimeo.com/12345", "unsupported_url"),
    ("https://www.youtube.com/watch?v=short", "invalid_url"),
    ("https://www.youtube.com/playlist?list=PL123", "unsupported_url"),
    ("https://evil.com/?u=youtube.com/watch?v=dQw4w9WgXcQ", "unsupported_url"),
    ("javascript:alert(1)", "invalid_url"),
    ("https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ", "unsupported_url"),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ;rm -rf", "invalid_url"),
])
def test_youtube_invalid_urls(url, code):
    with pytest.raises(EngineError) as exc:
        youtube.parse_video_id(url)
    assert exc.value.code in (code, "invalid_url", "unsupported_url")


@pytest.mark.parametrize("message,code", [
    ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access", "video_private"),
    ("ERROR: [youtube] abc: Video unavailable", "video_unavailable"),
    ("ERROR: Sign in to confirm your age. This video may be inappropriate for some users.", "age_restricted"),
    ("ERROR: The uploader has not made this video available in your country", "region_restricted"),
    ("ERROR: something odd happened", "download_failed"),
])
def test_youtube_error_mapping(message, code):
    assert youtube.map_error(message).code == code


# --- security helpers ------------------------------------------------------------------------

def test_sanitize_filename():
    assert security.sanitize_filename("../../etc/passwd") == "passwd"
    assert security.sanitize_filename("C:\\Users\\x\\My Song!!.MP3") == "My Song_.mp3"
    assert security.sanitize_filename("<script>.wav").endswith(".wav")
    assert security.sanitize_filename("") == "audio"


def test_sniff_audio(tone_wav_bytes):
    assert security.sniff_audio(tone_wav_bytes[:64]) == "wav"
    assert security.sniff_audio(b"fLaC" + b"\0" * 20) == "flac"
    assert security.sniff_audio(b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb" + b"\0" * 20) == "mp3"
    assert security.sniff_audio(b"\0\0\0\x20ftypM4A " + b"\0" * 20) == "mp4"
    assert security.sniff_audio(b"<html><body>hi</body></html>") is None


def test_rate_limiter():
    rl = security.RateLimiter(2)
    assert rl.allow("a") and rl.allow("a") and not rl.allow("a") and rl.allow("b")


# --- API -------------------------------------------------------------------------------------

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["capabilities"]["ffmpeg"] is True
    assert body["limits"]["max_upload_mb"] == 3


def test_upload_rejects_unsupported_extension(client):
    r = client.post("/api/analyze/upload", files={"file": ("notes.txt", b"hello world", "text/plain")})
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "unsupported_format"


def test_upload_rejects_fake_audio(client):
    r = client.post("/api/analyze/upload", files={"file": ("song.mp3", b"<html>" + b"x" * 5000, "audio/mpeg")})
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "invalid_audio"


def test_upload_rejects_mismatched_extension(client, tone_wav_bytes):
    r = client.post("/api/analyze/upload", files={"file": ("song.flac", tone_wav_bytes, "audio/flac")})
    assert r.status_code == 415


def test_upload_rejects_empty(client):
    r = client.post("/api/analyze/upload", files={"file": ("song.wav", b"", "audio/wav")})
    assert r.status_code in (400, 415)


def test_upload_rejects_large_file(client):
    big = b"RIFF\x00\x00\x00\x00WAVE" + b"\0" * (4 * 1024 * 1024)
    r = client.post("/api/analyze/upload", files={"file": ("big.wav", big, "audio/wav")})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "file_too_large"


def test_upload_rejects_too_long(client):
    y = np.zeros((44100 * 70, 1), dtype=np.int16)  # 70 s mono silence, limit is 60 s (~3 MB > limit? use 8 kHz)
    buf = io.BytesIO()
    sf.write(buf, y[: 8000 * 70], 8000, format="WAV", subtype="PCM_16")
    r = client.post("/api/analyze/upload", files={"file": ("long.wav", buf.getvalue(), "audio/wav")})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "duration_limit"


def test_youtube_endpoint_validation(client):
    r = client.post("/api/analyze/youtube", json={"url": "https://example.com/video"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "unsupported_url"


def test_youtube_endpoint_queues_job(client):
    r = client.post("/api/analyze/youtube", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    assert r.status_code == 202
    aid = r.json()["analysis_id"]
    status = client.get(f"/api/analyze/{aid}/status").json()
    assert status["status"] == "queued" and status["source_type"] == "youtube"
    # cache: same video id is deduplicated
    again = client.post("/api/analyze/youtube", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}).json()
    assert again["analysis_id"] == aid and again["cached"] is True
    assert client.post(f"/api/analyze/{aid}/cancel").status_code == 200
    assert client.get(f"/api/analyze/{aid}/status").json()["status"] == "cancelled"
    assert client.delete(f"/api/analyze/{aid}").status_code == 204
    assert client.get(f"/api/analyze/{aid}").status_code == 404


def test_unknown_analysis_404(client):
    assert client.get("/api/analyze/doesnotexist").status_code == 404
    assert client.get("/api/analyze/../../etc/status").status_code == 404


def test_results_not_ready(client, song_wav_bytes):
    r = client.post("/api/analyze/upload", files={"file": ("clip.wav", song_wav_bytes, "audio/wav")}, data={"force": "true"})
    aid = r.json()["analysis_id"]
    assert client.get(f"/api/analyze/{aid}/results").status_code == 409
    assert client.get(f"/api/analyze/{aid}/export?format=pdf").status_code == 409
    client.delete(f"/api/analyze/{aid}")


def test_end_to_end_upload_analysis_and_exports(client, song_wav_bytes):
    """Upload → run the job in-process → results, audio, exports, cache, delete."""
    from songscope_api.db import session_scope
    from songscope_api.models import Job
    from songscope_api.worker_process import run_job

    r = client.post("/api/analyze/upload", files={"file": ("Test Song.wav", song_wav_bytes, "audio/wav")})
    assert r.status_code == 202, r.text
    aid = r.json()["analysis_id"]
    with session_scope() as s:
        job_id = s.query(Job).filter(Job.analysis_id == aid).one().id
        s.query(Job).filter(Job.id == job_id).update({"status": "running"})
    run_job(job_id)

    status = client.get(f"/api/analyze/{aid}/status").json()
    assert status["status"] == "completed", status
    assert status["progress"] == 1.0
    assert all(st["state"] == "done" for st in status["stages"])

    full = client.get(f"/api/analyze/{aid}").json()
    res = full["results"]
    assert res["metadata"]["title"] == "Test Song.wav"
    assert res["metadata"]["sample_rate"] == 44100 and res["metadata"]["channels"] == 2
    assert res["tempo"]["bpm"] == pytest.approx(124, abs=2)
    assert res["key"]["key"] in ("E Major", "C# Minor")
    assert res["loudness"]["integrated_lufs"] is not None
    assert full["audio"]["available"] is True

    audio = client.get(f"/api/analyze/{aid}/audio")
    assert audio.status_code == 200 and audio.content[:4] == b"RIFF"
    ranged = client.get(f"/api/analyze/{aid}/audio", headers={"Range": "bytes=0-99"})
    assert ranged.status_code == 206 and len(ranged.content) == 100

    for fmt, magic in (("json", b"{"), ("csv", b"\xef\xbb\xbfcategory"), ("txt", b"SONGSCOPE"), ("pdf", b"%PDF")):
        e = client.get(f"/api/analyze/{aid}/export?format={fmt}")
        assert e.status_code == 200 and e.content.startswith(magic), fmt
        assert "attachment" in e.headers["content-disposition"]

    # identical content is served from cache
    again = client.post("/api/analyze/upload", files={"file": ("copy.wav", song_wav_bytes, "audio/wav")}).json()
    assert again["cached"] is True and again["analysis_id"] == aid

    explain = client.post(f"/api/analyze/{aid}/explain", json={"audience": "guitarist"})
    assert explain.status_code == 503  # no API key configured in tests
    assert client.post(f"/api/analyze/{aid}/explain", json={"audience": "nobody"}).status_code == 422

    listing = client.get("/api/analyses").json()["items"]
    assert any(i["id"] == aid for i in listing)
    assert client.delete(f"/api/analyze/{aid}").status_code == 204
    assert client.get(f"/api/analyze/{aid}/audio").status_code == 404


def test_analysis_failure_is_recorded(client, tone_wav_bytes, monkeypatch):
    from songscope_api.db import session_scope
    from songscope_api.models import Job
    from songscope_api.worker_process import run_job

    r = client.post("/api/analyze/upload", files={"file": ("tone.wav", tone_wav_bytes, "audio/wav")})
    aid = r.json()["analysis_id"]

    import songscope_engine.pipeline as pipeline

    def boom(*a, **k):
        raise EngineError("Audio decoding failed. corrupt stream", "decode_failed")

    monkeypatch.setattr(pipeline, "run_analysis", boom)
    with session_scope() as s:
        job_id = s.query(Job).filter(Job.analysis_id == aid).one().id
        s.query(Job).filter(Job.id == job_id).update({"status": "running"})
    run_job(job_id)
    st = client.get(f"/api/analyze/{aid}/status").json()
    assert st["status"] == "failed"
    assert st["error"]["code"] == "decode_failed"
    assert "decoding failed" in st["error"]["message"].lower()
