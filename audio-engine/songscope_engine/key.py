"""Key estimation by fusing several independent methods.

  * Pitch-class profile correlation with four published key profiles
    (Krumhansl-Kessler, Temperley/Kostka-Payne, Aarden-Essen, Albrecht-Shanahan)
  * Chord-sequence fit (how well detected chords are explained diatonically by each key)
  * Bass tonic evidence (bass register emphasises tonic and dominant)
  * Cadential evidence (first/last sustained chords)

Confidence combines the margin between the best and runner-up keys, agreement between
methods and the tonal clarity of the audio. Sustained modulations are reported separately.
"""

from __future__ import annotations

import numpy as np

from .chords import RawChord
from .confidence import annotate, clamp01
from .features import HarmonicFeatures
from .theory import SHARP_NAMES, is_diatonic, key_name, pc_name, uses_flats

PROFILES = {
    "krumhansl_kessler": (
        [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88],
        [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17],
    ),
    "temperley": (
        [0.748, 0.060, 0.488, 0.082, 0.670, 0.460, 0.096, 0.715, 0.104, 0.366, 0.057, 0.400],
        [0.712, 0.084, 0.474, 0.618, 0.049, 0.460, 0.105, 0.747, 0.404, 0.067, 0.133, 0.330],
    ),
    "aarden_essen": (
        [17.7661, 0.145624, 14.9265, 0.160186, 19.8049, 11.3587, 0.291248, 22.062, 0.145624, 8.15494, 0.232998, 4.95122],
        [18.2648, 0.737619, 14.0499, 16.8599, 0.702494, 14.4362, 0.702494, 18.6161, 4.56621, 1.93186, 7.37619, 1.75623],
    ),
    "albrecht_shanahan": (
        [0.238, 0.006, 0.111, 0.006, 0.137, 0.094, 0.016, 0.214, 0.009, 0.080, 0.008, 0.081],
        [0.220, 0.006, 0.104, 0.123, 0.019, 0.103, 0.012, 0.214, 0.062, 0.022, 0.061, 0.052],
    ),
}


def key_index(tonic: int, mode: str) -> int:
    return tonic if mode == "major" else 12 + tonic


def index_key(i: int) -> tuple[int, str]:
    return (i % 12, "major" if i < 12 else "minor")


def relative_index(i: int) -> int:
    t, m = index_key(i)
    return key_index((t + 9) % 12, "minor") if m == "major" else key_index((t + 3) % 12, "major")


def profile_correlations(chroma12: np.ndarray, name: str) -> np.ndarray:
    major, minor = (np.array(p, dtype=float) for p in PROFILES[name])
    out = np.zeros(24)
    x = chroma12 - chroma12.mean()
    xs = np.sqrt(np.sum(x**2)) + 1e-12
    for i, prof in enumerate((major, minor)):
        for t in range(12):
            p = np.roll(prof, t)
            p = p - p.mean()
            out[i * 12 + t] = float(np.sum(x * p) / (xs * (np.sqrt(np.sum(p**2)) + 1e-12)))
    return out


def _minmax(x: np.ndarray) -> np.ndarray:
    lo, hi = x.min(), x.max()
    return (x - lo) / (hi - lo) if hi > lo else np.zeros_like(x)


def _chord_fit(chords: list[RawChord]) -> np.ndarray | None:
    real = [c for c in chords if c.is_chord]
    total = sum(c.end - c.start for c in real)
    if total < 5.0 or len(real) < 3:
        return None
    fit = np.zeros(24)
    for i in range(24):
        tonic, mode = index_key(i)
        tonic_q = "maj" if mode == "major" else "min"
        acc = 0.0
        for c in real:
            d = (c.end - c.start) * c.confidence
            simple = {"7": "maj", "maj7": "maj", "min7": "min"}.get(c.quality, c.quality)
            degree = (c.root - tonic) % 12
            if degree == 0 and simple == tonic_q:
                w = 1.6
            elif is_diatonic(c.root, simple, tonic, mode):
                w = 1.1 if degree == 7 else (1.0 if degree == 5 else 0.8)
            else:
                w = -0.3
            acc += d * w
        fit[i] = acc / total
    return fit


def _cadence(chords: list[RawChord]) -> np.ndarray:
    real = [c for c in chords if c.is_chord and (c.end - c.start) >= 1.0]
    out = np.zeros(24)
    if not real:
        return out
    for c, w in ((real[0], 0.4), (real[-1], 0.6)):
        simple = {"7": "maj", "maj7": "maj", "min7": "min"}.get(c.quality, c.quality)
        if simple in ("maj", "min"):
            out[key_index(c.root, "major" if simple == "maj" else "minor")] += w
    return out


def _best_consensus(chroma12: np.ndarray) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    per = {name: profile_correlations(chroma12, name) for name in PROFILES}
    consensus = np.zeros(24)
    for r in per.values():
        consensus += (r - r.mean()) / (r.std() + 1e-12)
    return consensus / len(per), per


def analyze_key(harm: HarmonicFeatures, chords: list[RawChord], duration: float) -> tuple[dict, dict]:
    weights = harm.frame_energy / (harm.frame_energy.sum() + 1e-12)
    chroma12 = harm.chroma @ weights
    bass12 = harm.chroma_bass @ weights
    if chroma12.max() <= 0:
        block = annotate({"available": True, "key": None, "tonic": None, "mode": None}, 0.0, "estimated",
                         "No reliable key detected.")
        return block, {"tonic": None, "mode": None}

    consensus, per = _best_consensus(chroma12)
    fit = _chord_fit(chords)
    bassn = bass12 / (bass12.max() + 1e-12)
    bass_ev = np.array([bassn[index_key(i)[0]] + 0.4 * bassn[(index_key(i)[0] + 7) % 12] for i in range(24)])
    cadence = _cadence(chords)

    components = [(0.5, _minmax(consensus)), (0.1, _minmax(bass_ev)), (0.1, cadence)]
    if fit is not None:
        components.append((0.3, _minmax(fit)))
    total_w = sum(w for w, _ in components)
    fused = sum(w * c for w, c in components) / total_w

    order = np.argsort(fused)[::-1]
    best, second = int(order[0]), int(order[1])
    tonic, mode = index_key(best)

    votes = [int(np.argmax(r)) for r in per.values()]
    if fit is not None:
        votes.append(int(np.argmax(fit)))
    agree = np.mean([1.0 if v == best else (0.5 if v == relative_index(best) else 0.0) for v in votes])
    bass_agree = 1.0 if int(np.argmax(bassn)) == tonic else 0.0
    agreement = 0.85 * agree + 0.15 * bass_agree
    margin = clamp01((fused[best] - fused[second]) / (fused[best] - np.median(fused) + 1e-12) * 2.5)
    clarity = clamp01((per["krumhansl_kessler"].max() - 0.4) / 0.45)
    conf = 0.45 * agreement + 0.35 * margin + 0.2 * clarity

    # key signature (scale) certainty: combine each key with its relative
    scale = np.array([max(fused[i], fused[relative_index(i)]) for i in range(12)])
    s_order = np.sort(scale)[::-1]
    scale_conf = clamp01(0.5 * agreement + 0.5 * clamp01((s_order[0] - s_order[1]) / (s_order[0] - np.median(scale) + 1e-12) * 2.0))
    scale_conf = max(scale_conf, conf)

    flats = uses_flats(tonic, mode)
    alt_t, alt_m = index_key(second)
    candidates = [{"key": key_name(*index_key(int(i))), "score": round(float(fused[i]), 3)} for i in order[:5]]
    msg = None
    if second == relative_index(best) and fused[second] > 0.9 * fused[best]:
        msg = f"Relative major/minor ambiguity: {key_name(alt_t, alt_m)} is nearly as likely."
    elif conf < 0.5:
        msg = "No reliable key detected — tonal centre is ambiguous. Verify manually."

    dom_pc = int(np.argmax(chroma12))
    block = annotate(
        {
            "available": True,
            "key": key_name(tonic, mode),
            "tonic": pc_name(tonic, flats),
            "tonic_pc": tonic,
            "mode": mode,
            "alternative_key": key_name(alt_t, alt_m),
            "alternative_relation": _relation(best, second),
            "candidates": candidates,
            "scale_confidence": round(scale_conf, 3),
            "method_votes": {name: key_name(*index_key(v)) for name, v in zip(list(per) + (["chord_fit"] if fit is not None else []), votes)},
            "tuning_cents": round(harm.tuning_cents, 1),
            "reference_a4_hz": round(440.0 * 2 ** (harm.tuning_cents / 1200.0), 2),
            "most_prominent_pitch_class": pc_name(dom_pc, flats),
            "chroma_distribution": {pc_name(i, flats): round(float(chroma12[i] / chroma12.max()), 3) for i in range(12)},
            "components": {"agreement": round(float(agreement), 3), "margin": round(margin, 3), "tonal_clarity": round(clarity, 3)},
            "changes": _key_changes(harm, best, duration),
        },
        conf,
        "estimated",
        msg,
    )
    return block, {"tonic": tonic, "mode": mode}


def _relation(a: int, b: int) -> str:
    ta, ma = index_key(a)
    tb, mb = index_key(b)
    if b == relative_index(a):
        return "relative"
    if ta == tb:
        return "parallel"
    if ma == mb and (tb - ta) % 12 == 7:
        return "dominant"
    if ma == mb and (tb - ta) % 12 == 5:
        return "subdominant"
    return "other"


def _key_changes(harm: HarmonicFeatures, global_idx: int, duration: float) -> list[dict]:
    win_s, hop_s = 24.0, 6.0
    if duration < 75:
        return []
    fr = harm.frame_rate
    wins = []
    for start in np.arange(0, duration - win_s + 1e-6, hop_s):
        a, b = int(start * fr), int((start + win_s) * fr)
        e = harm.frame_energy[a:b]
        if e.sum() <= 0:
            continue
        c = harm.chroma[:, a:b] @ (e / e.sum())
        cons, _ = _best_consensus(c)
        o = np.argsort(cons)[::-1]
        margin = clamp01((cons[o[0]] - cons[o[1]]) / 0.6)
        wins.append((float(start), int(o[0]), margin))
    if len(wins) < 4:
        return []
    labels = [w[1] for w in wins]
    smoothed = []
    for i in range(len(labels)):
        nb = labels[max(0, i - 1) : i + 2]
        smoothed.append(max(set(nb), key=nb.count))
    segs: list[list] = []
    for (start, _, m), lab in zip(wins, smoothed):
        if segs and segs[-1][2] == lab:
            segs[-1][1] = start + win_s
            segs[-1][3].append(m)
        else:
            segs.append([start, start + win_s, lab, [m]])
    significant = [
        s for s in segs
        if s[2] != global_idx and s[2] != relative_index(global_idx) and (s[1] - s[0]) >= 36 and np.mean(s[3]) >= 0.55
    ]
    if not significant:
        return []
    out = []
    for s in significant:
        t, m = index_key(s[2])
        out.append({"start": round(s[0] + hop_s, 1), "end": round(min(duration, s[1] - hop_s), 1),
                    "key": key_name(t, m), "confidence": round(float(np.mean(s[3])) * 0.8, 3)})
    return out


__all__ = ["analyze_key", "PROFILES", "SHARP_NAMES"]
