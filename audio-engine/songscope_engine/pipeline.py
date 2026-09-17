"""Analysis pipeline orchestration with real, stage-based progress reporting.

Each stage is isolated: a failure is recorded in `errors` and the dependent result is marked
unavailable, while independent stages continue. Only decoding failures are fatal.
"""

from __future__ import annotations

import logging
import os
import time
import traceback
from typing import Callable

import numpy as np

from . import ENGINE_VERSION
from .confidence import unavailable
from .decode import ProbeInfo, load_signal, normalize, probe, read_tags, waveform_peaks
from .errors import CancelledError, EngineError

log = logging.getLogger("songscope.engine")

STAGES: list[tuple[str, str, float]] = [
    ("loading", "Loading audio", 4),
    ("decoding", "Decoding audio", 8),
    ("tempo", "Detecting tempo", 16),
    ("meter", "Detecting meter", 14),
    ("key", "Detecting key", 5),
    ("chords", "Detecting chords", 3),
    ("harmony", "Analyzing harmony", 3),
    ("structure", "Analyzing structure", 8),
    ("pitch", "Analyzing pitch", 16),
    ("dynamics", "Analyzing dynamics", 17),
    ("report", "Preparing report", 5),
]
STAGE_INDEX = {k: i for i, (k, _, _) in enumerate(STAGES)}
_TOTAL_W = sum(w for _, _, w in STAGES)

ProgressFn = Callable[[str, float, float], None]  # (stage_key, stage_fraction, overall_fraction)


def overall_progress(stage: str, fraction: float) -> float:
    i = STAGE_INDEX[stage]
    done = sum(w for _, _, w in STAGES[:i])
    return min(1.0, (done + STAGES[i][2] * max(0.0, min(1.0, fraction))) / _TOTAL_W)


class _Runner:
    def __init__(self, progress: ProgressFn | None, should_cancel: Callable[[], bool] | None):
        self.progress = progress or (lambda *a: None)
        self.should_cancel = should_cancel or (lambda: False)
        self.errors: list[dict] = []
        self.timings: dict[str, float] = {}

    def begin(self, stage: str) -> float:
        if self.should_cancel():
            raise CancelledError("Analysis was cancelled.")
        self.progress(stage, 0.0, overall_progress(stage, 0.0))
        return time.perf_counter()

    def end(self, stage: str, t0: float) -> None:
        self.timings[stage] = round(self.timings.get(stage, 0.0) + time.perf_counter() - t0, 3)
        self.progress(stage, 1.0, overall_progress(stage, 1.0))

    def guard(self, stage: str, label: str, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (CancelledError, MemoryError):
            raise
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("stage %s/%s failed: %s\n%s", stage, label, exc, traceback.format_exc())
            self.errors.append({"stage": stage, "component": label, "message": f"{label} failed: {exc}"})
            return None


def run_analysis(
    source_path: str,
    work_dir: str,
    *,
    source_meta: dict | None = None,
    max_duration: float = 900,
    progress: ProgressFn | None = None,
    should_cancel: Callable[[], bool] | None = None,
    probe_info: ProbeInfo | None = None,
) -> dict:
    run = _Runner(progress, should_cancel)
    started = time.perf_counter()
    source_meta = dict(source_meta or {})

    # --- 1. loading -----------------------------------------------------------------
    t = run.begin("loading")
    info = probe_info or probe(source_path)
    tags = read_tags(source_path)
    run.end("loading", t)

    # --- 2. decoding ----------------------------------------------------------------
    t = run.begin("decoding")
    wav = normalize(source_path, os.path.join(work_dir, "analysis.wav"), info, max_duration=max_duration)
    sig = load_signal(wav)
    run.progress("decoding", 0.6, overall_progress("decoding", 0.6))
    sig.hpss()
    waveform = waveform_peaks(sig)
    run.end("decoding", t)

    metadata = {
        "title": source_meta.get("title") or tags.get("title") or source_meta.get("filename"),
        "artist": source_meta.get("artist") or tags.get("artist"),
        "album": source_meta.get("album") or tags.get("album"),
        "year": tags.get("date") or source_meta.get("upload_date"),
        "genre_tag": tags.get("genre"),
        "duration": round(sig.duration, 3),
        "sample_rate": info.sample_rate,
        "analysis_sample_rate": sig.sr_full,
        "channels": info.channels,
        "bit_depth": info.bit_depth,
        "bit_rate": info.bit_rate,
        "format": source_meta.get("format") or (os.path.splitext(source_path)[1].lstrip(".").upper() or info.format_name),
        "codec": info.codec,
        "file_size": os.path.getsize(source_path),
        "source_type": source_meta.get("source_type", "upload"),
        "filename": source_meta.get("filename"),
        "youtube": source_meta.get("youtube"),
    }

    from .chords import chords_block, detect_chords
    from .drums import analyze_drums
    from .features import compute_harmonic_features
    from .harmony import analyze_harmony
    from .key import analyze_key
    from .loudness import analyze_loudness
    from .meter import analyze_meter
    from .pitch import analyze_pitch
    from .progression import analyze_progressions
    from .spectral import analyze_spectrum
    from .structure import analyze_structure
    from .summary import build_summary
    from .tempo import analyze_tempo
    from .theory import uses_flats

    results: dict = {}

    # --- 3. tempo & beats ---------------------------------------------------------------
    t = run.begin("tempo")
    out = run.guard("tempo", "Tempo detection", analyze_tempo, sig)
    if out is None:
        raise EngineError("Rhythm analysis failed; the audio may be corrupt.")
    results["tempo"], results["rhythm"], rhythm = out
    run.end("tempo", t)

    # --- 4. meter (harmonic features are computed here; meter uses chord-change accents) ---
    t = run.begin("meter")
    harm = run.guard("meter", "Harmonic feature extraction", compute_harmonic_features, sig)
    run.progress("meter", 0.7, overall_progress("meter", 0.7))
    downbeats, bpb, meter_extra = [], None, {}
    if harm is not None:
        m = run.guard("meter", "Meter detection", analyze_meter, rhythm, harm)
        if m:
            results["meter"], downbeats, meter_extra = m
            bpb = meter_extra.get("beats_per_bar")
            results["rhythm"]["downbeats"] = downbeats
    results.setdefault("meter", unavailable("Meter could not be determined."))
    run.end("meter", t)

    # --- 5. key (fuses chroma profiles with a first chord pass) ---------------------------
    t = run.begin("key")
    raw_chords = []
    key_ctx = {"tonic": None, "mode": None}
    if harm is not None:
        raw_chords = run.guard("chords", "Chord detection", detect_chords, harm, rhythm, sig.duration) or []
        k = run.guard("key", "Key detection", analyze_key, harm, raw_chords, sig.duration)
        if k:
            results["key"], key_ctx = k
    results.setdefault("key", unavailable("No reliable key detected."))
    run.end("key", t)

    # --- 6. chords (key-aware spelling, statistics) --------------------------------------
    t = run.begin("chords")
    if harm is not None:
        cb = run.guard("chords", "Chord labelling", chords_block, raw_chords, key_ctx["tonic"], key_ctx["mode"],
                       sig.duration, harm)
        if cb:
            results["chords"] = cb
    results.setdefault("chords", unavailable("Chord recognition was not possible."))
    run.end("chords", t)

    # --- 7. harmony -----------------------------------------------------------------------
    t = run.begin("harmony")
    if harm is not None and results["key"].get("available", True):
        h = run.guard("harmony", "Harmonic analysis", analyze_harmony, harm, results["key"], results["chords"], sig.duration)
        if h:
            results["harmony"] = h
    results.setdefault("harmony", unavailable("Harmonic analysis unavailable."))
    run.end("harmony", t)

    # --- 8. structure + progressions + drums ----------------------------------------------
    t = run.begin("structure")
    if harm is not None:
        s = run.guard("structure", "Structural segmentation", analyze_structure, sig, rhythm, harm, downbeats, bpb)
        if s:
            results["structure"] = s
    results.setdefault("structure", unavailable("Song structure could not be analysed."))
    if results["chords"].get("items"):
        p = run.guard("structure", "Progression analysis", analyze_progressions, results["chords"]["items"],
                      key_ctx["tonic"], key_ctx["mode"], results["structure"].get("sections"),
                      results["chords"].get("confidence", 0.0))
        if p:
            results["progression"] = p
    results.setdefault("progression", unavailable("No chord progression analysis available."))
    d = run.guard("structure", "Drum pattern", analyze_drums, sig.percussive, sig.sr, rhythm.beat_times, downbeats, bpb,
                  results["meter"].get("confidence", 0.0), sig.percussive_ratio())
    results["drums"] = d or unavailable("Drum pattern analysis failed.")
    run.end("structure", t)

    # --- 9. pitch -------------------------------------------------------------------------
    t = run.begin("pitch")
    pb = run.guard("pitch", "Pitch tracking", analyze_pitch, sig.harmonic, sig.sr, "mix", sig.percussive,
                   uses_flats(key_ctx["tonic"], key_ctx["mode"]))
    results["pitch"] = pb or unavailable("Pitch tracking failed.")
    run.end("pitch", t)

    # --- 10. dynamics & spectrum ------------------------------------------------------------
    t = run.begin("dynamics")
    results["loudness"] = run.guard("dynamics", "Loudness measurement", analyze_loudness, sig) or unavailable("Loudness measurement failed.")
    run.progress("dynamics", 0.5, overall_progress("dynamics", 0.5))
    results["spectrum"] = run.guard("dynamics", "Spectral analysis", analyze_spectrum, sig) or unavailable("Spectral analysis failed.")
    run.end("dynamics", t)

    # --- 11. report -------------------------------------------------------------------------
    t = run.begin("report")
    report = {
        "schema_version": 1,
        "engine_version": ENGINE_VERSION,
        "metadata": metadata,
        **results,
        "waveform": waveform,
        "stems": None,
    }
    report["summary"] = run.guard("report", "Summary", build_summary, report) or {"text": "", "sentences": [], "highlights": []}
    report["overview"] = _overview(report)
    report["errors"] = run.errors
    report["warnings"] = _warnings(report)
    run.end("report", t)
    report["timings"] = {**run.timings, "total": round(time.perf_counter() - started, 3)}
    if wav != source_path and os.path.exists(wav):
        try:
            os.remove(wav)
        except OSError:
            pass
    return _jsonable(report)


def _overview(r: dict) -> dict:
    core = [r.get(k) or {} for k in ("tempo", "key", "meter", "chords")]
    confs = [b.get("confidence", 0.0) for b in core]
    overall = float(np.mean(confs)) if confs else 0.0
    from .confidence import level

    return {
        "bpm": (r.get("tempo") or {}).get("bpm"),
        "key": (r.get("key") or {}).get("key"),
        "meter": (r.get("meter") or {}).get("signature"),
        "duration": r["metadata"]["duration"],
        "integrated_lufs": (r.get("loudness") or {}).get("integrated_lufs"),
        "overall_confidence": round(overall, 3),
        "overall_confidence_level": level(overall),
    }


def _warnings(r: dict) -> list[str]:
    out = []
    for key in ("tempo", "meter", "key", "chords", "structure", "pitch", "drums", "progression"):
        b = r.get(key) or {}
        if b.get("message") and b.get("confidence_level") == "low":
            out.append(f"{key.capitalize()}: {b['message']}")
    return out


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return v if np.isfinite(v) else None
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    if isinstance(obj, np.ndarray):
        return _jsonable(obj.tolist())
    return obj
