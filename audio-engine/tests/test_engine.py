"""Accuracy tests against synthetic songs with exact ground truth."""

import numpy as np
import pytest

from songscope_engine import synth, theory
from songscope_engine.chords import detect_chords
from songscope_engine.decode import load_signal, probe
from songscope_engine.features import compute_harmonic_features
from songscope_engine.key import analyze_key
from songscope_engine.loudness import analyze_loudness
from songscope_engine.meter import analyze_meter
from songscope_engine.pitch import analyze_pitch
from songscope_engine.pipeline import run_analysis
from songscope_engine.tempo import analyze_tempo


def _chord_accuracy(raw, truth) -> float:
    ok = n = 0
    for t in np.arange(0, truth[-1]["end"], 0.1):
        tr = next((c["chord"] for c in truth if c["start"] <= t < c["end"]), None)
        est = next((c for c in raw if c.start <= t < c.end), None)
        if tr is None or est is None:
            continue
        r, q = synth.parse_chord(tr)
        n += 1
        if est.root is not None:
            ok += est.root == r and theory.simplify_quality(est.quality) == theory.simplify_quality(q)
    return ok / n


# --- tempo -------------------------------------------------------------------------------

@pytest.mark.parametrize("fixture,bpm", [("pop_song", 124.0), ("waltz_song", 150.0), ("minor_song", 96.0)])
def test_tempo_detection(request, fixture, bpm):
    path, _ = request.getfixturevalue(fixture)
    tempo, rhythm, _ = analyze_tempo(load_signal(path))
    assert abs(tempo["bpm"] - bpm) / bpm < 0.02
    assert tempo["confidence_level"] == "high"
    assert tempo["alternatives"], "half/double-time alternative should be exposed"
    assert rhythm["beat_count"] > 20


def test_tempo_has_alternative_interpretation(pop_song):
    tempo, _, _ = analyze_tempo(load_signal(pop_song[0]))
    rels = {a["relation"]: a["bpm"] for a in tempo["alternatives"]}
    assert rels["half-time"] == pytest.approx(62.0, rel=0.02)
    assert rels["double-time"] == pytest.approx(248.0, rel=0.02)


def test_noise_has_low_rhythm_confidence(noise_file):
    tempo, _, _ = analyze_tempo(load_signal(noise_file))
    assert tempo["bpm"] is None or tempo["confidence"] < 0.5


# --- meter -------------------------------------------------------------------------------

@pytest.mark.parametrize("fixture,signature", [("pop_song", "4/4"), ("waltz_song", "3/4"), ("minor_song", "4/4")])
def test_meter_detection(request, fixture, signature):
    path, spec = request.getfixturevalue(fixture)
    sig = load_signal(path)
    _, _, rhythm = analyze_tempo(sig)
    meter, downbeats, _ = analyze_meter(rhythm, compute_harmonic_features(sig))
    assert meter["reliable"] and meter["signature"] == signature
    bar = spec.beats_per_bar * 60 / spec.bpm
    offsets = [abs(((d + bar / 2) % bar) - bar / 2) for d in downbeats]
    assert np.median(offsets) < 0.08, "downbeats should align with bar lines"


def test_meter_unreliable_is_not_reported_as_fact(noise_file):
    sig = load_signal(noise_file)
    _, _, rhythm = analyze_tempo(sig)
    meter, _, _ = analyze_meter(rhythm, compute_harmonic_features(sig))
    if not meter["reliable"]:
        assert meter["signature"] is None
        assert "could not be determined" in meter["message"]


# --- key & chords ------------------------------------------------------------------------

@pytest.mark.parametrize("fixture,key", [("pop_song", "E Major"), ("waltz_song", "G Major"), ("minor_song", "A Minor")])
def test_key_and_chords(request, fixture, key):
    path, spec = request.getfixturevalue(fixture)
    sig = load_signal(path)
    _, _, rhythm = analyze_tempo(sig)
    harm = compute_harmonic_features(sig)
    raw = detect_chords(harm, rhythm, sig.duration)
    key_block, ctx = analyze_key(harm, raw, sig.duration)
    assert key_block["key"] == key
    assert key_block["confidence"] >= 0.5
    assert _chord_accuracy(raw, spec.chords_truth) >= 0.9


def test_tonic_differs_from_most_prominent_pitch(minor_song):
    sig = load_signal(minor_song[0])
    _, _, rhythm = analyze_tempo(sig)
    harm = compute_harmonic_features(sig)
    key_block, _ = analyze_key(harm, detect_chords(harm, rhythm, sig.duration), sig.duration)
    assert key_block["tonic"] == "A"
    assert key_block["most_prominent_pitch_class"] in theory.SHARP_NAMES


def test_roman_numerals():
    e = theory.SHARP_NAMES.index("E")
    assert [theory.roman_numeral((e + d) % 12, q, e, "major") for d, q in ((0, "maj"), (7, "maj"), (9, "min"), (5, "maj"))] == ["I", "V", "vi", "IV"]
    a = theory.SHARP_NAMES.index("A")
    assert theory.roman_numeral((a + 7) % 12, "maj", a, "minor") == "V"
    assert theory.roman_numeral((a + 10) % 12, "maj", a, "major") == "bVII"
    assert theory.key_name(10, "major") == "Bb Major"


# --- pitch & loudness --------------------------------------------------------------------

def test_pitch_on_monophonic_tone(tmp_path):
    y = synth.sine(440.0, 4.0)
    block = analyze_pitch(y, synth.SR, source="vocals")
    assert block["most_frequent_note"] == "A4"
    assert abs(block["fundamental_hz_median"] - 440.0) < 3


def test_loudness_against_reference(pop_song):
    import pyloudnorm as pyln

    sig = load_signal(pop_song[0])
    block = analyze_loudness(sig)
    ref = pyln.Meter(sig.sr_full).integrated_loudness(sig.stereo.T.astype(np.float64))
    assert block["integrated_lufs"] == pytest.approx(ref, abs=0.1)
    assert block["true_peak_dbtp"] >= block["sample_peak_dbfs"] - 0.05
    st = [v for v in block["short_term"]["lufs"] if v is not None]
    assert abs(np.median(st) - ref) < 3


def test_full_sine_loudness(tmp_path):
    import soundfile as sf

    # 1 kHz sine, peak 0.1 on both channels: -0.691 + 10*log10(2 * 0.005) ~= -20.7, plus ~+0.7 dB K-weighting gain at 1 kHz
    path = tmp_path / "sine.wav"
    y = synth.sine(1000.0, 10.0, amp=0.1)
    sf.write(path, np.stack([y, y]).T, synth.SR)
    block = analyze_loudness(load_signal(str(path)))
    assert block["integrated_lufs"] == pytest.approx(-20.0, abs=0.5)


# --- full pipeline ------------------------------------------------------------------------

def test_pipeline_structure_and_progression(pop_result, pop_song):
    r = pop_result
    assert r["errors"] == []
    assert r["overview"]["bpm"] == pytest.approx(124, abs=1)
    assert r["overview"]["key"] == "E Major"
    assert r["progression"]["main"]["numerals"] == ["I", "V", "vi", "IV"]
    labels = [s["label"] for s in r["structure"]["sections"]]
    assert labels[0] == "Intro" and labels[-1] == "Outro"
    assert labels.count("Chorus") + labels.count("Final Chorus") == 3
    truth = [s["start"] for s in pop_song[1].sections_truth]
    est = [s["start"] for s in r["structure"]["sections"]]
    assert all(min(abs(t - e) for e in est) < 1.0 for t in truth)


def test_pipeline_drum_pattern(pop_result):
    inst = pop_result["drums"]["instruments"]
    assert inst["kick"]["pattern"] == "1, 3"
    assert inst["snare"]["pattern"] == "2, 4"
    assert pop_result["drums"]["estimated"] is True


def test_every_major_result_has_confidence(pop_result):
    for key in ("tempo", "meter", "key", "chords", "structure", "pitch", "loudness", "drums", "progression", "harmony"):
        block = pop_result[key]
        assert 0.0 <= block["confidence"] <= 1.0
        assert block["confidence_level"] in ("high", "medium", "low")
        assert block["status"] in ("detected", "estimated", "inferred", "uncertain")


def test_summary_is_grounded(pop_result):
    text = pop_result["summary"]["text"]
    assert "124 BPM" in text and "E Major" in text and "4/4" in text


def test_probe_rejects_non_audio(tmp_path):
    from songscope_engine.errors import EngineError

    bad = tmp_path / "fake.mp3"
    bad.write_bytes(b"this is not audio" * 100)
    with pytest.raises(EngineError):
        probe(str(bad))


def test_result_matches_shared_schema(pop_result):
    import json
    from pathlib import Path

    jsonschema = pytest.importorskip("jsonschema")
    schema_path = Path(__file__).resolve().parents[2] / "shared" / "analysis-result.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(json.loads(json.dumps(pop_result)), schema)
