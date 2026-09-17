"""Recurring chord progressions and Roman-numeral analysis."""

from __future__ import annotations

from collections import Counter

import numpy as np

from .confidence import annotate, clamp01
from .theory import chord_label, roman_numeral, simplify_quality, uses_flats

LENGTH_WEIGHT = {2: 0.45, 3: 0.8, 4: 1.0, 5: 0.85, 6: 0.9, 7: 0.9, 8: 0.95}


def _is_periodic(gram: tuple) -> bool:
    n = len(gram)
    for p in range(1, n):
        if n % p == 0 and gram == gram[:p] * (n // p):
            return True
    return False


def _canonical(gram: tuple) -> tuple:
    return min(gram[i:] + gram[:i] for i in range(len(gram)))


def _occurrences(labels: list, gram: tuple) -> list[int]:
    n, out, i = len(gram), [], 0
    while i <= len(labels) - n:
        if tuple(labels[i : i + n]) == gram:
            out.append(i)
            i += n
        else:
            i += 1
    return out


def analyze_progressions(chords: list[dict], tonic_pc: int | None, mode: str | None,
                         sections: list[dict] | None, chord_confidence: float) -> dict:
    flats = uses_flats(tonic_pc, mode)
    seq: list[dict] = []
    for c in chords:
        if c["root"] is None:
            continue
        q = simplify_quality(c["quality"])
        lab = chord_label(c["root"], q, flats)
        if seq and seq[-1]["label"] == lab:
            seq[-1]["end"] = c["end"]
            seq[-1]["conf"].append(c["confidence"])
            continue
        seq.append({"label": lab, "root": c["root"], "quality": q, "start": c["start"], "end": c["end"],
                    "conf": [c["confidence"]]})
    labels = [s["label"] for s in seq]
    if len(labels) < 4:
        return annotate({"available": True, "main": None, "others": [], "by_section": []}, 0.0, "inferred",
                        "Not enough harmonic content to identify recurring progressions.")

    patterns: dict[tuple, dict] = {}
    for n in range(2, 9):
        if len(labels) < 2 * n:
            break
        counts = Counter(tuple(labels[i : i + n]) for i in range(len(labels) - n + 1))
        for gram, c in counts.items():
            if c < 2 or len(set(gram)) < 2 or _is_periodic(gram):
                continue
            key = (n, _canonical(gram))
            rec = patterns.setdefault(key, {"rotations": {}})
            rec["rotations"][gram] = len(_occurrences(labels, gram))

    scored = []
    for (n, canon), rec in patterns.items():
        gram, occ = max(rec["rotations"].items(), key=lambda kv: (kv[1], -labels.index(kv[0][0])))
        if occ < 2:
            continue
        coverage = occ * n / len(labels)
        scored.append((coverage * LENGTH_WEIGHT[n], n, gram, occ, coverage))
    if not scored:
        return annotate({"available": True, "main": None, "others": [], "by_section": []}, 0.2, "inferred",
                        "No clearly repeating chord progression was found.")
    scored.sort(key=lambda x: x[0], reverse=True)

    def describe(gram: tuple, occ_count: int, coverage: float) -> dict:
        starts = _occurrences(labels, gram)
        occ = [{"start": round(seq[i]["start"], 2), "end": round(seq[i + len(gram) - 1]["end"], 2)} for i in starts]
        confs = [np.mean(seq[i + k]["conf"]) for i in starts for k in range(len(gram))]
        numerals = None
        if tonic_pc is not None and mode:
            numerals = [roman_numeral(seq[starts[0] + k]["root"], seq[starts[0] + k]["quality"], tonic_pc, mode)
                        for k in range(len(gram))]
        in_sections = []
        if sections:
            for si, sec in enumerate(sections):
                if any(o["start"] < sec["end"] and o["end"] > sec["start"] for o in occ):
                    in_sections.append(si)
        return {
            "chords": list(gram),
            "display": " → ".join(gram),
            "numerals": numerals,
            "numerals_display": " – ".join(numerals) if numerals else None,
            "occurrences": occ,
            "count": occ_count,
            "coverage": round(coverage, 3),
            "sections": in_sections,
            "confidence": round(clamp01(float(np.mean(confs)) * clamp01(coverage * 2.5)), 3),
        }

    main_score, main_n, main_gram, main_occ, main_cov = scored[0]
    main = describe(main_gram, main_occ, main_cov)
    main_canon = _canonical(main_gram)
    others = []
    used = [set(main_gram)]
    for sc, n, gram, occ, cov in scored[1:]:
        canon = _canonical(gram)
        if canon == main_canon or cov < 0.2 or occ < 3:
            continue
        # skip "junction" patterns that mostly overlap the main progression's occurrences
        cand_occ = [(seq[i]["start"], seq[i + n - 1]["end"]) for i in _occurrences(labels, gram)]
        overlap = sum(max(0.0, min(e, o["end"]) - max(s_, o["start"])) for s_, e in cand_occ for o in main["occurrences"])
        if overlap > 0.5 * sum(e - s_ for s_, e in cand_occ):
            continue
        doubled = main_gram + main_gram
        if any(doubled[i : i + n] == gram for i in range(len(main_gram))) or any(set(gram) == u for u in used):
            continue
        others.append(describe(gram, occ, cov))
        used.append(set(gram))
        if len(others) >= 3:
            break

    by_section = []
    for si, sec in enumerate(sections or []):
        inside = [s for s in seq if s["start"] < sec["end"] - 0.25 and s["end"] > sec["start"] + 0.25]
        labs = [s["label"] for s in inside]
        match = None
        for p in [main] + others:
            if si in p["sections"]:
                match = p["display"]
                break
        compact = labs[:8]
        by_section.append({"section_index": si, "label": sec.get("display_label"), "start": sec["start"],
                           "end": sec["end"], "chords": compact, "progression": match})

    conf = main["confidence"] * (0.7 + 0.3 * clamp01(chord_confidence))
    return annotate({"available": True, "main": main, "others": others, "by_section": by_section}, conf,
                    "inferred", None)
