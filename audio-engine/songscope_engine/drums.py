"""Estimated drum pattern (kick / snare / hi-hat) on the bar grid.

Band-limited spectral flux is computed on the percussive component (or a drum stem when
available). Hits are quantised onto a 16th-note grid anchored at detected downbeats, and a
per-slot hit probability across all bars yields the typical pattern. This is an *estimate*:
band overlap between instruments makes per-instrument attribution approximate.
"""

from __future__ import annotations

import librosa
import numpy as np

from .confidence import annotate, clamp01

INSTRUMENTS = {
    "kick": [(30, 120)],
    "snare": [(1500, 5000)],
    "hihat": [(7000, 11000)],
}
SLOTS_PER_BEAT = 4
SLOT_NAMES = ["", "e", "&", "a"]


def _band_flux(S_mag: np.ndarray, freqs: np.ndarray, ranges: list[tuple[float, float]]) -> np.ndarray:
    # flux on compressed magnitude (not dB) so quiet attacks don't look as strong as loud hits
    total = np.zeros(S_mag.shape[1])
    for lo, hi in ranges:
        m = (freqs >= lo) & (freqs < hi)
        if not m.any():
            continue
        band = S_mag[m]
        flux = np.maximum(0, np.diff(band, axis=1, prepend=band[:, :1])).sum(axis=0)
        total += flux / (np.percentile(flux, 99) + 1e-9)
    return total / len(ranges)


def _slot_label(slot: int) -> str:
    beat, sub = divmod(slot, SLOTS_PER_BEAT)
    return f"{beat + 1}{SLOT_NAMES[sub]}"


def _describe(name: str, prob: np.ndarray, bpb: int) -> str:
    hits = np.where(prob >= 0.5)[0]
    if len(hits) == 0:
        return "No consistent pattern"
    if name == "hihat" or len(hits) >= 2 * bpb:
        eighths = np.arange(0, bpb * SLOTS_PER_BEAT, 2)
        offs = np.arange(1, bpb * SLOTS_PER_BEAT, 2)
        quarters = np.arange(0, bpb * SLOTS_PER_BEAT, 4)
        on8 = np.mean(prob[eighths] >= 0.5)
        on16 = np.mean(prob[offs] >= 0.5)
        if on8 >= 0.75 and on16 >= 0.75:
            return "16th notes"
        if on8 >= 0.75:
            return "8th notes"
        and_slots = np.arange(2, bpb * SLOTS_PER_BEAT, 4)
        if np.mean(prob[and_slots] >= 0.5) >= 0.75 and np.mean(prob[quarters] >= 0.5) < 0.25:
            return "Off-beat 8ths"
        if np.mean(prob[quarters] >= 0.5) >= 0.75 and on8 < 0.75:
            return "Quarter notes"
    return ", ".join(_slot_label(int(s)) for s in hits)


def analyze_drums(y: np.ndarray, sr: int, beat_times: np.ndarray, downbeats: list[float], beats_per_bar: int | None,
                  meter_confidence: float, percussive_ratio: float, source: str = "mix") -> dict:
    if not beats_per_bar or len(downbeats) < 4 or len(beat_times) < 16:
        return annotate({"available": True, "instruments": {}, "bars_analyzed": 0, "estimated": True}, 0.0,
                        "inferred", "Drum pattern needs a reliable beat and bar grid.")
    hop = 256
    S = np.abs(librosa.stft(y, n_fft=1024, hop_length=hop))
    S_mag = np.sqrt(S / (S.max() + 1e-12))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=1024)
    fr = sr / hop
    envs = {k: _band_flux(S_mag, freqs, v) for k, v in INSTRUMENTS.items()}

    bpb = int(beats_per_bar)
    n_slots = bpb * SLOTS_PER_BEAT
    db = np.asarray(downbeats)
    bars = []
    for a, b in zip(db[:-1], db[1:]):
        inside = beat_times[(beat_times >= a - 0.02) & (beat_times < b - 0.02)]
        if len(inside) != bpb:
            continue  # skip irregular bars (tracking errors, fills)
        bars.append((a, b))
    if len(bars) < 4:
        return annotate({"available": True, "instruments": {}, "bars_analyzed": len(bars), "estimated": True}, 0.1,
                        "inferred", "Too few regular bars to estimate a drum pattern.")

    result = {}
    consistencies = []
    for name, env in envs.items():
        thresh = max(0.25, float(np.percentile(env, 90)) * 0.9)
        strength = np.zeros((len(bars), n_slots))
        for bi, (a, b) in enumerate(bars):
            slot_dur = (b - a) / n_slots
            for s in range(n_slots):
                t = a + s * slot_dur
                lo = int(max(0, (t - slot_dur * 0.4) * fr))
                hi = int(min(len(env), (t + slot_dur * 0.4) * fr + 1))
                if hi > lo:
                    strength[bi, s] = float(env[lo:hi].max())
        # a hit must be absolutely strong and strong relative to that bar's loudest hit, which
        # separates e.g. a kick drum from the attacks of a bass line in the same band
        bar_max = strength.max(axis=1, keepdims=True)
        hits = ((strength >= thresh) & (strength >= 0.55 * bar_max)).astype(float)
        prob = hits.mean(axis=0)
        activity = float(hits.mean())
        consistency = float(np.mean(np.abs(2 * prob - 1)))
        present = activity >= 0.03
        if present:
            consistencies.append(consistency)
        result[name] = {
            "present": bool(present),
            "pattern": _describe(name, prob, bpb) if present else "Not detected",
            "slot_probabilities": [round(float(p), 3) for p in prob],
            "consistency": round(consistency, 3),
        }

    drum_presence = clamp01((percussive_ratio - 0.05) / 0.25) if source == "mix" else 1.0
    base = float(np.mean(consistencies)) if consistencies else 0.0
    conf = base * (0.5 + 0.5 * clamp01(meter_confidence)) * (0.4 + 0.6 * drum_presence) * (0.8 if source == "mix" else 1.0)
    msg = "Estimated pattern — band overlap between drums makes attribution approximate."
    if not consistencies:
        msg = "No clear drum track detected."
    block = {
        "available": True,
        "estimated": True,
        "source": source,
        "beats_per_bar": bpb,
        "slots_per_beat": SLOTS_PER_BEAT,
        "slot_labels": [_slot_label(s) for s in range(n_slots)],
        "bars_analyzed": len(bars),
        "instruments": result,
    }
    return annotate(block, conf, "inferred", msg)
