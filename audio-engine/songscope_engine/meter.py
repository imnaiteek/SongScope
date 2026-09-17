"""Meter (time signature) estimation and downbeat tracking.

Rather than assuming 4/4, each candidate bar length B (2..7 beats) and phase is scored by how
strongly beat-level accents distinguish "bar starts" from other beats. Accents combine:
  * harmonic change (chord and bass-note changes cluster at bar lines)
  * low-frequency onsets (kick drum)
  * overall onset strength
The beat subdivision (duple vs triple) is measured separately from onset periodicity to
separate simple meters (3/4) from compound ones (6/8, 12/8). Confidence reflects the
effect size, the margin over competing meters and consistency between song halves. Low
confidence results are reported as undetermined rather than as facts.
"""

from __future__ import annotations

import librosa
import numpy as np

from .confidence import annotate, clamp01
from .features import HarmonicFeatures, unit_columns
from .tempo import RhythmInternals

CANDIDATES = (2, 3, 4, 5, 6, 7)
RELIABLE_THRESHOLD = 0.5


def _z(x: np.ndarray) -> np.ndarray:
    s = x.std()
    return (x - x.mean()) / s if s > 1e-9 else np.zeros_like(x)


def _local_max(env: np.ndarray, frames: np.ndarray, radius: int) -> np.ndarray:
    out = np.empty(len(frames))
    for i, f in enumerate(frames):
        a, b = max(0, f - radius), min(len(env), f + radius + 1)
        out[i] = env[a:b].max() if b > a else 0.0
    return out


def beat_accents(rhythm: RhythmInternals, harm: HarmonicFeatures) -> dict[str, np.ndarray]:
    beats = rhythm.beat_frames
    r = max(1, int(0.07 * rhythm.frame_rate))
    onset = _local_max(rhythm.onset_env, beats, r)
    low = _local_max(rhythm.low_env, beats, r)
    T = harm.chroma.shape[1]
    b = np.clip(beats, 0, T - 1)
    ch = unit_columns(librosa.util.sync(harm.chroma, b, aggregate=np.median))
    bs = unit_columns(librosa.util.sync(harm.chroma_bass, b, aggregate=np.median))
    # sync segment k+1 starts at beat k; change at beat k compares with the previous segment
    chord_change = 1.0 - np.sum(ch[:, 1:] * ch[:, :-1], axis=0)
    bass_change = 1.0 - np.sum(bs[:, 1:] * bs[:, :-1], axis=0)
    n = len(beats)
    harm_change = (0.5 * chord_change + 0.5 * bass_change)[:n]
    return {"onset": _z(onset), "low": _z(low), "harmonic": _z(harm_change)}


def _cohen_d(x: np.ndarray, B: int, p: int) -> float:
    idx = np.arange(len(x)) % B == p
    a, b = x[idx], x[~idx]
    if len(a) < 3 or len(b) < 3:
        return 0.0
    pooled = np.sqrt((a.var() * (len(a) - 1) + b.var() * (len(b) - 1)) / (len(a) + len(b) - 2))
    return float((a.mean() - b.mean()) / pooled) if pooled > 1e-9 else 0.0


def _score(acc: np.ndarray) -> dict[int, tuple[float, int]]:
    out = {}
    for B in CANDIDATES:
        best = max(((_cohen_d(acc, B, p), p) for p in range(B)), key=lambda t: t[0])
        out[B] = best
    return out


def _decide(scores: dict[int, tuple[float, int]], harm_scores: dict[int, tuple[float, int]]) -> tuple[int, str]:
    d = {B: max(0.0, s[0]) for B, s in scores.items()}
    families = {
        "duple": max(d[2], d[4]),
        "triple": d[3],
        "five": d[5] * 0.8,  # irregular meters need clearly stronger evidence
        "seven": d[7] * 0.8,
    }
    family = max(families, key=families.get)
    if family == "duple":
        hd = {B: max(0.0, harm_scores[B][0]) for B in (2, 4)}
        B = 2 if (d[2] > 1.25 * d[4] and hd[2] > 1.25 * hd[4]) else 4
    elif family == "triple":
        B = 6 if d[6] > 1.25 * d[3] else 3
    elif family == "five":
        B = 5
    else:
        B = 7
    return B, family


def _subdivision(rhythm: RhythmInternals, bpm: float) -> tuple[str, float]:
    env = rhythm.onset_env - rhythm.onset_env.mean()
    P = rhythm.frame_rate * 60.0 / bpm
    ac = librosa.autocorrelate(env, max_size=int(P * 1.5) + 3)
    ac = ac / ac[0] if ac[0] > 0 else ac

    def at(lag: float) -> float:
        k = int(round(lag))
        lo, hi = max(1, k - 1), min(len(ac) - 1, k + 1)
        return float(ac[lo : hi + 1].max())

    duple = at(P / 2)
    triple = 0.5 * (at(P / 3) + at(2 * P / 3))
    diff = triple - duple
    return ("triple" if diff > 0.04 else "duple"), clamp01(abs(diff) / 0.2)


def _signature(B: int, subdivision: str, bpm: float) -> tuple[str, str]:
    """Return (signature, beat unit description)."""
    if B in (2, 4):
        if subdivision == "triple":
            return ("6/8" if B == 2 else "12/8"), "dotted quarter"
        return f"{B}/4", "quarter"
    if B == 3:
        return ("9/8", "dotted quarter") if subdivision == "triple" else ("3/4", "quarter")
    if B == 6:
        return "6/8", "eighth"
    if B == 5:
        return ("5/8", "eighth") if bpm > 200 else ("5/4", "quarter")
    return ("7/8", "eighth") if bpm > 140 else ("7/4", "quarter")


def _downbeat_viterbi(acc: np.ndarray, B: int) -> np.ndarray:
    """Bar-position HMM: returns bar position (0 = downbeat) for each beat."""
    n = len(acc)
    p_down = 1.0 / (1.0 + np.exp(-1.5 * (acc - 0.5)))
    logE = np.empty((n, B))
    logE[:, 0] = np.log(p_down + 1e-9)
    logE[:, 1:] = np.log(1 - p_down + 1e-9)[:, None]
    T = np.full((B, B), np.log(0.03 / max(1, B - 1)))
    for s in range(B):
        T[s, (s + 1) % B] = np.log(0.97)
    delta = logE[0] + np.log(1.0 / B)
    back = np.zeros((n, B), dtype=int)
    for i in range(1, n):
        cand = delta[:, None] + T
        back[i] = np.argmax(cand, axis=0)
        delta = cand[back[i], np.arange(B)] + logE[i]
    states = np.empty(n, dtype=int)
    states[-1] = int(np.argmax(delta))
    for i in range(n - 1, 0, -1):
        states[i - 1] = back[i, states[i]]
    return states


def analyze_meter(rhythm: RhythmInternals, harm: HarmonicFeatures) -> tuple[dict, list[float], dict]:
    n = len(rhythm.beat_frames)
    if rhythm.bpm is None or n < 16 or rhythm.confidence < 0.25:
        block = annotate(
            {"available": True, "signature": None, "reliable": False, "beats_per_bar": None, "candidates": [],
             "subdivision": None, "bars": 0},
            0.0, "estimated", "Meter could not be determined reliably (no stable beat grid).",
        )
        return block, [], {"beats_per_bar": None, "positions": None}

    feats = beat_accents(rhythm, harm)
    combined = 0.2 * feats["onset"] + 0.35 * feats["low"] + 0.45 * feats["harmonic"]
    scores = _score(combined)
    harm_scores = _score(feats["harmonic"])
    B, family = _decide(scores, harm_scores)
    subdivision, sub_conf = _subdivision(rhythm, rhythm.bpm)
    signature, beat_unit = _signature(B, subdivision, rhythm.bpm)

    # --- confidence ------------------------------------------------------------
    d_best = max(0.0, scores[B][0])
    related = {2: {2, 4}, 4: {2, 4}, 3: {3, 6}, 6: {3, 6}, 5: {5}, 7: {7}}[B]
    competitors = [max(0.0, scores[c][0]) for c in CANDIDATES if c not in related]
    d_comp = max(competitors) if competitors else 0.0
    evidence = clamp01(d_best / 1.5)
    margin = clamp01((d_best - d_comp) / (d_best + 1e-9))
    half = n // 2
    s1, s2 = _score(combined[:half]), _score(combined[half:])
    B1, f1 = _decide(s1, _score(feats["harmonic"][:half]))
    B2, f2 = _decide(s2, _score(feats["harmonic"][half:]))
    consistency = 1.0 if (B1 == B and B2 == B) else (0.6 if (f1 == family and f2 == family) else 0.0)
    conf = (0.4 * evidence + 0.35 * margin + 0.25 * consistency) * (0.5 + 0.5 * rhythm.confidence)
    if B in (2, 4) and subdivision == "triple" or B == 3:
        conf *= 0.75 + 0.25 * sub_conf  # simple-vs-compound ambiguity
    reliable = conf >= RELIABLE_THRESHOLD

    positions = _downbeat_viterbi(combined, B)
    downbeats = [round(float(rhythm.beat_times[i]), 3) for i in np.where(positions == 0)[0]]

    cand = []
    for c in CANDIDATES:
        sig_c, _ = _signature(c, subdivision, rhythm.bpm)
        cand.append({"beats_per_bar": c, "signature": sig_c, "score": round(max(0.0, scores[c][0]), 3)})
    cand.sort(key=lambda x: x["score"], reverse=True)

    msg = None if reliable else "Meter could not be determined reliably."
    if reliable and B in (2, 4) and subdivision == "duple" and abs(scores[2][0] - scores[4][0]) < 0.15:
        msg = "2/4 and 4/4 are hard to distinguish acoustically; the bar length may be notated either way."
    block = annotate(
        {
            "available": True,
            "signature": signature,
            "tendency": signature,
            "reliable": reliable,
            "beats_per_bar": B,
            "beat_unit": beat_unit,
            "subdivision": subdivision,
            "subdivision_confidence": round(sub_conf, 3),
            "candidates": cand,
            "bars": len(downbeats),
            "components": {"effect_size": round(d_best, 3), "margin": round(margin, 3),
                           "half_consistency": consistency,
                           "accent_weights": {"harmonic_change": 0.45, "low_onsets": 0.35, "onsets": 0.2}},
        },
        conf,
        "estimated",
        msg,
    )
    if not reliable:
        block["signature"] = None
    return block, downbeats, {"beats_per_bar": B, "positions": positions}
