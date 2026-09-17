"""Tempo estimation and beat tracking.

Several independent estimators are combined rather than trusting one algorithm:
  1. global autocorrelation of the onset-strength envelope
  2. global Fourier spectrum of the onset envelope
  3. librosa's prior-weighted tempogram estimate
  4. dynamic-programming beat tracker (median inter-beat interval)
  5. inter-onset-interval histogram

Candidates (and their half/double/triplet relatives) are scored by salience,
cross-estimator agreement and a perceptual tempo prior. The runner-up metrical
interpretation is exposed as an alternative (half-time / double-time).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import librosa
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

from .confidence import annotate, clamp01
from .decode import AudioSignal

BPM_MIN, BPM_MAX = 30.0, 300.0
PRIOR_CENTER, PRIOR_SIGMA_OCT = 115.0, 0.9


@dataclass
class RhythmInternals:
    onset_env: np.ndarray
    low_env: np.ndarray
    frame_rate: float
    beat_frames: np.ndarray
    beat_times: np.ndarray
    bpm: float | None
    confidence: float
    onset_times: np.ndarray = field(default_factory=lambda: np.array([]))
    mel_db: np.ndarray | None = None


def _norm(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    m = np.max(np.abs(x)) if x.size else 0
    return x / m if m > 0 else x


def prior(bpm: float) -> float:
    return float(np.exp(-0.5 * (np.log2(bpm / PRIOR_CENTER) / PRIOR_SIGMA_OCT) ** 2))


def tempo_category(bpm: float | None) -> str | None:
    if bpm is None:
        return None
    if bpm < 66:
        return "Very Slow"
    if bpm < 90:
        return "Slow"
    if bpm < 120:
        return "Moderate"
    if bpm < 150:
        return "Fast"
    return "Very Fast"


class Salience:
    """Continuous periodicity salience S(bpm) from the whole onset envelope."""

    def __init__(self, env: np.ndarray, frame_rate: float):
        self.fr = frame_rate
        x = env - env.mean()
        max_lag = int(frame_rate * 60.0 / BPM_MIN * 1.1)
        ac = librosa.autocorrelate(x, max_size=min(len(x), max_lag + 2))
        self.ac = np.clip(ac / ac[0], 0, None) if ac[0] > 0 else np.zeros_like(ac)
        n_fft = 1 << int(np.ceil(np.log2(max(len(x) * 4, 2**14))))
        spec = np.abs(np.fft.rfft(x * np.hanning(len(x)), n=n_fft))
        self.ft_bpm = np.fft.rfftfreq(n_fft, d=1.0 / frame_rate) * 60.0
        self.ft = spec / (spec[(self.ft_bpm >= BPM_MIN) & (self.ft_bpm <= BPM_MAX)].max() + 1e-12)
        grid = np.geomspace(BPM_MIN, BPM_MAX, 1200)
        self.grid = grid
        self.ac_grid = self.ac_at(grid)
        self.ft_grid = np.interp(grid, self.ft_bpm, self.ft)
        acn = self.ac_grid / (self.ac_grid.max() + 1e-12)
        self.s_grid = np.sqrt(np.clip(acn, 0, None) * np.clip(self.ft_grid, 0, None))

    def ac_at(self, bpm: np.ndarray | float) -> np.ndarray:
        lag = self.fr * 60.0 / np.asarray(bpm, dtype=float)
        return np.interp(lag, np.arange(len(self.ac)), self.ac, right=0.0)

    def __call__(self, bpm: float) -> float:
        return float(np.interp(bpm, self.grid, self.s_grid))

    def peaks(self, curve: np.ndarray, top: int = 3) -> list[float]:
        pk, _ = find_peaks(curve, prominence=0.05 * (curve.max() + 1e-12))
        order = pk[np.argsort(curve[pk])[::-1]][:top]
        return [float(self.grid[i]) for i in order]


def onset_envelopes(sig: AudioSignal) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    S = librosa.feature.melspectrogram(y=sig.mono, sr=sig.sr, hop_length=sig.hop, n_fft=2048, n_mels=128, fmax=11025)
    S_db = librosa.power_to_db(S, ref=np.max)
    env_full = librosa.onset.onset_strength(S=S_db, sr=sig.sr, hop_length=sig.hop, aggregate=np.median, max_size=3)
    env_perc = librosa.onset.onset_strength(y=sig.percussive, sr=sig.sr, hop_length=sig.hop, max_size=3)
    mel_f = librosa.mel_frequencies(n_mels=128, fmax=11025)
    low_bins = max(2, int(np.sum(mel_f < 160)))
    env_low = librosa.onset.onset_strength(S=S_db[:low_bins], sr=sig.sr, hop_length=sig.hop, aggregate=np.mean)
    n = min(len(env_full), len(env_perc), len(env_low))
    env = 0.5 * _norm(env_full[:n]) + 0.5 * _norm(env_perc[:n])
    return env, _norm(env_low[:n]), S_db


def _ioi_estimate(onset_times: np.ndarray) -> float | None:
    if len(onset_times) < 8:
        return None
    bins = np.arange(np.log2(BPM_MIN), np.log2(BPM_MAX), 1 / 48)
    hist = np.zeros(len(bins))
    for k in range(1, 7):
        d = onset_times[k:] - onset_times[:-k]
        d = d[(d > 60 / BPM_MAX) & (d < 60 / BPM_MIN)]
        if len(d):
            idx = np.clip(np.searchsorted(bins, np.log2(60.0 / d)), 0, len(bins) - 1)
            np.add.at(hist, idx, 1.0 / k)
    hist = gaussian_filter1d(hist, 1.5)
    if hist.max() <= 0:
        return None
    w = np.array([prior(2**b) for b in bins])
    return float(2 ** bins[np.argmax(hist * w)])


def _beat_windows(beat_times: np.ndarray, size: int = 16, hop: int = 8) -> list[tuple[float, float, float]]:
    """Least-squares tempo per window of beats: (centre time, bpm, jitter fraction)."""
    out = []
    for s in range(0, max(0, len(beat_times) - size) + 1, hop):
        t = beat_times[s : s + size]
        if len(t) < 6:
            continue
        idx = np.arange(len(t))
        slope, intercept = np.polyfit(idx, t, 1)
        if slope <= 0:
            continue
        resid = t - (slope * idx + intercept)
        out.append((float(t.mean()), 60.0 / slope, float(np.sqrt(np.mean(resid**2)) / slope)))
    return out


def analyze_tempo(sig: AudioSignal) -> tuple[dict, dict, RhythmInternals]:
    env, low_env, mel_db = onset_envelopes(sig)
    fr = sig.sr / sig.hop
    duration = sig.duration
    sal = Salience(env, fr)

    onset_frames = librosa.onset.onset_detect(onset_envelope=env, sr=sig.sr, hop_length=sig.hop, backtrack=False)
    onset_times = librosa.frames_to_time(onset_frames, sr=sig.sr, hop_length=sig.hop)

    # --- independent estimates -------------------------------------------------
    estimates: dict[str, float | None] = {}
    ac_peaks = sal.peaks(sal.ac_grid)
    ft_peaks = sal.peaks(sal.ft_grid)
    estimates["autocorrelation"] = ac_peaks[0] if ac_peaks else None
    estimates["fourier"] = ft_peaks[0] if ft_peaks else None
    try:
        estimates["tempogram_prior"] = float(
            np.atleast_1d(librosa.feature.tempo(onset_envelope=env, sr=sig.sr, hop_length=sig.hop))[0]
        )
    except Exception:
        estimates["tempogram_prior"] = None
    _, dp_beats = librosa.beat.beat_track(onset_envelope=env, sr=sig.sr, hop_length=sig.hop, units="time")
    estimates["beat_tracker"] = float(60.0 / np.median(np.diff(dp_beats))) if len(dp_beats) > 4 else None
    estimates["inter_onset"] = _ioi_estimate(onset_times)
    valid = {k: v for k, v in estimates.items() if v and BPM_MIN <= v <= BPM_MAX}

    if not valid or env.std() < 1e-6:
        return _no_tempo(env, fr, onset_times, duration, low_env, mel_db)

    # --- candidate scoring -----------------------------------------------------
    candidates: list[float] = []
    for v in list(valid.values()) + ac_peaks[1:] + ft_peaks[1:]:
        for r in (1.0, 0.5, 2.0, 2 / 3, 1.5):
            c = v * r
            if 50 <= c <= 220 and not any(abs(c / x - 1) < 0.02 for x in candidates):
                candidates.append(c)

    def support(c: float) -> float:
        total = 0.0
        for v in valid.values():
            ratio = v / c
            if abs(ratio - 1) < 0.03:
                total += 1.0
            elif abs(ratio - 2) < 0.06 or abs(ratio - 0.5) < 0.015:
                total += 0.3
        return total / len(estimates)

    s_max = sal.s_grid[(sal.grid >= 40) & (sal.grid <= 240)].max() + 1e-12
    scored = sorted(
        ((0.5 * sal(c) / s_max + 0.5 * support(c)) * prior(c) ** 0.8, c) for c in candidates
    )[::-1]
    bpm0 = scored[0][1]

    # --- beat tracking at the chosen tempo --------------------------------------
    _, beat_frames = librosa.beat.beat_track(
        onset_envelope=env, sr=sig.sr, hop_length=sig.hop, bpm=bpm0, tightness=120, units="frames"
    )
    beat_times = librosa.frames_to_time(beat_frames, sr=sig.sr, hop_length=sig.hop)
    windows = _beat_windows(beat_times)
    if windows:
        bpm = float(np.median([w[1] for w in windows]))
        if abs(bpm / bpm0 - 1) > 0.04:
            bpm = bpm0
    else:
        bpm = bpm0

    # --- confidence ------------------------------------------------------------
    ibis = np.diff(beat_times)
    consistency = float(np.mean(np.abs(ibis / np.median(ibis) - 1) < 0.06)) if len(ibis) > 3 else 0.0
    grid_mask = (sal.grid >= 40) & (sal.grid <= 240)
    s_med = float(np.median(sal.s_grid[grid_mask]))
    clarity = clamp01((sal(bpm) - s_med) / (s_max - s_med + 1e-12))
    agreement = clamp01(support(bpm) * len(estimates) / max(1, len(valid)))
    pulse = clamp01(float(sal.ac_at(bpm)) / 0.15)
    conf = (0.35 * agreement + 0.3 * clarity + 0.35 * consistency) * (0.6 + 0.4 * pulse)
    if len(beat_times) < 8:
        conf *= 0.5

    # --- alternative metrical interpretation -----------------------------------
    alternatives = []
    for ratio, label in ((0.5, "half-time"), (2.0, "double-time")):
        alt = bpm * ratio
        if BPM_MIN <= alt <= BPM_MAX:
            alternatives.append({"bpm": round(alt, 1), "relation": label, "salience": round(sal(alt) / s_max, 3),
                                 "plausibility": round((sal(alt) / s_max) * prior(alt), 3)})
    alternatives.sort(key=lambda a: a["plausibility"], reverse=True)
    main_plaus = (sal(bpm) / s_max) * prior(bpm)
    octave_ambiguous = bool(alternatives and alternatives[0]["plausibility"] > 0.8 * main_plaus)

    # --- stability & local tempo -----------------------------------------------
    stability, drift, jitter = _stability(windows)
    sections = _tempo_sections(env, sig, bpm, duration)
    tempo_varies = False
    if len(sections) > 1 and (conf < 0.5 or len(sections) > 6):
        # many short "sections" or an unreliable pulse means no clear tempo map, not real tempo changes
        tempo_varies = len(sections) > 6
        sections = [{"start": 0.0, "end": round(duration, 2), "bpm": round(bpm, 1)}]
    curve_t = [round(w[0], 2) for w in windows]
    curve_b = [round(w[1], 2) for w in windows]

    msg = None
    if octave_ambiguous:
        msg = f"Half/double-time interpretation ({alternatives[0]['bpm']:g} BPM) is similarly plausible."
    tempo_block = annotate(
        {
            "available": True,
            "bpm": round(bpm, 1),
            "bpm_rounded": int(round(bpm)),
            "category": tempo_category(bpm),
            "alternatives": alternatives,
            "alternative_bpm": alternatives[0]["bpm"] if alternatives else None,
            "alternative_relation": alternatives[0]["relation"] if alternatives else None,
            "octave_ambiguous": octave_ambiguous,
            "estimates": {k: (round(v, 1) if v else None) for k, v in estimates.items()},
            "stability": round(stability, 3) if stability is not None else None,
            "drift_percent": round(drift * 100, 2) if drift is not None else None,
            "timing_jitter_ms": round(jitter * 60000 / bpm, 1) if jitter is not None else None,
            "sections": sections,
            "has_tempo_changes": len(sections) > 1,
            "tempo_varies": tempo_varies,
            "curve": {"times": curve_t, "bpm": curve_b},
            "components": {"agreement": round(agreement, 3), "clarity": round(clarity, 3),
                           "beat_consistency": round(consistency, 3), "pulse_strength": round(pulse, 3)},
        },
        conf,
        "estimated",
        msg,
    )

    rhythm_block = _rhythm_block(env, fr, beat_frames, beat_times, onset_times, duration, bpm, stability, sig)
    internals = RhythmInternals(
        onset_env=env, low_env=low_env, frame_rate=fr, beat_frames=beat_frames, beat_times=beat_times,
        bpm=bpm, confidence=tempo_block["confidence"], onset_times=onset_times, mel_db=mel_db,
    )
    return tempo_block, rhythm_block, internals


def extended_beat_frames(rhythm: RhythmInternals, n_frames: int) -> np.ndarray:
    """Beat frames extrapolated over the intro/outro and across gaps the tracker left empty.

    The tracker trims weak beats (e.g. a drumless intro); harmonic and structural analysis
    still need a musically aligned grid there.
    """
    b = np.asarray(rhythm.beat_frames, dtype=float)
    if len(b) < 4:
        return b.astype(int)
    period = float(np.median(np.diff(b)))
    filled = [b[0]]
    for nxt in b[1:]:
        gap = nxt - filled[-1]
        k = int(round(gap / period))
        if k >= 2:
            filled.extend(filled[-1] + gap * np.arange(1, k) / k)
        filled.append(nxt)
    head = np.arange(b[0] - period, 0, -period)[::-1]
    tail = np.arange(b[-1] + period, n_frames, period)
    out = np.concatenate([head, filled, tail])
    return np.unique(np.clip(np.round(out), 0, n_frames - 1).astype(int))


def _stability(windows) -> tuple[float | None, float | None, float | None]:
    if len(windows) < 2:
        return None, None, None
    bpms = np.array([w[1] for w in windows])
    jit = float(np.median([w[2] for w in windows]))
    drift = float(np.std(bpms) / np.median(bpms))
    stability = clamp01(1.0 - (max(0.0, jit - 0.015) * 8.0 + drift * 5.0))
    return stability, drift, jit


def _tempo_sections(env: np.ndarray, sig: AudioSignal, bpm: float, duration: float) -> list[dict]:
    """Sustained local-tempo regions from a windowed autocorrelation tempogram."""
    win_s, hop_s = 12.0, 4.0
    if duration < win_s * 2:
        return [{"start": 0.0, "end": round(duration, 2), "bpm": round(bpm, 1)}]
    tg = librosa.feature.tempogram(onset_envelope=env, sr=sig.sr, hop_length=sig.hop, win_length=512)
    lags = np.arange(tg.shape[0])
    fr = sig.sr / sig.hop
    local = []
    for start in np.arange(0, duration - win_s + 1e-6, hop_s):
        a, b = int(start * fr), int((start + win_s) * fr)
        prof = tg[:, a:b].mean(axis=1)
        lo_lag, hi_lag = fr * 60 / (bpm * 1.3), fr * 60 / (bpm / 1.3)
        mask = (lags >= lo_lag) & (lags <= hi_lag)
        if not mask.any():
            continue
        k = lags[mask][np.argmax(prof[mask])]
        if 0 < k < len(prof) - 1:
            den = prof[k - 1] - 2 * prof[k] + prof[k + 1]
            k = k + (0.5 * (prof[k - 1] - prof[k + 1]) / den if den != 0 else 0)
        local.append((start, fr * 60 / k if k > 0 else bpm, float(prof[mask].max())))
    if not local:
        return [{"start": 0.0, "end": round(duration, 2), "bpm": round(bpm, 1)}]
    vals = np.array([x[1] for x in local])
    from scipy.ndimage import median_filter

    vals = median_filter(vals, size=5, mode="nearest")
    segs: list[list] = []
    for (start, _, _), v in zip(local, vals):
        if segs and abs(v / np.median(segs[-1][2]) - 1) < 0.06:
            segs[-1][1] = start + win_s
            segs[-1][2].append(v)
        else:
            segs.append([start, start + win_s, [v]])
    # absorb short segments (< 20 s) into their neighbour
    merged: list[list] = []
    for s in segs:
        if merged and (s[1] - s[0] < 20 or merged[-1][1] - merged[-1][0] < 20):
            merged[-1][1] = s[1]
            merged[-1][2].extend(s[2])
        else:
            merged.append(s)
    out = []
    for i, (a, b, v) in enumerate(merged):
        out.append({"start": round(0.0 if i == 0 else float(a), 2),
                    "end": round(duration if i == len(merged) - 1 else float(merged[i + 1][0]), 2),
                    "bpm": round(float(np.median(v)), 1)})
    # only report changes that are musically meaningful (> 6%)
    if len(out) > 1 and max(o["bpm"] for o in out) / min(o["bpm"] for o in out) < 1.06:
        return [{"start": 0.0, "end": round(duration, 2), "bpm": round(bpm, 1)}]
    return out


def _rhythm_block(env, fr, beat_frames, beat_times, onset_times, duration, bpm, stability, sig) -> dict:
    rms = librosa.feature.rms(y=sig.mono, hop_length=sig.hop)[0]
    active = float(np.sum(rms > (rms.max() * 10 ** (-40 / 20)))) / fr if rms.size else duration
    active = max(active, 1.0)
    strengths = env[np.clip(beat_frames, 0, len(env) - 1)] if len(beat_frames) else np.array([])

    positions = {"on_beat": 0.0, "eighth_offbeat": 0.0, "sixteenth": 0.0}
    if len(beat_times) > 2 and len(onset_times):
        idx = np.searchsorted(beat_times, onset_times) - 1
        ok = (idx >= 0) & (idx < len(beat_times) - 1)
        o = onset_times[ok]
        i = idx[ok]
        phase = (o - beat_times[i]) / (beat_times[i + 1] - beat_times[i])
        w = env[np.clip(librosa.time_to_frames(o, sr=sig.sr, hop_length=sig.hop), 0, len(env) - 1)]
        on = (phase < 0.125) | (phase > 0.875)
        eighth = np.abs(phase - 0.5) < 0.125
        tot = w.sum() + 1e-12
        positions = {"on_beat": float(w[on].sum() / tot), "eighth_offbeat": float(w[eighth].sum() / tot),
                     "sixteenth": float(w[~on & ~eighth].sum() / tot)}

    return {
        "available": True,
        "beats": [round(float(t), 3) for t in beat_times],
        "beat_strengths": [round(float(s), 3) for s in _norm(strengths)] if len(strengths) else [],
        "beat_count": int(len(beat_times)),
        "beat_interval_s": round(float(np.median(np.diff(beat_times))), 4) if len(beat_times) > 1 else None,
        "tempo_stability": round(stability, 3) if stability is not None else None,
        "onset_count": int(len(onset_times)),
        "onset_density": round(len(onset_times) / active, 2),
        "rhythm_density": round(len(onset_times) / max(1, len(beat_times)), 2),
        "syncopation": round(positions["eighth_offbeat"] + positions["sixteenth"], 3),
        "onset_positions": {k: round(v, 3) for k, v in positions.items()},
        "onsets": [round(float(t), 3) for t in onset_times[:6000]],
        "downbeats": [],
    }


def _no_tempo(env, fr, onset_times, duration, low_env, mel_db):
    tempo_block = annotate(
        {"available": True, "bpm": None, "bpm_rounded": None, "category": None, "alternatives": [],
         "alternative_bpm": None, "alternative_relation": None, "octave_ambiguous": False, "estimates": {},
         "stability": None, "sections": [], "has_tempo_changes": False, "curve": {"times": [], "bpm": []}},
        0.0, "estimated", "No reliable rhythmic pulse detected.",
    )
    rhythm_block = {"available": False, "beats": [], "beat_strengths": [], "beat_count": 0, "downbeats": [],
                    "onsets": [round(float(t), 3) for t in onset_times[:6000]],
                    "onset_density": round(len(onset_times) / max(duration, 1), 2),
                    "message": "No reliable beat grid could be established."}
    internals = RhythmInternals(onset_env=env, low_env=low_env, frame_rate=fr, beat_frames=np.array([], int),
                                beat_times=np.array([]), bpm=None, confidence=0.0, onset_times=onset_times,
                                mel_db=mel_db)
    return tempo_block, rhythm_block, internals
