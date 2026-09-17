"""Chord recognition: beat-synchronous chroma + bass chroma, template matching, HMM smoothing.

Pass 1 decodes a conservative major/minor/no-chord vocabulary with Viterbi and computes
per-segment posteriors via forward-backward. Pass 2 only upgrades a segment to an extended or
altered chord (7, maj7, m7, sus2, sus4, dim, aug) when the characteristic tone is clearly
present and the richer template fits significantly better. Accuracy over complexity:
a plain "C" is preferred over an unsupported "Cmaj7".
"""

from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np
from scipy.special import logsumexp

from .confidence import annotate, clamp01
from .features import HarmonicFeatures, unit_columns
from .tempo import RhythmInternals, extended_beat_frames
from .theory import CHORD_QUALITIES, chord_label, chord_template, uses_flats

BETA = 25.0
N_STATE = 24  # index of "no chord"


@dataclass
class RawChord:
    start: float
    end: float
    root: int | None
    quality: str | None
    confidence: float

    @property
    def is_chord(self) -> bool:
        return self.root is not None


def _templates() -> np.ndarray:
    T = np.zeros((25, 12))
    for r in range(12):
        T[r] = chord_template(r, "maj")
        T[12 + r] = chord_template(r, "min")
    T[N_STATE] = np.ones(12) / np.sqrt(12)
    return T


def _viterbi(logE: np.ndarray, logT: np.ndarray) -> np.ndarray:
    n, S = logE.shape
    delta = logE[0] - np.log(S)
    back = np.zeros((n, S), dtype=np.int32)
    for i in range(1, n):
        cand = delta[:, None] + logT
        back[i] = np.argmax(cand, axis=0)
        delta = cand[back[i], np.arange(S)] + logE[i]
    path = np.empty(n, dtype=np.int32)
    path[-1] = int(np.argmax(delta))
    for i in range(n - 1, 0, -1):
        path[i - 1] = back[i, path[i]]
    return path


def _posteriors(logE: np.ndarray, logT: np.ndarray) -> np.ndarray:
    n, S = logE.shape
    fwd = np.empty((n, S))
    bwd = np.zeros((n, S))
    fwd[0] = logE[0] - np.log(S)
    for i in range(1, n):
        fwd[i] = logsumexp(fwd[i - 1][:, None] + logT, axis=0) + logE[i]
    for i in range(n - 2, -1, -1):
        bwd[i] = logsumexp(logT + (logE[i + 1] + bwd[i + 1])[None, :], axis=1)
    post = fwd + bwd
    return np.exp(post - logsumexp(post, axis=1, keepdims=True))


def _segment_grid(rhythm: RhythmInternals, harm: HarmonicFeatures, duration: float) -> tuple[np.ndarray, float]:
    T = harm.chroma.shape[1]
    fr = harm.frame_rate
    if len(rhythm.beat_frames) >= 8 and rhythm.confidence >= 0.3 and rhythm.bpm:
        b = extended_beat_frames(rhythm, T).astype(float)
        if rhythm.bpm < 90:  # slow songs: allow changes on half-beats
            mids = (b[:-1] + b[1:]) / 2
            b = np.sort(np.concatenate([b, mids]))
            stay = 0.9
        else:
            stay = 0.82
        return np.unique(np.clip(b.astype(int), 1, T - 1)), stay
    step = max(1, int(0.5 * fr))
    return np.arange(step, T, step), 0.85


def detect_chords(harm: HarmonicFeatures, rhythm: RhythmInternals, duration: float) -> list[RawChord]:
    fr = harm.frame_rate
    bounds, stay = _segment_grid(rhythm, harm, duration)
    C = librosa.util.sync(harm.chroma, bounds, aggregate=np.median)
    Bc = librosa.util.sync(harm.chroma_bass, bounds, aggregate=np.median)
    E = librosa.util.sync(harm.frame_energy[None, :], bounds, aggregate=np.mean)[0]
    edges = np.concatenate([[0.0], bounds / fr, [duration]])
    starts, ends = edges[:-1], edges[1:]
    K = C.shape[1]
    starts, ends = starts[:K], ends[:K]

    # contrast enhancement: remove per-segment noise floor before normalising
    Cc = np.clip(C - np.percentile(C, 25, axis=0, keepdims=True), 0, None)
    cn = unit_columns(Cc)
    bn = Bc / (Bc.max(axis=0, keepdims=True) + 1e-12)
    T = _templates()
    scores = T @ cn  # (25, K)
    for r in range(12):  # bass-note evidence for the root
        bonus = 0.10 * (bn[r] - bn.mean(axis=0))
        scores[r] += bonus
        scores[12 + r] += bonus
    silent = E < 0.08 * np.percentile(E, 95)
    flat = Cc.sum(axis=0) < 1e-6
    scores[N_STATE] = 0.75 * scores[N_STATE] + np.where(silent | flat, 1.0, 0.0)

    logE = (BETA * scores - logsumexp(BETA * scores, axis=0, keepdims=True)).T  # (K, 25)
    S = 25
    logT = np.full((S, S), np.log((1 - stay) / (S - 1)))
    np.fill_diagonal(logT, np.log(stay))
    path = _viterbi(logE, logT)
    post = _posteriors(logE, logT)

    chords: list[RawChord] = []
    i = 0
    while i < K:
        j = i
        while j + 1 < K and path[j + 1] == path[i]:
            j += 1
        state = int(path[i])
        conf = float(post[i : j + 1, state].mean())
        if state == N_STATE:
            chords.append(RawChord(float(starts[i]), float(ends[j]), None, None, conf))
        else:
            root, quality = state % 12, ("maj" if state < 12 else "min")
            w = E[i : j + 1] + 1e-9
            seg = unit_columns((Cc[:, i : j + 1] * w).sum(axis=1, keepdims=True))[:, 0]
            quality, conf = _refine_quality(seg, root, quality, conf)
            chords.append(RawChord(float(starts[i]), float(ends[j]), root, quality, conf))
        i = j + 1
    return _merge_short(chords)


def _refine_quality(s: np.ndarray, r: int, base: str, conf: float) -> tuple[str, float]:
    def at(iv: int) -> float:
        return float(s[(r + iv) % 12])

    ref = max(at(0), at(7), 1e-9)
    base_score = float(chord_template(r, base) @ s)
    options: list[tuple[str, bool]] = []
    if base == "maj":
        options += [("7", at(10) >= 0.55 * ref), ("maj7", at(11) >= 0.55 * ref),
                    ("aug", at(8) >= 0.6 * at(0) and at(7) <= 0.35 * at(0))]
    else:
        options += [("min7", at(10) >= 0.55 * ref), ("dim", at(6) >= 0.6 * at(0) and at(7) <= 0.35 * at(0))]
    no_third = max(at(3), at(4)) <= 0.35 * at(0)
    options += [("sus4", at(5) >= 0.6 * at(0) and no_third), ("sus2", at(2) >= 0.6 * at(0) and no_third)]
    best, best_score = base, base_score
    for q, plausible in options:
        if not plausible:
            continue
        sc = float(chord_template(r, q) @ s)
        if sc > best_score + 0.03:
            best, best_score = q, sc
    if best != base:
        conf *= 0.85
    return best, conf


def _merge_short(chords: list[RawChord], min_dur: float = 0.25) -> list[RawChord]:
    out: list[RawChord] = []
    for c in chords:
        if out and (c.end - c.start) < min_dur:
            out[-1].end = c.end
            continue
        if out and out[-1].root == c.root and out[-1].quality == c.quality:
            d1, d2 = out[-1].end - out[-1].start, c.end - c.start
            out[-1].confidence = (out[-1].confidence * d1 + c.confidence * d2) / (d1 + d2)
            out[-1].end = c.end
            continue
        out.append(c)
    return out


def chords_block(raw: list[RawChord], tonic_pc: int | None, mode: str | None, duration: float,
                 harm: HarmonicFeatures) -> dict:
    flats = uses_flats(tonic_pc, mode)
    items = []
    total_dur = 0.0
    weighted = 0.0
    changes = 0
    prev = None
    durations: dict[str, float] = {}
    for c in raw:
        label = chord_label(c.root, c.quality, flats) if c.is_chord else "N"
        items.append({
            "start": round(c.start, 3), "end": round(c.end, 3), "chord": label,
            "root": None if c.root is None else int(c.root), "quality": c.quality,
            "confidence": round(clamp01(c.confidence), 3),
        })
        if c.is_chord:
            d = c.end - c.start
            total_dur += d
            weighted += d * c.confidence
            durations[label] = durations.get(label, 0.0) + d
            if prev is not None and prev != label:
                changes += 1
            prev = label
    tonal = float(np.mean(harm.tonalness)) if harm.tonalness.size else 0.0
    conf = (weighted / total_dur if total_dur else 0.0) * (0.6 + 0.4 * clamp01((tonal - 0.3) / 0.4))
    coverage = total_dur / duration if duration else 0.0
    if coverage < 0.3:
        conf *= coverage / 0.3
    top = sorted(durations.items(), key=lambda kv: kv[1], reverse=True)
    msg = "Chord recognition confidence is low." if conf < 0.5 else None
    block = {
        "available": True,
        "items": items,
        "unique_chords": len(durations),
        "changes_per_minute": round(changes / (duration / 60.0), 1) if duration else None,
        "mean_chord_duration_s": round(total_dur / max(1, sum(1 for c in raw if c.is_chord)), 2),
        "chord_coverage": round(coverage, 3),
        "most_common": [{"chord": k, "seconds": round(v, 1), "share": round(v / total_dur, 3)} for k, v in top[:8]],
        "vocabulary": sorted({q for q in (c.quality for c in raw) if q}),
        "method": "Beat-synchronous CQT chroma + bass chroma, template matching, HMM (Viterbi + forward-backward)",
    }
    return annotate(block, conf, "estimated", msg)


def supported_qualities() -> list[str]:
    return list(CHORD_QUALITIES)
