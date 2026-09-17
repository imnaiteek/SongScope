"""Structural segmentation and (inferred) section labelling.

Boundaries come from Foote novelty on a combined self-similarity matrix built from
beat-synchronous harmony (time-delay embedded chroma), timbre (MFCC) and energy. Segments
are grouped by repetition (block similarity) into letters A, B, C... - that grouping is the
acoustically detected structure. Functional names (Verse, Chorus, Bridge...) are *inferred*
from repetition, energy and position; they are heuristics, never lyric-aware, and are marked
"Possible ..." whenever confidence is modest.
"""

from __future__ import annotations

import librosa
import numpy as np
from scipy.signal import find_peaks

from .confidence import annotate, clamp01
from .decode import AudioSignal
from .features import HarmonicFeatures, unit_columns
from .tempo import RhythmInternals, extended_beat_frames

POSSIBLE_THRESHOLD = 0.6


def _grid(rhythm: RhythmInternals, T: int, fr: float) -> np.ndarray:
    if len(rhythm.beat_frames) >= 16 and rhythm.confidence >= 0.35:
        g = extended_beat_frames(rhythm, T)
    else:
        g = np.arange(0, T, max(1, int(0.5 * fr)))
    g = g[g < T]
    return g if len(g) and g[0] == 0 else np.concatenate([[0], g]).astype(int)


def _cos_ssm(X: np.ndarray) -> np.ndarray:
    Xn = unit_columns(X)
    return Xn.T @ Xn


def _checkerboard(L: int) -> np.ndarray:
    ax = np.arange(-L, L) + 0.5
    g = np.exp(-0.5 * (ax / (0.5 * L)) ** 2)
    k = np.outer(np.sign(ax), np.sign(ax)) * np.outer(g, g)
    return k / np.abs(k).sum()


def _novelty(S: np.ndarray, L: int) -> np.ndarray:
    K = S.shape[0]
    pad = np.pad(S, L, mode="edge")
    kern = _checkerboard(L)
    nov = np.array([np.sum(kern * pad[i : i + 2 * L, i : i + 2 * L]) for i in range(K)])
    nov = np.clip(nov, 0, None)
    return nov / (nov.max() + 1e-12)


def _block_similarity(S: np.ndarray, a: tuple[int, int], b: tuple[int, int]) -> float:
    blk = S[a[0] : a[1], b[0] : b[1]]
    if blk.size == 0:
        return 0.0
    return float(0.5 * (blk.max(axis=1).mean() + blk.max(axis=0).mean()))


def analyze_structure(sig: AudioSignal, rhythm: RhythmInternals, harm: HarmonicFeatures,
                      downbeats: list[float], beats_per_bar: int | None) -> dict:
    fr = harm.frame_rate
    T = min(harm.chroma.shape[1], rhythm.mel_db.shape[1] if rhythm.mel_db is not None else harm.chroma.shape[1])
    grid = _grid(rhythm, T, fr)
    times = librosa.frames_to_time(grid, sr=sig.sr, hop_length=sig.hop)
    duration = sig.duration
    if len(grid) < 24 or duration < 20:
        block = {"available": True, "sections": [{"start": 0.0, "end": round(duration, 2), "label": "Section",
                                                   "display_label": "Section A", "group": "A", "confidence": 0.3}],
                 "sequence": "Section A", "ssm": None}
        return annotate(block, 0.3, "inferred", "Audio too short for structural segmentation.")

    chroma = librosa.util.sync(harm.chroma[:, :T], grid, aggregate=np.median, pad=False)
    mfcc = librosa.feature.mfcc(S=rhythm.mel_db[:, :T], n_mfcc=14)[1:]
    mfcc = librosa.util.sync(mfcc, grid, aggregate=np.mean, pad=False)
    mfcc = (mfcc - mfcc.mean(axis=1, keepdims=True)) / (mfcc.std(axis=1, keepdims=True) + 1e-9)
    rms = librosa.feature.rms(y=sig.mono, hop_length=sig.hop)[0][:T]
    rms_db = 20 * np.log10(librosa.util.sync(rms[None, :], grid, aggregate=np.mean, pad=False)[0] + 1e-6)
    K = min(chroma.shape[1], mfcc.shape[1], len(rms_db))
    chroma, mfcc, rms_db = chroma[:, :K], mfcc[:, :K], rms_db[:K]
    unit_times = np.concatenate([times[:K], [duration]])

    S_h = _cos_ssm(librosa.feature.stack_memory(chroma, n_steps=4, mode="edge"))
    S_t = (_cos_ssm(librosa.feature.stack_memory(mfcc, n_steps=2, mode="edge")) + 1) / 2
    S_e = np.exp(-np.abs(rms_db[:, None] - rms_db[None, :]) / 6.0)
    S = 0.45 * S_h + 0.35 * S_t + 0.2 * S_e

    unit_s = float(np.median(np.diff(unit_times)))
    bpb = beats_per_bar or 4
    L = int(np.clip(round(4 * bpb * (0.5 / unit_s if unit_s < 0.3 else 1.0)), 8, 32))
    nov = _novelty(S, L)
    min_len_units = max(4, int(round(7.5 / unit_s)))
    peaks, props = find_peaks(nov, distance=min_len_units, prominence=0.08, height=np.mean(nov) + 0.25 * np.std(nov))
    max_sections = max(2, int(duration / 9))
    if len(peaks) > max_sections - 1:
        keep = np.argsort(props["prominences"])[::-1][: max_sections - 1]
        peaks = np.sort(peaks[keep])

    # snap to downbeats when available
    bounds_t = [float(unit_times[p]) for p in peaks]
    if downbeats and len(downbeats) > 4:
        db = np.asarray(downbeats)
        bar = float(np.median(np.diff(db)))
        snapped = []
        for t in bounds_t:
            j = int(np.argmin(np.abs(db - t)))
            snapped.append(float(db[j]) if abs(db[j] - t) < 0.5 * bar else t)
        bounds_t = snapped
    strengths = {round(t, 3): float(nov[p]) for t, p in zip(bounds_t, peaks)}
    edges = sorted(set([0.0] + [t for t in bounds_t if 1.0 < t < duration - 1.0] + [duration]))

    def to_unit(t: float) -> int:
        return int(np.clip(np.searchsorted(unit_times, t), 0, K))

    segs = [{"start": a, "end": b, "u": (to_unit(a), max(to_unit(a) + 1, to_unit(b)))} for a, b in zip(edges[:-1], edges[1:])]
    segs = _merge_short(segs, S, min_seconds=6.0)

    # --- group by repetition -----------------------------------------------------
    n = len(segs)
    sim = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            sim[i, j] = sim[j, i] = _block_similarity(S, segs[i]["u"], segs[j]["u"])
    offdiag = sim[~np.eye(n, dtype=bool)] if n > 1 else np.array([0.0])
    groups = _cluster(sim, threshold=max(0.86, float(np.percentile(offdiag, 60)) if n > 2 else 0.86))
    letters = {}
    for g in groups:
        if g not in letters:
            letters[g] = chr(ord("A") + len(letters)) if len(letters) < 26 else f"Z{len(letters)}"
    track_db = float(np.median(rms_db))
    for s, g in zip(segs, groups):
        a, b = s["u"]
        s["group"] = letters[g]
        s["energy_db"] = float(np.mean(rms_db[a:b])) - track_db
        s["boundary_strength"] = strengths.get(round(s["start"], 3), 1.0 if s["start"] == 0 else 0.5)

    labels, confs = _label(segs, duration)
    n_groups = len({x["group"] for x in segs})
    repeated_share = sum(x["end"] - x["start"] for x in segs
                         if sum(1 for y in segs if y["group"] == x["group"]) >= 2) / duration
    if len(segs) > 16 or repeated_share < 0.4 or n_groups > max(6, len(segs) * 0.7):
        # no clear song form (e.g. film score, ambient, DJ mix): keep acoustic letters only
        labels = [f"Section {x['group']}" for x in segs]
        confs = [0.3] * len(segs)
    sections = []
    for s, lab, c in zip(segs, labels, confs):
        c = clamp01(c)
        display = lab if c >= POSSIBLE_THRESHOLD or lab.startswith("Section") else f"Possible {lab}"
        sections.append({
            "start": round(s["start"], 2), "end": round(s["end"], 2), "label": lab, "display_label": display,
            "group": s["group"], "confidence": round(c, 3), "relative_energy_db": round(s["energy_db"], 1),
            "boundary_strength": round(float(s["boundary_strength"]), 3),
        })
    overall = float(np.mean([s["confidence"] for s in sections])) if sections else 0.0
    step = max(1, int(np.ceil(K / 160)))
    ssm_small = S[::step, ::step]
    block = {
        "available": True,
        "sections": sections,
        "sequence": " → ".join(s["display_label"] for s in sections),
        "group_sequence": "".join(s["group"] for s in sections),
        "ssm": {"size": int(ssm_small.shape[0]), "seconds_per_cell": round(duration / ssm_small.shape[0], 3),
                "values": [[int(round(v * 99)) for v in row] for row in np.clip(ssm_small, 0, 1)]},
        "novelty": {"times": [round(float(t), 2) for t in unit_times[:K:step]],
                    "values": [round(float(v), 3) for v in nov[::step]]},
        "method": "Foote novelty on harmony/timbre/energy self-similarity; repetition clustering; heuristic labels",
    }
    return annotate(block, overall, "inferred",
                    "Section letters come from acoustic repetition. Names like Verse/Chorus are inferred from "
                    "repetition, energy and position — the analysis does not understand lyrics.")


def _merge_short(segs: list[dict], S: np.ndarray, min_seconds: float) -> list[dict]:
    changed = True
    while changed and len(segs) > 1:
        changed = False
        for i, s in enumerate(segs):
            if s["end"] - s["start"] >= min_seconds:
                continue
            if i == 0:
                j = 1
            elif i == len(segs) - 1:
                j = i - 1
            else:
                left = _block_similarity(S, segs[i - 1]["u"], s["u"])
                right = _block_similarity(S, segs[i + 1]["u"], s["u"])
                j = i - 1 if left >= right else i + 1
            a, b = sorted((i, j))
            merged = {"start": segs[a]["start"], "end": segs[b]["end"], "u": (segs[a]["u"][0], segs[b]["u"][1])}
            segs = segs[:a] + [merged] + segs[b + 1 :]
            changed = True
            break
    return segs


def _cluster(sim: np.ndarray, threshold: float) -> list[int]:
    n = sim.shape[0]
    if n == 1:
        return [0]
    from sklearn.cluster import AgglomerativeClustering

    dist = np.clip(1.0 - sim, 0, None)
    np.fill_diagonal(dist, 0)
    model = AgglomerativeClustering(n_clusters=None, metric="precomputed", linkage="average",
                                    distance_threshold=1.0 - threshold)
    raw = model.fit_predict(dist)
    remap: dict[int, int] = {}
    return [remap.setdefault(int(g), len(remap)) for g in raw]


def _label(segs: list[dict], duration: float) -> tuple[list[str], list[float]]:
    n = len(segs)
    groups: dict[str, list[int]] = {}
    for i, s in enumerate(segs):
        groups.setdefault(s["group"], []).append(i)
    repeated = [g for g, idx in groups.items() if len(idx) >= 2]
    labels: list[str | None] = [None] * n
    confs = [0.3] * n

    if not repeated:
        return [f"Section {s['group']}" for s in segs], [0.3] * n

    def g_energy(g: str) -> float:
        return float(np.mean([segs[i]["energy_db"] for i in groups[g]]))

    energies = {g: g_energy(g) for g in repeated}
    e_lo, e_hi = min(energies.values()), max(energies.values())

    def chorus_score(g: str) -> float:
        e = (energies[g] - e_lo) / (e_hi - e_lo) if e_hi > e_lo else 0.5
        late = np.mean([(segs[i]["start"] + segs[i]["end"]) / 2 / duration for i in groups[g]])
        return 0.6 * e + 0.25 * min(len(groups[g]), 4) / 4 + 0.15 * late

    chorus = max(repeated, key=chorus_score)
    others = [g for g in repeated if g != chorus]
    first_chorus = groups[chorus][0]
    verse = None
    if others:
        before = [g for g in others if groups[g][0] < first_chorus]
        pool = before or others
        verse = max(pool, key=lambda g: sum(segs[i]["end"] - segs[i]["start"] for i in groups[g]))

    contrast = energies[chorus] - (energies[verse] if verse else np.median([s["energy_db"] for s in segs]))
    chorus_conf = 0.4 + 0.3 * clamp01(contrast / 4.0) + 0.15 * clamp01((len(groups[chorus]) - 1) / 2) + 0.1
    verse_conf = 0.35 + 0.3 * clamp01(contrast / 4.0) + 0.15 * clamp01((len(groups[verse]) - 1) / 2) if verse else 0

    for i, s in enumerate(segs):
        if s["group"] == chorus:
            labels[i], confs[i] = "Chorus", chorus_conf
        elif s["group"] == verse:
            labels[i], confs[i] = "Verse", verse_conf

    # other repeated groups: pre-chorus if they usually lead into a chorus
    for g in others:
        if g == verse:
            continue
        idx = groups[g]
        leads = sum(1 for i in idx if i + 1 < n and segs[i + 1]["group"] == chorus)
        for i in idx:
            if leads >= max(1, int(np.ceil(len(idx) * 2 / 3))):
                labels[i], confs[i] = "Pre-Chorus", 0.5
            else:
                labels[i], confs[i] = "Interlude", 0.35

    median_e = float(np.median([s["energy_db"] for s in segs]))
    for i, s in enumerate(segs):
        if labels[i] is not None and i not in (0, n - 1):
            continue
        dur = s["end"] - s["start"]
        if i == 0 and n > 1 and (labels[i] is None or (labels[i] not in ("Chorus", "Verse") and dur <= 30)):
            labels[i], confs[i] = "Intro", 0.55 + (0.2 if s["energy_db"] < median_e else 0.0)
        elif i == n - 1 and n > 1:
            if labels[i] in (None, "Interlude"):
                labels[i], confs[i] = "Outro", 0.55 + (0.2 if s["energy_db"] < median_e else 0.0)
            elif labels[i] == "Chorus" and s["energy_db"] < energies[chorus] - 3.0:
                labels[i], confs[i] = "Outro", 0.5
        elif labels[i] is None:
            chorus_idx = groups[chorus]
            if i + 1 < n and segs[i + 1]["group"] == chorus and i > 0 and labels[i - 1] == "Verse":
                labels[i], confs[i] = "Pre-Chorus", 0.45
            elif chorus_idx[0] < i < chorus_idx[-1]:
                labels[i], confs[i] = "Bridge", 0.55
            else:
                labels[i], confs[i] = "Interlude", 0.35

    chorus_positions = [i for i in range(n) if labels[i] == "Chorus"]
    if len(chorus_positions) >= 3 or (chorus_positions and any(labels[i] == "Bridge" for i in range(chorus_positions[-1]))):
        last = chorus_positions[-1] if chorus_positions else None
        if last is not None and last > 0 and labels[last - 1] in ("Bridge", "Chorus", "Pre-Chorus", "Interlude"):
            labels[last] = "Final Chorus"
    return [lab or f"Section {s['group']}" for lab, s in zip(labels, segs)], confs
