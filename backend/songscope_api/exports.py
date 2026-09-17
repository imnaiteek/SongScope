"""Report exports: JSON, CSV, plain text and PDF — all rendered from stored results."""

from __future__ import annotations

import csv
import io
import json
import re


def _t(sec: float | None) -> str:
    if sec is None:
        return "—"
    m, s = divmod(float(sec), 60)
    return f"{int(m)}:{s:04.1f}"


def _pct(c: float | None) -> str:
    return "—" if c is None else f"{round(c * 100)}%"


def slug(text: str | None) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", text or "analysis").strip("-").lower()
    return s[:60] or "analysis"


def to_json(results: dict) -> bytes:
    return json.dumps(results, ensure_ascii=False, indent=2).encode("utf-8")


def to_csv(results: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["category", "start_s", "end_s", "label", "value", "confidence"])
    ov = results.get("overview", {})
    tempo, meter, key = results.get("tempo") or {}, results.get("meter") or {}, results.get("key") or {}
    w.writerow(["overview", "", "", "tempo_bpm", tempo.get("bpm"), tempo.get("confidence")])
    w.writerow(["overview", "", "", "alternative_bpm", tempo.get("alternative_bpm"), ""])
    w.writerow(["overview", "", "", "meter", meter.get("signature") or "undetermined", meter.get("confidence")])
    w.writerow(["overview", "", "", "key", key.get("key"), key.get("confidence")])
    w.writerow(["overview", "", "", "duration_s", ov.get("duration"), ""])
    loud = results.get("loudness") or {}
    for k in ("integrated_lufs", "true_peak_dbtp", "loudness_range_lu", "dynamic_range_db"):
        w.writerow(["loudness", "", "", k, loud.get(k), ""])
    prog = (results.get("progression") or {}).get("main")
    if prog:
        w.writerow(["progression", "", "", " - ".join(prog["chords"]), " - ".join(prog.get("numerals") or []), prog.get("confidence")])
    for s in (results.get("structure") or {}).get("sections", []):
        w.writerow(["section", s["start"], s["end"], s["display_label"], s["group"], s["confidence"]])
    for c in (results.get("chords") or {}).get("items", []):
        w.writerow(["chord", c["start"], c["end"], c["chord"], c.get("quality"), c["confidence"]])
    for k in key.get("changes") or []:
        w.writerow(["key_change", k["start"], k["end"], k["key"], "", k["confidence"]])
    for s in tempo.get("sections") or []:
        w.writerow(["tempo_section", s["start"], s["end"], "bpm", s["bpm"], ""])
    rhythm = results.get("rhythm") or {}
    downbeats = set(rhythm.get("downbeats") or [])
    for b in rhythm.get("beats") or []:
        w.writerow(["beat", b, "", "downbeat" if b in downbeats else "beat", "", ""])
    for e in (results.get("pitch") or {}).get("events", []):
        w.writerow(["pitch_event", e["start"], e["end"], e["note"], e["hz"], ""])
    return buf.getvalue().encode("utf-8-sig")


def to_text(results: dict) -> str:
    md = results.get("metadata") or {}
    tempo, meter, key = results.get("tempo") or {}, results.get("meter") or {}, results.get("key") or {}
    chords, prog = results.get("chords") or {}, results.get("progression") or {}
    loud, pitch, spec = results.get("loudness") or {}, results.get("pitch") or {}, results.get("spectrum") or {}
    lines = [
        "SONGSCOPE — TECHNICAL MUSIC ANALYSIS",
        "=" * 44,
        f"Title:     {md.get('title') or '—'}",
        f"Artist:    {md.get('artist') or '—'}",
        f"Album:     {md.get('album') or '—'}",
        f"Duration:  {_t(md.get('duration'))}",
        f"Format:    {md.get('format') or '—'} · {md.get('sample_rate') or '—'} Hz · {md.get('channels') or '—'} ch"
        + (f" · {md['bit_depth']}-bit" if md.get("bit_depth") else ""),
        "",
        "SUMMARY",
        (results.get("summary") or {}).get("text", ""),
        "",
        "Results are probabilistic estimates. Confidence is shown for every result.",
        "",
        "TEMPO & METER",
        f"  Tempo:            {tempo.get('bpm') or 'undetermined'} BPM ({tempo.get('category') or '—'}) — {_pct(tempo.get('confidence'))} [{tempo.get('confidence_level')}]",
        f"  Alternative:      {tempo.get('alternative_bpm') or '—'} BPM ({tempo.get('alternative_relation') or '—'})",
        f"  Tempo stability:  {_pct(tempo.get('stability'))}",
        f"  Meter:            {meter.get('signature') or 'Could not be determined reliably'}"
        + (f" — {_pct(meter.get('confidence'))} [{meter.get('confidence_level')}]" if meter.get("signature") else ""),
        "",
        "KEY & HARMONY",
        f"  Key:              {key.get('key') or 'No reliable key detected'} — {_pct(key.get('confidence'))} [{key.get('confidence_level')}]",
        f"  Alternative key:  {key.get('alternative_key') or '—'} ({key.get('alternative_relation') or '—'})",
        f"  Tonic:            {key.get('tonic') or '—'}   Most prominent pitch class: {key.get('most_prominent_pitch_class') or '—'}",
        f"  Tuning:           A4 = {key.get('reference_a4_hz') or '—'} Hz ({key.get('tuning_cents') or 0:+} cents)",
    ]
    if prog.get("main"):
        m = prog["main"]
        lines += [f"  Main progression: {' -> '.join(m['chords'])}", f"  Roman numerals:   {' - '.join(m.get('numerals') or [])}"]
    lines += [f"  Chord changes/min: {chords.get('changes_per_minute') or '—'}   Chord recognition: {_pct(chords.get('confidence'))}", ""]
    lines.append("STRUCTURE (labels inferred from acoustic repetition, not lyrics)")
    for s in (results.get("structure") or {}).get("sections", []):
        lines.append(f"  {_t(s['start']):>7}  {s['display_label']:<22} group {s['group']}  {_pct(s['confidence'])}")
    lines += ["", "CHORDS"]
    for c in chords.get("items", []):
        if c["chord"] != "N":
            lines.append(f"  {_t(c['start']):>7} – {_t(c['end']):>7}  {c['chord']:<8} {_pct(c['confidence'])}")
    lines += [
        "",
        "PITCH",
        f"  Range:            {pitch.get('lowest_note') or '—'} – {pitch.get('highest_note') or '—'} ({pitch.get('range_description') or '—'})",
        f"  Most frequent:    {pitch.get('most_frequent_note') or '—'}   Confidence: {_pct(pitch.get('confidence'))}",
        "",
        "LOUDNESS",
        f"  Integrated:       {loud.get('integrated_lufs')} LUFS",
        f"  True peak:        {loud.get('true_peak_dbtp')} dBTP",
        f"  Loudness range:   {loud.get('loudness_range_lu')} LU",
        f"  Dynamic range:    {loud.get('dynamic_range_db')} dB",
        "",
        "SPECTRUM",
        f"  Character:        {(spec.get('summary') or {}).get('brightness') or '—'}",
    ]
    for b in spec.get("bands") or []:
        lines.append(f"  {b['name']:<10} {b['energy_share'] * 100:5.1f}% of energy")
    if results.get("warnings"):
        lines += ["", "WARNINGS"] + [f"  • {w}" for w in results["warnings"]]
    return "\n".join(lines) + "\n"


def to_pdf(results: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title="SongScope Analysis")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=20, textColor=colors.HexColor("#1b1530"), alignment=0)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=colors.HexColor("#5b3fd6"), spaceBefore=10)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=colors.HexColor("#666666"))

    def esc(s) -> str:
        # built-in PDF fonts use WinAnsi encoding: map glyphs it lacks to ASCII before escaping
        text = str(s) if s is not None else "—"
        for a, b in (("→", "->"), ("≈", "~"), ("¢", "c"), ("♯", "#"), ("♭", "b")):
            text = text.replace(a, b)
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def table(rows, widths=None):
        t = Table([[Paragraph(esc(c), body) for c in r] for r in rows], colWidths=widths, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#efeafd")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d6d0ea")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return t

    md = results.get("metadata") or {}
    tempo, meter, key = results.get("tempo") or {}, results.get("meter") or {}, results.get("key") or {}
    loud, prog = results.get("loudness") or {}, (results.get("progression") or {}).get("main")
    story = [
        Paragraph("SongScope — Technical Music Analysis", h1),
        Paragraph(esc(f"{md.get('title') or 'Untitled'}" + (f" · {md['artist']}" if md.get("artist") else "")), body),
        Spacer(1, 6),
        Paragraph(esc((results.get("summary") or {}).get("text", "")), body),
        Paragraph("All results are probabilistic estimates; confidence is shown for each.", small),
        Paragraph("Overview", h2),
        table([
            ["Result", "Value", "Confidence"],
            ["Tempo", f"{tempo.get('bpm') or 'Undetermined'} BPM" + (f" (alt. {tempo['alternative_bpm']} {tempo.get('alternative_relation')})" if tempo.get("alternative_bpm") else ""), f"{_pct(tempo.get('confidence'))} · {tempo.get('confidence_level')}"],
            ["Meter", meter.get("signature") or "Could not be determined reliably", f"{_pct(meter.get('confidence'))} · {meter.get('confidence_level')}"],
            ["Key", key.get("key") or "No reliable key", f"{_pct(key.get('confidence'))} · {key.get('confidence_level')}"],
            ["Alternative key", key.get("alternative_key"), ""],
            ["Main progression", " → ".join(prog["chords"]) + "  (" + " – ".join(prog.get("numerals") or []) + ")" if prog else "—", _pct(prog.get("confidence")) if prog else ""],
            ["Duration", _t(md.get("duration")), "detected"],
            ["Integrated loudness", f"{loud.get('integrated_lufs')} LUFS · TP {loud.get('true_peak_dbtp')} dBTP · LRA {loud.get('loudness_range_lu')} LU", "detected"],
        ], [38 * mm, 100 * mm, 36 * mm]),
        Paragraph("Song structure (inferred labels)", h2),
        table([["Start", "End", "Section", "Group", "Confidence"]] + [
            [_t(s["start"]), _t(s["end"]), s["display_label"], s["group"], _pct(s["confidence"])]
            for s in (results.get("structure") or {}).get("sections", [])
        ]),
        Paragraph("Chords", h2),
    ]
    chord_rows = [[_t(c["start"]), _t(c["end"]), c["chord"], _pct(c["confidence"])]
                  for c in (results.get("chords") or {}).get("items", []) if c["chord"] != "N"]
    story.append(table([["Start", "End", "Chord", "Confidence"]] + chord_rows[:250]))
    if len(chord_rows) > 250:
        story.append(Paragraph(f"… {len(chord_rows) - 250} more chords in the CSV/JSON export.", small))
    if results.get("warnings"):
        story += [Paragraph("Warnings", h2)] + [Paragraph(esc("• " + w), body) for w in results["warnings"]]
    doc.build(story)
    return buf.getvalue()
