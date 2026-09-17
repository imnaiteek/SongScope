"""Aggregate harmonic descriptors and chromagram for visualisation."""

from __future__ import annotations

import numpy as np

from .confidence import annotate, clamp01
from .features import HarmonicFeatures
from .theory import is_diatonic, pc_name, simplify_quality, uses_flats


def analyze_harmony(harm: HarmonicFeatures, key: dict, chords: dict, duration: float) -> dict:
    tonic, mode = key.get("tonic_pc"), key.get("mode")
    flats = uses_flats(tonic, mode)
    weights = harm.frame_energy / (harm.frame_energy.sum() + 1e-12)
    dist = harm.chroma @ weights
    p = dist / (dist.sum() + 1e-12)
    entropy = float(-np.sum(p * np.log2(p + 1e-12)) / np.log2(12))

    items = [c for c in chords.get("items", []) if c["root"] is not None]
    total = sum(c["end"] - c["start"] for c in items) or 1e-9
    nondiatonic = 0.0
    if tonic is not None and mode:
        nondiatonic = sum(c["end"] - c["start"] for c in items
                          if not is_diatonic(c["root"], simplify_quality(c["quality"]), tonic, mode)) / total
    unique = chords.get("unique_chords", 0)
    cpm = chords.get("changes_per_minute") or 0.0
    ext_share = sum(c["end"] - c["start"] for c in items if c["quality"] not in ("maj", "min")) / total

    # entropy of a typical diatonic song sits around 0.85-0.92; rescale that range
    complexity = clamp01(0.35 * clamp01((entropy - 0.80) / 0.17) + 0.25 * clamp01((unique - 3) / 10)
                         + 0.25 * clamp01(nondiatonic / 0.35) + 0.15 * clamp01(ext_share / 0.4))
    key_change_share = sum(c["end"] - c["start"] for c in key.get("changes", [])) / duration if duration else 0.0
    stability = clamp01((1 - nondiatonic) * (1 - key_change_share) * (1 - 0.4 * clamp01((cpm - 20) / 60)))

    # chromagram: ~2 frames per second, column-normalised, 0-99 ints
    step = max(1, int(round(harm.frame_rate / 2)))
    C = harm.chroma
    n = C.shape[1] // step
    Cd = C[:, : n * step].reshape(12, n, step).mean(axis=2)
    Cd = Cd / (Cd.max(axis=0, keepdims=True) + 1e-12)
    silent = harm.frame_energy[: n * step].reshape(n, step).mean(axis=1) < 0.02 * np.percentile(harm.frame_energy, 95)
    Cd[:, silent] = 0

    block = {
        "available": True,
        "tonal_center": key.get("tonic"),
        "key": key.get("key"),
        "chroma_distribution": [{"pitch_class": pc_name(i, flats), "value": round(float(dist[i] / (dist.max() + 1e-12)), 3)}
                                for i in range(12)],
        "chroma_entropy": round(entropy, 3),
        "harmonic_complexity": round(complexity, 3),
        "complexity_label": "Simple" if complexity < 0.33 else ("Moderate" if complexity < 0.66 else "Complex"),
        "unique_chords": unique,
        "chord_changes_per_minute": cpm,
        "non_diatonic_share": round(nondiatonic, 3),
        "extended_chord_share": round(ext_share, 3),
        "harmonic_stability": round(stability, 3),
        "stability_label": "Stable" if stability >= 0.75 else ("Moderately stable" if stability >= 0.5 else "Unstable"),
        "chromagram": {"seconds_per_frame": round(step / harm.frame_rate, 4),
                       "pitch_classes": [pc_name(i, flats) for i in range(12)],
                       "values": [[int(round(v * 99)) for v in col] for col in Cd.T]},
    }
    conf = min(key.get("confidence", 0.0), 1.0) * 0.5 + chords.get("confidence", 0.0) * 0.5
    return annotate(block, conf, "estimated")
