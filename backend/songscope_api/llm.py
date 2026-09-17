"""Optional language-model layer. Runs strictly AFTER DSP analysis.

The model receives a compact JSON digest of the detected results and is instructed to explain
them for a given audience without inventing or altering any numbers.
"""

from __future__ import annotations

import json

AUDIENCES = {
    "beginner": "a curious listener with no music-theory background",
    "musician": "a general musician comfortable with keys, chords and meter",
    "guitarist": "a guitarist who wants practical playing guidance (capo ideas, chord shapes, strumming feel)",
    "producer": "a music producer interested in arrangement, groove, loudness and mix balance",
    "drummer": "a drummer interested in tempo, feel, meter and the groove pattern",
    "singer": "a singer interested in key, vocal range and phrasing",
    "educator": "a music teacher preparing a lesson about this track",
}

SYSTEM_PROMPT = """You explain automated music-analysis results to people.

You will receive a JSON digest produced by a signal-processing engine. Ground every statement in it:
- Never invent, round differently, or change numbers, keys, chords, tempos or section names.
- Never add facts that are not in the digest (no guesses about genre, instruments, lyrics, artist history).
- Each result has a confidence level. Present high-confidence results plainly; for medium say "likely";
  for low, say the result is uncertain and should be verified by ear. If a value is null, say it could not be determined.
- Section names such as Verse/Chorus are inferred from acoustic repetition and energy, not lyrics — say so if you mention them.
- Audience-specific practical advice is welcome as long as it follows directly from the digest
  (e.g. suggesting chord shapes for the detected chords).
Write 3-6 short paragraphs of plain prose (no headings, no tables)."""


def digest(results: dict) -> dict:
    """Small, number-preserving subset of the analysis for the prompt."""

    def pick(block: dict | None, keys: list[str]) -> dict:
        block = block or {}
        out = {k: block.get(k) for k in keys if k in block}
        out["confidence_level"] = block.get("confidence_level")
        return out

    prog = (results.get("progression") or {}).get("main") or {}
    sections = (results.get("structure") or {}).get("sections") or []
    drums = (results.get("drums") or {}).get("instruments") or {}
    return {
        "metadata": pick(results.get("metadata"), ["title", "artist", "duration"]),
        "tempo": pick(results.get("tempo"), ["bpm", "category", "alternative_bpm", "alternative_relation", "stability", "has_tempo_changes"]),
        "meter": pick(results.get("meter"), ["signature", "reliable", "tendency", "subdivision"]),
        "key": pick(results.get("key"), ["key", "alternative_key", "tuning_cents", "most_prominent_pitch_class"]),
        "chords": {
            "most_common": [c["chord"] for c in (results.get("chords") or {}).get("most_common", [])[:8]],
            "changes_per_minute": (results.get("chords") or {}).get("changes_per_minute"),
            "confidence_level": (results.get("chords") or {}).get("confidence_level"),
        },
        "main_progression": {"chords": prog.get("chords"), "numerals": prog.get("numerals"),
                             "confidence_level": (results.get("progression") or {}).get("confidence_level")},
        "sections": [{"label": s["display_label"], "start": s["start"], "end": s["end"]} for s in sections],
        "drum_pattern_estimate": {k: v.get("pattern") for k, v in drums.items()},
        "pitch": pick(results.get("pitch"), ["lowest_note", "highest_note", "range_description", "most_frequent_note", "source"]),
        "loudness": pick(results.get("loudness"), ["integrated_lufs", "true_peak_dbtp", "loudness_range_lu", "dynamic_range_db"]),
        "spectrum": (results.get("spectrum") or {}).get("summary"),
        "harmony": pick(results.get("harmony"), ["complexity_label", "stability_label", "non_diatonic_share"]),
    }


class LLMUnavailable(Exception):
    pass


def explain(results: dict, audience: str, api_key: str | None, model: str) -> str:
    if audience not in AUDIENCES:
        raise ValueError("unknown audience")
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise LLMUnavailable("The anthropic package is not installed.") from exc
    if not api_key:
        raise LLMUnavailable("No ANTHROPIC_API_KEY configured on the server.")

    client = anthropic.Anthropic(api_key=api_key, timeout=120.0)
    user = (
        f"Explain this analysis to {AUDIENCES[audience]}.\n\n"
        f"<analysis_digest>\n{json.dumps(digest(results), ensure_ascii=False, indent=1)}\n</analysis_digest>"
    )
    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.AuthenticationError as exc:
        raise LLMUnavailable("The configured Anthropic API key was rejected.") from exc
    except anthropic.RateLimitError as exc:
        raise LLMUnavailable("The language model is rate limited. Try again shortly.") from exc
    except anthropic.APIStatusError as exc:
        raise LLMUnavailable(f"The language model request failed ({exc.status_code}).") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMUnavailable("Could not reach the language model service.") from exc

    if response.stop_reason == "refusal":
        raise LLMUnavailable("The language model declined to produce an explanation.")
    text = "\n\n".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise LLMUnavailable("The language model returned an empty explanation.")
    return text
