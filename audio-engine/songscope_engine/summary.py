"""Human-readable summary generated strictly from detected values.

Every clause is conditioned on the corresponding confidence so uncertain results are hedged
or omitted; nothing is stated that the analysis did not measure.
"""

from __future__ import annotations


def _lvl(block: dict | None) -> str:
    return (block or {}).get("confidence_level", "low")


def _fmt_bpm(bpm: float) -> str:
    return f"{bpm:.0f}" if abs(bpm - round(bpm)) < 0.25 else f"{bpm:.1f}"


def build_summary(r: dict) -> dict:
    sentences: list[str] = []
    highlights: list[dict] = []
    tempo, meter, key = r.get("tempo") or {}, r.get("meter") or {}, r.get("key") or {}
    prog, chords, structure = r.get("progression") or {}, r.get("chords") or {}, r.get("structure") or {}
    loud, pitch, spec = r.get("loudness") or {}, r.get("pitch") or {}, r.get("spectrum") or {}

    # --- opening sentences: tempo, key, meter --------------------------------------------
    bpm = tempo.get("bpm")
    key_name = key.get("key")
    key_phrase = None
    if key_name:
        key_phrase = {"high": f"in {key_name}", "medium": f"most likely in {key_name}"}.get(
            _lvl(key), f"with an ambiguous tonal centre (weak tendency toward {key_name})")
    meter_phrase = None
    if meter.get("reliable") and meter.get("signature"):
        meter_phrase = f"with a {meter['signature']} meter" + ("" if _lvl(meter) == "high" else " (medium confidence)")
    if bpm and _lvl(tempo) in ("high", "medium"):
        lead = (f"An approximately {_fmt_bpm(bpm)} BPM track" if _lvl(tempo) == "high"
                else f"A track with an estimated tempo of around {_fmt_bpm(bpm)} BPM")
        sentences.append(" ".join(p for p in (lead, key_phrase, meter_phrase) if p) + ".")
    else:
        if bpm:
            sentences.append(f"The tempo could not be established reliably (weak estimate ≈{_fmt_bpm(bpm)} BPM).")
        else:
            sentences.append("No clearly detectable rhythmic pulse was found.")
        if key_phrase:
            sentences.append(" ".join(p for p in ("The track is", key_phrase, meter_phrase) if p) + ".")
    if not meter.get("reliable"):
        sentences.append("The meter could not be determined reliably.")
    if tempo.get("octave_ambiguous") and tempo.get("alternative_bpm") and _lvl(tempo) != "low":
        sentences.append(f"It could also be felt at {_fmt_bpm(tempo['alternative_bpm'])} BPM ({tempo.get('alternative_relation')}).")

    # --- harmony ------------------------------------------------------------------
    common = [c["chord"] for c in (chords.get("most_common") or [])[:4]]
    main = prog.get("main") if prog else None
    if common and _lvl(chords) != "low":
        s = f"The harmonic language primarily revolves around {', '.join(common[:-1])} and {common[-1]}" if len(common) > 1 \
            else f"The harmony centres on {common[0]}"
        if main and main.get("numerals_display") and _lvl(prog) != "low":
            s += f", with a recurring {main['display']} ({main['numerals_display']}) progression"
        sentences.append(s + ".")
    elif chords.get("available"):
        sentences.append("Chord recognition confidence is low, so the harmonic description should be verified by ear.")

    # --- tempo stability ----------------------------------------------------------
    stab = tempo.get("stability")
    if stab is not None and bpm:
        if tempo.get("tempo_varies"):
            sentences.append("The tempo varies considerably, so no single tempo map describes the whole track.")
        elif tempo.get("has_tempo_changes"):
            secs = ", ".join(f"{_fmt_bpm(s['bpm'])} BPM" for s in tempo.get("sections", []))
            sentences.append(f"The tempo appears to change over the course of the track ({secs}).")
        elif stab >= 0.9:
            sentences.append("The tempo is very stable throughout, consistent with a quantised or click-tracked performance.")
        elif stab >= 0.7:
            sentences.append("The tempo is relatively stable throughout the track.")
        else:
            sentences.append("The tempo fluctuates noticeably, suggesting a freely performed or rubato recording.")

    # --- structure ----------------------------------------------------------------
    secs = structure.get("sections") or []
    if len(secs) >= 3:
        if all(s["label"].startswith("Section") for s in secs):
            groups = len({s["group"] for s in secs})
            sentences.append(f"Structural analysis found {len(secs)} acoustically distinct segments ({groups} recurring types) "
                             "but no clear verse/chorus form.")
        elif len(secs) <= 12:
            labels = [s["display_label"] for s in secs]
            sentences.append(f"Structural analysis suggests {len(secs)} sections ({' → '.join(labels)}); section names are inferred.")
        else:
            sentences.append(f"Structural analysis suggests {len(secs)} sections; section names are inferred.")

    # --- loudness -----------------------------------------------------------------
    if loud.get("integrated_lufs") is not None:
        sentences.append(
            f"Integrated loudness measures {loud['integrated_lufs']} LUFS with a true peak of {loud['true_peak_dbtp']} dBTP"
            + (f" and a loudness range of {loud['loudness_range_lu']} LU" if loud.get("loudness_range_lu") is not None else "")
            + f" — {loud.get('character', '').rstrip('.').lower()}."
        )

    # --- pitch & timbre -------------------------------------------------------------
    if pitch.get("lowest_note") and _lvl(pitch) != "low":
        sentences.append(f"The tracked melodic line spans roughly {pitch['range_description']} ({pitch['lowest_note']}–{pitch['highest_note']}).")
    summ = spec.get("summary") or {}
    if summ.get("brightness"):
        emph = summ.get("emphasized_regions") or []
        sentences.append(f"Spectrally the mix is {summ['brightness'].lower()}" + (f", with emphasis in the {', '.join(e.lower() for e in emph)} region{'s' if len(emph) > 1 else ''}" if emph else "") + ".")

    for label, block, value in (
        ("Tempo", tempo, f"{_fmt_bpm(bpm)} BPM" if bpm else "Undetermined"),
        ("Key", key, key.get("key") or "Undetermined"),
        ("Meter", meter, meter.get("signature") if meter.get("reliable") else "Undetermined"),
        ("Chords", chords, main["display"] if main else "—"),
        ("Structure", structure, f"{len(secs)} sections" if secs else "—"),
    ):
        highlights.append({"label": label, "value": value, "confidence": block.get("confidence"),
                           "confidence_level": block.get("confidence_level"), "status": block.get("status")})
    return {"text": " ".join(sentences), "sentences": sentences, "highlights": highlights,
            "generated_from": "detected analysis values (template-based, no language model)"}
