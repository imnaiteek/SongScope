"""Probing, tag extraction, normalisation to the internal analysis format, and loading."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import numpy as np
import soundfile as sf

from . import ffmpeg
from .errors import DecodeError, DurationLimitError, UnsupportedMediaError

ANALYSIS_SR = 22050
HOP = 512
NATIVE_RATES = (44100, 48000)
# Containers every mainstream browser can play without transcoding.
BROWSER_PLAYABLE = {"mp3", "m4a", "aac", "mp4", "ogg", "oga", "opus", "webm", "wav", "flac"}


@dataclass
class ProbeInfo:
    format_name: str | None = None
    codec: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    bit_depth: int | None = None
    bit_rate: int | None = None
    duration: float | None = None
    tags: dict = field(default_factory=dict)


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_BITRATE_RE = re.compile(r"bitrate:\s*(\d+)\s*kb/s")
_AUDIO_RE = re.compile(r"Stream #\d+:\d+.*?: Audio: ([^,\s]+)[^,]*,\s*(\d+) Hz,\s*([^,]+),\s*([^,\s]+)")
_INPUT_RE = re.compile(r"Input #0, ([^,]+(?:,[^,]+)*?), from")


def probe(path: str, timeout: float = 30) -> ProbeInfo:
    """Inspect a media file. Uses ffprobe when present, otherwise parses `ffmpeg -i`."""
    fp = ffmpeg.ffprobe_path()
    if fp:
        return _probe_ffprobe(fp, path, timeout)
    exe = ffmpeg.ffmpeg_path()
    if not exe:
        raise DecodeError("FFmpeg is not available on the server.")
    res = ffmpeg.run([exe, "-hide_banner", "-nostdin", "-i", path], timeout=timeout)
    text = res.stderr.decode("utf-8", errors="replace")
    info = ProbeInfo()
    m = _INPUT_RE.search(text)
    if m:
        info.format_name = m.group(1).strip()
    m = _DURATION_RE.search(text)
    if m:
        info.duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = _BITRATE_RE.search(text)
    if m:
        info.bit_rate = int(m.group(1)) * 1000
    m = _AUDIO_RE.search(text)
    if not m:
        raise UnsupportedMediaError("No audio stream was found in this file.")
    info.codec = m.group(1)
    info.sample_rate = int(m.group(2))
    layout = m.group(3).strip()
    info.channels = {"mono": 1, "stereo": 2}.get(layout.split("(")[0].strip())
    if info.channels is None:
        mm = re.match(r"(\d+)(?:\.(\d+))?", layout)
        info.channels = int(mm.group(1)) + (int(mm.group(2)) if mm and mm.group(2) else 0) if mm else None
    info.bit_depth = _bit_depth_from_sample_fmt(m.group(4), info.codec)
    return info


def _probe_ffprobe(fp: str, path: str, timeout: float) -> ProbeInfo:
    res = ffmpeg.run(
        [fp, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path], timeout=timeout
    )
    if res.returncode != 0:
        raise UnsupportedMediaError("The file could not be read as audio.")
    data = json.loads(res.stdout.decode("utf-8", errors="replace") or "{}")
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        raise UnsupportedMediaError("No audio stream was found in this file.")
    s = streams[0]
    fmt = data.get("format", {})
    bits = s.get("bits_per_raw_sample") or s.get("bits_per_sample")
    try:
        bits = int(bits) or None
    except (TypeError, ValueError):
        bits = None
    return ProbeInfo(
        format_name=fmt.get("format_name"),
        codec=s.get("codec_name"),
        sample_rate=int(s["sample_rate"]) if s.get("sample_rate") else None,
        channels=s.get("channels"),
        bit_depth=bits or _bit_depth_from_sample_fmt(s.get("sample_fmt", ""), s.get("codec_name", "")),
        bit_rate=int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
        duration=float(fmt["duration"]) if fmt.get("duration") else None,
        tags={k.lower(): v for k, v in (fmt.get("tags") or {}).items()},
    )


def _bit_depth_from_sample_fmt(sample_fmt: str, codec: str | None) -> int | None:
    # Bit depth is only meaningful for lossless/PCM codecs.
    lossless = codec and (codec.startswith("pcm_") or codec in ("flac", "alac", "wavpack", "ape"))
    if not lossless:
        return None
    if codec and codec.startswith("pcm_"):
        m = re.search(r"(\d+)", codec)
        if m:
            return int(m.group(1))
    m = re.search(r"(\d+)", sample_fmt or "")
    return int(m.group(1)) if m else None


def read_tags(path: str) -> dict:
    """Title/artist/album from embedded tags (ID3, Vorbis comments, MP4 atoms...)."""
    out: dict = {}
    try:
        import mutagen

        f = mutagen.File(path, easy=True)
        if f is not None and f.tags:
            for key in ("title", "artist", "album", "albumartist", "date", "genre"):
                val = f.tags.get(key)
                if val:
                    out[key] = str(val[0] if isinstance(val, list) else val)[:300]
    except Exception:
        pass
    return out


def normalize(src: str, dst_wav: str, probe_info: ProbeInfo, max_duration: float, timeout: float = 600) -> str:
    """Produce the internal analysis file (float32 PCM WAV, 44.1/48 kHz, <=2 ch).

    Files that already satisfy the format are used as-is (no re-encode).
    """
    if probe_info.duration is not None and probe_info.duration > max_duration + 1:
        raise DurationLimitError(
            f"Audio is {probe_info.duration / 60:.1f} min long; the limit is {max_duration / 60:.0f} min."
        )
    try:
        sfi = sf.info(src)
        if (
            sfi.format in ("WAV", "WAVEX", "FLAC", "AIFF")
            and sfi.samplerate in NATIVE_RATES
            and sfi.channels <= 2
            and sfi.duration <= max_duration + 1
        ):
            return src
    except Exception:
        pass

    exe = ffmpeg.ffmpeg_path()
    if not exe:
        raise DecodeError("FFmpeg is not available on the server.")
    rate = probe_info.sample_rate if probe_info.sample_rate in NATIVE_RATES else 44100
    channels = str(min(2, probe_info.channels or 2))
    args = [
        exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", ffmpeg.FFMPEG_THREADS,
        "-i", src, "-map", "0:a:0", "-vn", "-sn", "-dn",
        "-ac", channels, "-ar", str(rate), "-c:a", "pcm_f32le", "-t", str(int(max_duration)),
        "-y", dst_wav,
    ]
    res = ffmpeg.run(args, timeout=timeout)
    if res.returncode != 0 or not os.path.exists(dst_wav) or os.path.getsize(dst_wav) < 1000:
        detail = res.stderr.decode("utf-8", errors="replace").strip().splitlines()[-1:] or [""]
        raise DecodeError(f"Audio decoding failed. {detail[0][:200]}")
    return dst_wav


def prepare_playback(src: str, dst_m4a: str, timeout: float = 600) -> str:
    """Return a browser-playable file; only transcodes formats browsers cannot play (e.g. AIFF)."""
    ext = os.path.splitext(src)[1].lower().lstrip(".")
    if ext in BROWSER_PLAYABLE:
        return src
    exe = ffmpeg.ffmpeg_path()
    args = [
        exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", ffmpeg.FFMPEG_THREADS,
        "-i", src, "-map", "0:a:0", "-vn", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        "-y", dst_m4a,
    ]
    res = ffmpeg.run(args, timeout=timeout)
    if res.returncode != 0:
        raise DecodeError("Could not prepare a playback copy of the audio.")
    return dst_m4a


@dataclass
class AudioSignal:
    stereo: np.ndarray  # (channels, samples) float32 at sr_full
    sr_full: int
    mono: np.ndarray  # float32 at ANALYSIS_SR
    sr: int = ANALYSIS_SR
    hop: int = HOP
    _cache: dict = field(default_factory=dict, repr=False)

    @property
    def duration(self) -> float:
        return self.stereo.shape[1] / self.sr_full

    def mono_full(self) -> np.ndarray:
        if "mono_full" not in self._cache:
            self._cache["mono_full"] = self.stereo.mean(axis=0).astype(np.float32)
        return self._cache["mono_full"]

    def hpss(self) -> tuple[np.ndarray, np.ndarray]:
        if "hpss" not in self._cache:
            import librosa

            D = librosa.stft(self.mono, n_fft=2048, hop_length=self.hop)
            H, P = librosa.decompose.hpss(D, margin=1.0)
            h = librosa.istft(H, hop_length=self.hop, length=len(self.mono)).astype(np.float32)
            p = librosa.istft(P, hop_length=self.hop, length=len(self.mono)).astype(np.float32)
            self._cache["hpss"] = (h, p)
            self._cache["hpss_energy"] = (float(np.mean(np.abs(H) ** 2)), float(np.mean(np.abs(P) ** 2)))
        return self._cache["hpss"]

    @property
    def harmonic(self) -> np.ndarray:
        return self.hpss()[0]

    @property
    def percussive(self) -> np.ndarray:
        return self.hpss()[1]

    def percussive_ratio(self) -> float:
        self.hpss()
        h, p = self._cache["hpss_energy"]
        return p / (h + p + 1e-12)


def load_signal(wav_path: str) -> AudioSignal:
    import librosa

    try:
        data, sr = sf.read(wav_path, dtype="float32", always_2d=True)
    except Exception as exc:
        raise DecodeError(f"Could not read decoded audio: {exc}") from exc
    stereo = np.ascontiguousarray(data.T)
    if stereo.shape[1] < sr * 1.0:
        raise DecodeError("Audio is too short to analyse (under 1 second).")
    stereo = np.nan_to_num(stereo, nan=0.0, posinf=0.0, neginf=0.0)
    mono = librosa.resample(stereo.mean(axis=0), orig_sr=sr, target_sr=ANALYSIS_SR, res_type="soxr_hq")
    return AudioSignal(stereo=stereo, sr_full=int(sr), mono=mono.astype(np.float32))


def waveform_peaks(sig: AudioSignal, peaks_per_second: int = 50) -> dict:
    x = np.abs(sig.stereo).max(axis=0)
    bucket = max(1, int(sig.sr_full / peaks_per_second))
    n = len(x) // bucket
    peaks = x[: n * bucket].reshape(n, bucket).max(axis=1) if n else np.array([0.0])
    top = float(peaks.max()) or 1.0
    return {
        "peaks_per_second": sig.sr_full / bucket,
        "peaks": [round(float(v), 3) for v in peaks],
        "max_amplitude": round(top, 4),
    }
