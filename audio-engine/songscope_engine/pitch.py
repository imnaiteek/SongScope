"""Predominant pitch tracking (pYIN) with reliability safeguards.

On a full mix the tracker follows the most prominent harmonic source, so the harmonic
component is high-pass filtered to reduce bass dominance, and frames dominated by percussion
or with low voicing probability are rejected. When a vocal stem is supplied it is used
directly, which is far more reliable for melody.
"""

from __future__ import annotations

import librosa
import numpy as np
from scipy.signal import butter, sosfiltfilt

from .confidence import annotate, clamp01
from .theory import describe_interval, hz_to_midi, midi_to_hz, midi_to_note, pc_name

PITCH_SR = 16000
HOP = 320  # 20 ms


def track_pitch(y: np.ndarray, sr: int, fmin: float, fmax: float, highpass: float | None,
                percussive: np.ndarray | None = None) -> dict:
    y16 = librosa.resample(y, orig_sr=sr, target_sr=PITCH_SR, res_type="soxr_hq")
    if highpass:
        sos = butter(4, highpass, btype="high", fs=PITCH_SR, output="sos")
        y16 = sosfiltfilt(sos, y16).astype(np.float32)
    f0, voiced, prob = librosa.pyin(y16, fmin=fmin, fmax=fmax, sr=PITCH_SR, frame_length=1024, hop_length=HOP,
                                    resolution=0.2, center=True)
    times = librosa.times_like(f0, sr=PITCH_SR, hop_length=HOP)
    rms = librosa.feature.rms(y=y16, frame_length=1024, hop_length=HOP, center=True)[0][: len(f0)]
    audible = rms > (np.max(rms) * 10 ** (-45 / 20) if rms.size else 0)
    perc_frames = np.zeros(len(f0), dtype=bool)
    if percussive is not None:
        p16 = librosa.resample(percussive, orig_sr=sr, target_sr=PITCH_SR, res_type="soxr_hq")
        prms = librosa.feature.rms(y=p16, frame_length=1024, hop_length=HOP, center=True)[0][: len(f0)]
        hrms = rms[: len(prms)]
        perc_frames[: len(prms)] = prms > 1.5 * (hrms + 1e-9)
    reliable = voiced & (prob >= 0.6) & np.isfinite(f0) & audible & ~perc_frames
    return {"times": times, "f0": f0, "prob": prob, "reliable": reliable, "audible": audible,
            "perc_fraction": float(np.mean(perc_frames[audible])) if audible.any() else 0.0}


def track_predominant(y: np.ndarray, sr: int, fmin: float, fmax: float,
                      percussive: np.ndarray | None = None, hop: int = 512) -> dict:
    """Predominant-melody tracking for polyphonic mixes (Melodia-style, simplified).

    Harmonic summation over a 20-cent constant-Q spectrum gives a pitch salience function;
    a two-layer (voiced/unvoiced) HMM with local pitch transitions decodes a continuous
    contour. Salience is mildly biased toward the upper register where melodies usually sit.
    """
    bpo, n_harm, alpha = 60, 8, 0.8
    n_f0 = int(np.ceil(bpo * np.log2(fmax / fmin))) + 1
    n_bins = n_f0 + int(np.ceil(bpo * np.log2(n_harm))) + 1
    nyq_bins = int(np.floor(bpo * np.log2((sr / 2 * 0.95) / fmin)))
    n_bins = min(n_bins, nyq_bins)
    C = np.abs(librosa.cqt(y, sr=sr, hop_length=hop, fmin=fmin, n_bins=n_bins, bins_per_octave=bpo))
    M = (C / (C.max() + 1e-12)) ** 0.6  # mild compression keeps level differences meaningful
    S = np.zeros((n_f0, M.shape[1]))
    for h in range(1, n_harm + 1):
        shift = int(round(bpo * np.log2(h)))
        if shift >= n_bins:
            break
        width = min(n_f0, n_bins - shift)
        S[:width] += alpha ** (h - 1) * M[shift : shift + width]
    freqs = fmin * 2 ** (np.arange(n_f0) / bpo)
    # require energy at the fundamental itself: suppresses candidates that only collect
    # upper partials of lower (bass / pad) notes
    fundamental = M[:n_f0] / (M[:n_f0].max(axis=0, keepdims=True) + 1e-12)
    S *= np.sqrt(fundamental)
    S *= (1.0 + 0.35 * np.log2(freqs / fmin) / np.log2(fmax / fmin))[:, None]

    peak = S.max(axis=0)
    ratio = peak / (np.median(S, axis=0) + 1e-9)
    energy = M.sum(axis=0)
    audible = energy > np.percentile(energy, 95) * 0.05
    p_voiced = 1.0 / (1.0 + np.exp(-4.0 * (ratio - 1.8))) * audible

    Sn = S / (S.sum(axis=0, keepdims=True) + 1e-12)
    sharp = Sn**4
    sharp = sharp / (sharp.sum(axis=0, keepdims=True) + 1e-12)
    prob = np.vstack([sharp * p_voiced, np.tile((1 - p_voiced) / n_f0, (n_f0, 1))])
    # mostly small moves (vibrato, glides) but allow note leaps of up to an octave per frame
    narrow = librosa.sequence.transition_local(n_f0, width=2 * bpo // 12 + 1, window="triangle", wrap=False)
    wide = librosa.sequence.transition_local(n_f0, width=2 * bpo + 1, window="ones", wrap=False)
    local = 0.85 * narrow + 0.15 * wide
    switch = np.array([[0.99, 0.01], [0.01, 0.99]])
    trans = np.kron(switch, local)
    states = librosa.sequence.viterbi(prob, trans)
    voiced = states < n_f0
    idx = np.where(voiced, states, states - n_f0)
    f0 = freqs[idx].astype(float)
    # parabolic refinement on salience
    cols = np.arange(S.shape[1])
    i0 = np.clip(idx, 1, n_f0 - 2)
    a, b, c = S[i0 - 1, cols], S[i0, cols], S[i0 + 1, cols]
    den = a - 2 * b + c
    delta = np.where(np.abs(den) > 1e-9, 0.5 * (a - c) / den, 0.0)
    f0 = f0 * 2 ** (np.clip(delta, -0.5, 0.5) / bpo)
    f0[~voiced] = np.nan

    times = librosa.times_like(f0, sr=sr, hop_length=hop)
    perc_frames = np.zeros(len(f0), dtype=bool)
    if percussive is not None:
        prms = librosa.feature.rms(y=percussive, hop_length=hop)[0][: len(f0)]
        hrms = librosa.feature.rms(y=y, hop_length=hop)[0][: len(prms)]
        perc_frames[: len(prms)] = prms > 1.5 * (hrms + 1e-9)
    conf = p_voiced
    reliable = voiced & (conf >= 0.5) & ~perc_frames & audible
    return {"times": times, "f0": f0, "prob": conf, "reliable": reliable, "audible": audible,
            "perc_fraction": float(np.mean(perc_frames[audible])) if audible.any() else 0.0}


def analyze_pitch(y: np.ndarray, sr: int, source: str = "mix", percussive: np.ndarray | None = None,
                  flats: bool = False) -> dict:
    if source == "vocals":
        tr = track_pitch(y, sr, fmin=librosa.note_to_hz("E2"), fmax=librosa.note_to_hz("C6"), highpass=70)
    elif source == "bass":
        tr = track_pitch(y, sr, fmin=librosa.note_to_hz("B0"), fmax=librosa.note_to_hz("G3"), highpass=None)
    else:
        tr = track_predominant(y, sr, fmin=librosa.note_to_hz("C3"), fmax=librosa.note_to_hz("C6"),
                               percussive=percussive)
    times, f0, prob, ok = tr["times"], tr["f0"], tr["prob"], tr["reliable"]
    audible_n = max(1, int(tr["audible"].sum()))
    voiced_fraction = float(ok.sum()) / audible_n

    if ok.sum() < 25:
        msg = "Pitch tracking was unreliable"
        msg += " due to percussion-heavy audio." if tr["perc_fraction"] > 0.4 else " — no stable melodic pitch found."
        block = {"available": True, "source": source, "voiced_fraction": round(voiced_fraction, 3),
                 "lowest_note": None, "highest_note": None, "contour": {"times": [], "hz": [], "midi": []},
                 "events": []}
        return annotate(block, 0.1, "estimated", msg)

    midi = hz_to_midi(f0[ok])
    lo, hi = np.percentile(midi, 2), np.percentile(midi, 98)
    med = float(np.median(midi))
    rounded = np.round(midi).astype(int)
    hist = np.bincount(rounded, weights=prob[ok], minlength=128)
    mode_midi = int(np.argmax(hist))
    pc_hist = np.zeros(12)
    for m, w in zip(rounded, prob[ok]):
        pc_hist[m % 12] += w
    jumps = np.abs(np.diff(hz_to_midi(f0[ok])))
    consecutive = np.diff(np.where(ok)[0]) == 1
    jump_rate = float(np.mean(jumps[consecutive] >= 11)) if consecutive.any() else 0.0

    source_factor = {"vocals": 1.0, "bass": 0.95, "mix": 0.7}.get(source, 0.7)
    conf = float(np.mean(prob[ok])) * (1 - min(0.6, jump_rate * 5)) * source_factor * (0.5 + 0.5 * clamp01(voiced_fraction / 0.3))

    # contour (<= 3000 points), unvoiced frames as null
    step = max(1, int(np.ceil(len(times) / 3000)))
    c_t, c_hz, c_m = [], [], []
    for i in range(0, len(times), step):
        c_t.append(round(float(times[i]), 3))
        if ok[i]:
            c_hz.append(round(float(f0[i]), 2))
            c_m.append(round(float(hz_to_midi(f0[i])), 2))
        else:
            c_hz.append(None)
            c_m.append(None)

    events = _note_events(times, f0, ok, flats)
    low_note, high_note = int(round(lo)), int(round(hi))
    msg = None
    if source == "mix":
        msg = ("Pitch on a full mix follows the most prominent harmonic source (often the lead vocal or lead "
               "instrument). Separate stems for a more reliable melody.")
    if tr["perc_fraction"] > 0.5:
        msg = "Pitch tracking may be unreliable due to percussion-heavy audio."
    block = {
        "available": True,
        "source": source,
        "voiced_fraction": round(voiced_fraction, 3),
        "fundamental_hz_median": round(float(midi_to_hz(med)), 2),
        "average_note": midi_to_note(med, flats),
        "average_hz": round(float(np.mean(f0[ok])), 2),
        "lowest_note": midi_to_note(low_note, flats),
        "lowest_hz": round(float(midi_to_hz(lo)), 2),
        "highest_note": midi_to_note(high_note, flats),
        "highest_hz": round(float(midi_to_hz(hi)), 2),
        "range_semitones": int(high_note - low_note),
        "range_description": describe_interval(high_note - low_note),
        "most_frequent_note": midi_to_note(mode_midi, flats),
        "most_frequent_pitch_class": pc_name(int(np.argmax(pc_hist)), flats),
        "pitch_class_histogram": {pc_name(i, flats): round(float(pc_hist[i] / (pc_hist.max() + 1e-12)), 3) for i in range(12)},
        "octave_jump_rate": round(jump_rate, 4),
        "contour": {"times": c_t, "hz": c_hz, "midi": c_m},
        "events": events,
    }
    return annotate(block, conf, "estimated", msg)


def _note_events(times, f0, ok, flats, min_dur=0.12, max_events=1500) -> list[dict]:
    events = []
    cur = None
    for t, f, good in zip(times, f0, ok):
        m = int(round(float(hz_to_midi(f)))) if good else None
        if cur and m is not None and m == cur["midi"] and t - cur["end"] <= 0.06:
            cur["end"] = float(t)
            cur["hz"].append(float(f))
            continue
        if cur and cur["end"] - cur["start"] >= min_dur:
            events.append(cur)
        cur = {"start": float(t), "end": float(t), "midi": m, "hz": [float(f)]} if m is not None else None
    if cur and cur["end"] - cur["start"] >= min_dur:
        events.append(cur)
    out = [{"start": round(e["start"], 3), "end": round(e["end"] + 0.02, 3), "midi": e["midi"],
            "note": midi_to_note(e["midi"], flats), "hz": round(float(np.median(e["hz"])), 2)} for e in events]
    return out[:max_events]
