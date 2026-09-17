"""Loudness & dynamics per ITU-R BS.1770-4 / EBU R128 / EBU Tech 3342.

Integrated loudness comes from pyloudnorm (reference BS.1770-4 implementation). Momentary
(400 ms) and short-term (3 s) series plus LRA are computed with a vectorised
implementation that reuses pyloudnorm's K-weighting filter coefficients.
"""

from __future__ import annotations

import numpy as np
import pyloudnorm as pyln
from scipy.signal import lfilter, resample_poly

from .confidence import annotate
from .decode import AudioSignal


def _db(x: float, floor: float = -120.0) -> float | None:
    if x <= 0 or not np.isfinite(x):
        return None
    return max(floor, 20.0 * np.log10(x))


def _lufs(ms: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore"):
        return -0.691 + 10.0 * np.log10(np.maximum(ms, 1e-20))


def k_weighted(stereo: np.ndarray, sr: int) -> np.ndarray:
    meter = pyln.Meter(sr)
    out = np.empty_like(stereo, dtype=np.float64)
    for ch in range(stereo.shape[0]):
        x = stereo[ch].astype(np.float64)
        for stage in meter._filters.values():
            x = stage.passband_gain * lfilter(stage.b, stage.a, x)
        out[ch] = x
    return out


def windowed_loudness(kw: np.ndarray, sr: int, window_s: float, hop_s: float) -> tuple[np.ndarray, np.ndarray]:
    """Return (block start times, LUFS) for sliding windows over K-weighted audio."""
    sq = np.sum(kw**2, axis=0)  # channel gains are 1.0 for L/R
    csum = np.concatenate([[0.0], np.cumsum(sq)])
    win = int(round(window_s * sr))
    hop = int(round(hop_s * sr))
    if len(sq) < win:
        return np.array([0.0]), _lufs(np.array([csum[-1] / max(1, len(sq))]))
    starts = np.arange(0, len(sq) - win + 1, hop)
    ms = (csum[starts + win] - csum[starts]) / win
    return starts / sr, _lufs(ms)


def loudness_range(short_term_lufs: np.ndarray) -> float | None:
    """EBU Tech 3342 LRA from short-term (3 s) loudness values."""
    st = short_term_lufs[short_term_lufs > -70.0]
    if len(st) < 2:
        return None
    energy_mean = 10 * np.log10(np.mean(10 ** (st / 10)))
    gated = st[st > energy_mean - 20.0]
    if len(gated) < 2:
        return None
    return float(np.percentile(gated, 95) - np.percentile(gated, 10))


def true_peak(stereo: np.ndarray, oversample: int = 4, chunk_s: float = 10.0, sr: int = 44100) -> float:
    """Inter-sample peak estimate via 4x polyphase oversampling (BS.1770-4 Annex 2)."""
    chunk = int(chunk_s * sr)
    pad = 256
    peak = 0.0
    n = stereo.shape[1]
    for ch in range(stereo.shape[0]):
        x = stereo[ch]
        for start in range(0, n, chunk):
            a = max(0, start - pad)
            b = min(n, start + chunk + pad)
            up = resample_poly(x[a:b].astype(np.float64), oversample, 1)
            peak = max(peak, float(np.max(np.abs(up))) if len(up) else 0.0)
    return peak


def dr_score(stereo: np.ndarray, sr: int) -> float | None:
    """Crest-factor dynamic range in the style of the TT DR meter (3 s blocks, top 20% RMS)."""
    block = 3 * sr
    n_blocks = stereo.shape[1] // block
    if n_blocks < 2:
        return None
    values = []
    for ch in range(stereo.shape[0]):
        x = stereo[ch, : n_blocks * block].reshape(n_blocks, block).astype(np.float64)
        rms = np.sqrt(2.0 * np.mean(x**2, axis=1))
        peaks = np.sort(np.max(np.abs(x), axis=1))
        top = np.sort(rms)[-max(1, int(round(n_blocks * 0.2))):]
        rms_top = np.sqrt(np.mean(top**2))
        peak2 = peaks[-2] if len(peaks) > 1 else peaks[-1]
        if rms_top > 0 and peak2 > 0:
            values.append(20 * np.log10(peak2 / rms_top))
    return float(np.mean(values)) if values else None


def _series(times: np.ndarray, values: np.ndarray, max_points: int = 1500) -> dict:
    step = max(1, int(np.ceil(len(values) / max_points)))
    t = times[::step]
    v = values[::step]
    return {
        "times": [round(float(x), 2) for x in t],
        "lufs": [round(float(x), 1) if x > -70 else None for x in v],
    }


def analyze_loudness(sig: AudioSignal) -> dict:
    stereo, sr = sig.stereo, sig.sr_full
    meter = pyln.Meter(sr)
    integrated = float(meter.integrated_loudness(stereo.T.astype(np.float64)))
    integrated_val = integrated if np.isfinite(integrated) and integrated > -70 else None

    kw = k_weighted(stereo, sr)
    m_t, m_l = windowed_loudness(kw, sr, 0.4, 0.1)
    s_t, s_l = windowed_loudness(kw, sr, 3.0, 0.1)
    lra = loudness_range(s_l)

    sample_peak = float(np.max(np.abs(stereo)))
    tp = true_peak(stereo, sr=sr)
    rms = float(np.sqrt(np.mean(stereo.astype(np.float64) ** 2)))
    rms_db = _db(rms)
    tp_db = _db(tp)
    sp_db = _db(sample_peak)

    # Clipping: runs of >=3 consecutive samples at (near) full scale.
    clipped_runs = 0
    for ch in range(stereo.shape[0]):
        hot = np.abs(stereo[ch]) >= 0.9995
        if hot.any():
            runs = np.diff(np.concatenate([[0], hot.astype(np.int8), [0]]))
            starts, ends = np.where(runs == 1)[0], np.where(runs == -1)[0]
            clipped_runs += int(np.sum((ends - starts) >= 3))

    stereo_info = None
    if stereo.shape[0] == 2:
        l, r = stereo[0].astype(np.float64), stereo[1].astype(np.float64)
        denom = np.sqrt(np.sum(l**2) * np.sum(r**2))
        corr = float(np.sum(l * r) / denom) if denom > 0 else 1.0
        mid, side = (l + r) / 2, (l - r) / 2
        width = float(np.sqrt(np.mean(side**2)) / (np.sqrt(np.mean(mid**2)) + 1e-12))
        stereo_info = {"correlation": round(corr, 3), "side_to_mid_ratio": round(width, 3)}

    if integrated_val is None:
        character = "Near-silent audio — loudness could not be measured meaningfully."
    elif integrated_val > -8:
        character = "Very loud master; heavy limiting is likely."
    elif integrated_val > -12:
        character = "Loud master, typical of modern commercial releases."
    elif integrated_val > -16:
        character = "Moderate loudness with room for dynamics."
    else:
        character = "Quiet / highly dynamic master (or a streaming-normalised source)."

    block = {
        "available": True,
        "integrated_lufs": round(integrated_val, 1) if integrated_val is not None else None,
        "true_peak_dbtp": round(tp_db, 1) if tp_db is not None else None,
        "sample_peak_dbfs": round(sp_db, 1) if sp_db is not None else None,
        "rms_dbfs": round(rms_db, 1) if rms_db is not None else None,
        "crest_factor_db": round(sp_db - rms_db, 1) if (sp_db is not None and rms_db is not None) else None,
        "loudness_range_lu": round(lra, 1) if lra is not None else None,
        "plr_db": round(tp_db - integrated_val, 1) if (tp_db is not None and integrated_val is not None) else None,
        "dynamic_range_db": round(dr, 1) if (dr := dr_score(stereo, sr)) is not None else None,
        "max_momentary_lufs": round(float(np.max(m_l)), 1) if len(m_l) else None,
        "max_short_term_lufs": round(float(np.max(s_l)), 1) if len(s_l) else None,
        "clipping_events": clipped_runs,
        "stereo": stereo_info,
        "character": character,
        "momentary": _series(m_t + 0.2, m_l),
        "short_term": _series(s_t + 1.5, s_l),
        "method": "ITU-R BS.1770-4 (pyloudnorm) · EBU Tech 3342 LRA · 4× oversampled true peak",
    }
    return annotate(block, 1.0, "detected")
