"""Spectral descriptors, long-term average spectrum, band balance and a playback-synced band spectrogram."""

from __future__ import annotations

import librosa
import numpy as np
from scipy.signal import welch

from .confidence import annotate
from .decode import AudioSignal
from .theory import hz_to_note

BANDS = [
    ("sub_bass", "Sub Bass", 20, 60),
    ("bass", "Bass", 60, 250),
    ("low_mid", "Low Mid", 250, 500),
    ("mid", "Mid", 500, 2000),
    ("high_mid", "High Mid", 2000, 6000),
    ("treble", "Treble", 6000, 20000),
]


def _stats(x: np.ndarray, digits: int = 1) -> dict:
    x = x[np.isfinite(x)]
    if not x.size:
        return {"mean": None, "std": None, "p10": None, "p90": None}
    return {"mean": round(float(np.mean(x)), digits), "std": round(float(np.std(x)), digits),
            "p10": round(float(np.percentile(x, 10)), digits), "p90": round(float(np.percentile(x, 90)), digits)}


def _series(times: np.ndarray, x: np.ndarray, max_points: int = 800, digits: int = 1) -> dict:
    step = max(1, int(np.ceil(len(x) / max_points)))
    return {"times": [round(float(t), 2) for t in times[::step]], "values": [round(float(v), digits) for v in x[::step]]}


def analyze_spectrum(sig: AudioSignal) -> dict:
    y = sig.mono_full()
    sr = sig.sr_full
    n_fft, hop = 4096, 2048
    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    times = librosa.frames_to_time(np.arange(S.shape[1]), sr=sr, hop_length=hop)
    power = S**2
    frame_energy = power.sum(axis=0)
    active = frame_energy > frame_energy.max() * 1e-5

    centroid = librosa.feature.spectral_centroid(S=S, sr=sr)[0]
    bandwidth = librosa.feature.spectral_bandwidth(S=S, sr=sr)[0]
    rolloff = librosa.feature.spectral_rolloff(S=S, sr=sr, roll_percent=0.85)[0]
    flatness = librosa.feature.spectral_flatness(S=S)[0]
    contrast = librosa.feature.spectral_contrast(S=S, sr=sr, n_bands=6, fmin=100.0)
    zcr = librosa.feature.zero_crossing_rate(y, frame_length=n_fft, hop_length=hop)[0][: S.shape[1]]
    rms = librosa.feature.rms(S=S, frame_length=n_fft)[0]
    rms_db = 20 * np.log10(rms / (rms.max() + 1e-12) + 1e-9)

    # long-term average spectrum on 1/12-octave bins
    f, psd = welch(y.astype(np.float64), fs=sr, nperseg=8192, noverlap=4096)
    edges = 20.0 * 2 ** (np.arange(0, np.log2(20000 / 20) * 12 + 1) / 12)
    centers, levels = [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (f >= lo) & (f < hi)
        if m.any():
            centers.append(float(np.sqrt(lo * hi)))
            levels.append(float(np.mean(psd[m])))
    levels = np.array(levels)
    ltas_db = 10 * np.log10(levels / (levels.max() + 1e-20) + 1e-12)
    centers = np.array(centers)
    pink_tilt = ltas_db + 3.0 * np.log2(centers / 1000.0)  # flat for pink-noise-like balance

    band_power = {}
    for key, name, lo, hi in BANDS:
        m = (f >= lo) & (f < min(hi, sr / 2))
        band_power[key] = float(np.sum(psd[m])) if m.any() else 0.0
    total = sum(band_power.values()) + 1e-20
    bands = []
    for key, name, lo, hi in BANDS:
        m = (centers >= lo) & (centers < hi)
        bands.append({"key": key, "name": name, "low_hz": lo, "high_hz": hi,
                      "energy_share": round(band_power[key] / total, 4),
                      "level_db": round(float(10 * np.log10(band_power[key] / total + 1e-12)), 1),
                      "tilt_corrected_db": round(float(np.mean(pink_tilt[m])), 1) if m.any() else None})
    tc = [b for b in bands if b["tilt_corrected_db"] is not None]
    ref = float(np.median([b["tilt_corrected_db"] for b in tc]))
    dominant = sorted(tc, key=lambda b: b["tilt_corrected_db"], reverse=True)
    emphasized = [b["name"] for b in dominant if b["tilt_corrected_db"] - ref >= 2.0][:3]

    audible = centers >= 30
    peak_hz = float(centers[audible][np.argmax(ltas_db[audible])])
    c_mean = float(np.mean(centroid[active])) if active.any() else 0.0
    brightness = "Dark / warm" if c_mean < 1500 else ("Balanced" if c_mean < 3000 else "Bright")
    flat_mean = float(np.mean(flatness[active])) if active.any() else 0.0
    texture = "Tonal" if flat_mean < 0.05 else ("Mixed tonal/noisy" if flat_mean < 0.2 else "Noisy / percussive")

    # band spectrogram synced to playback (~1/6 octave, <= 1200 frames)
    b_edges = 20.0 * 2 ** (np.arange(0, np.log2(20000 / 20) * 6 + 1) / 6)
    b_centers, rows = [], []
    for lo, hi in zip(b_edges[:-1], b_edges[1:]):
        m = (freqs >= lo) & (freqs < hi)
        if not m.any():
            m = np.zeros_like(freqs, dtype=bool)
            m[np.argmin(np.abs(freqs - np.sqrt(lo * hi)))] = True
        b_centers.append(round(float(np.sqrt(lo * hi)), 1))
        rows.append(power[m].mean(axis=0))
    B = np.array(rows)
    frames_per_quarter_second = max(1, int(round(0.25 * sr / hop)))
    t_step = max(frames_per_quarter_second, int(np.ceil(B.shape[1] / 1500)))
    n_cols = B.shape[1] // t_step
    Bd = B[:, : n_cols * t_step].reshape(B.shape[0], n_cols, t_step).mean(axis=2)
    Bdb = 10 * np.log10(Bd / (Bd.max() + 1e-20) + 1e-10)
    Bdb = np.clip(Bdb, -90, 0)

    block = {
        "available": True,
        "summary": {"brightness": brightness, "texture": texture, "emphasized_regions": emphasized,
                    "peak_frequency_hz": round(peak_hz, 1), "peak_frequency_note": hz_to_note(peak_hz)},
        "centroid_hz": _stats(centroid[active]),
        "bandwidth_hz": _stats(bandwidth[active]),
        "rolloff_hz": _stats(rolloff[active]),
        "flatness": _stats(flatness[active], 4),
        "zero_crossing_rate": _stats(zcr[active], 4),
        "rms_db": _stats(rms_db[active]),
        "contrast_db": {f"band_{i}": round(float(np.mean(contrast[i, active])), 1) for i in range(contrast.shape[0])},
        "bands": bands,
        "ltas": {"freqs": [round(float(x), 1) for x in centers], "db": [round(float(x), 1) for x in ltas_db]},
        "series": {"centroid_hz": _series(times, centroid, digits=0), "rolloff_hz": _series(times, rolloff, digits=0),
                   "rms_db": _series(times, rms_db)},
        "spectrogram": {"freqs": b_centers, "seconds_per_frame": round(t_step * hop / sr, 4),
                        "db": [[int(round(v)) for v in col] for col in Bdb.T]},
    }
    return annotate(block, 1.0, "detected")
