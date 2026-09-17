"""Optional source separation (Demucs) and per-stem analysis.

Separation is computationally expensive and requires PyTorch + Demucs (`pip install
songscope-engine[stems]`). It is never part of the basic analysis.
"""

from __future__ import annotations

import os
from typing import Callable

import numpy as np

from .confidence import annotate
from .errors import EngineError

STEMS = ("vocals", "drums", "bass", "other")


def is_available() -> tuple[bool, str | None]:
    try:
        import demucs  # noqa: F401
        import torch  # noqa: F401
    except Exception as exc:  # pragma: no cover - depends on optional install
        return False, f"Stem separation requires PyTorch and Demucs ({type(exc).__name__})."
    return True, None


def _load(path: str, sr: int) -> np.ndarray:
    from . import ffmpeg

    exe = ffmpeg.ffmpeg_path()
    res = ffmpeg.run([exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", path, "-map", "0:a:0",
                      "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"], timeout=600)
    if res.returncode != 0:
        raise EngineError("Could not decode audio for separation.", "decode_failed")
    return np.frombuffer(res.stdout, dtype=np.float32).reshape(-1, 2).T.copy()


def separate(path: str, out_dir: str, model_name: str, progress: Callable[[float, str], None]) -> dict[str, str]:
    ok, reason = is_available()
    if not ok:
        raise EngineError(reason, "stems_unavailable")
    import soundfile as sf
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    progress(0.02, "Loading separation model")
    torch.set_num_threads(max(1, (os.cpu_count() or 2) // 2))
    model = get_model(model_name)
    model.eval()
    progress(0.08, "Decoding audio")
    wav = torch.from_numpy(_load(path, model.samplerate))
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / (ref.std() + 1e-8)
    progress(0.12, "Separating stems (this can take several minutes on CPU)")
    total = wav.shape[-1]

    def on_segment(d: dict) -> None:
        # Demucs reports each processed segment; convert to overall fraction across the model bag
        models = max(1, int(d.get("models", 1)))
        done = min(1.0, (int(d.get("segment_offset", 0)) + model.segment * model.samplerate) / total) \
            if hasattr(model, "segment") else min(1.0, int(d.get("segment_offset", 0)) / total)
        frac = (int(d.get("model_idx_in_bag", 0)) + done) / models
        progress(0.12 + 0.56 * min(1.0, frac), f"Separating stems · {round(frac * 100)}%")

    with torch.no_grad():
        try:
            sources = apply_model(model, wav[None], device="cpu", split=True, overlap=0.25, progress=False,
                                  num_workers=0, callback=on_segment)[0]
        except TypeError:  # older Demucs without the callback argument
            sources = apply_model(model, wav[None], device="cpu", split=True, overlap=0.25, progress=False,
                                  num_workers=0)[0]
    sources = sources * (ref.std() + 1e-8) + ref.mean()
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    for name, src in zip(model.sources, sources):
        p = os.path.join(out_dir, f"{name}.wav")
        sf.write(p, src.numpy().T, model.samplerate, subtype="PCM_16")
        paths[name] = p
    progress(0.7, "Stems separated")
    return paths


def _to_playback(wav_path: str) -> str:
    from . import ffmpeg

    out = wav_path[:-4] + ".m4a"
    res = ffmpeg.run([ffmpeg.ffmpeg_path(), "-nostdin", "-hide_banner", "-loglevel", "error", "-i", wav_path,
                      "-c:a", "aac", "-b:a", "160k", "-y", out], timeout=600)
    return out if res.returncode == 0 else wav_path


def analyze_stems(path: str, out_dir: str, *, model_name: str, progress: Callable[[float, str], None],
                  key_tonic: int | None = None, key_mode: str | None = None, reference_bpm: float | None = None) -> dict:
    from .decode import load_signal
    from .loudness import analyze_loudness
    from .pitch import analyze_pitch
    from .spectral import analyze_spectrum
    from .tempo import analyze_tempo
    from .theory import uses_flats

    paths = separate(path, out_dir, model_name, progress)
    flats = uses_flats(key_tonic, key_mode)
    energies = {}
    out: dict = {"model": model_name, "stems": {}, "audio_available": True}
    for i, name in enumerate([s for s in STEMS if s in paths]):
        progress(0.7 + 0.28 * i / len(paths), f"Analysing {name} stem")
        sig = load_signal(paths[name])
        energies[name] = float(np.mean(sig.stereo.astype(np.float64) ** 2))
        loud = analyze_loudness(sig)
        spec = analyze_spectrum(sig)
        stem: dict = {
            "integrated_lufs": loud.get("integrated_lufs"),
            "rms_dbfs": loud.get("rms_dbfs"),
            "activity": loud["short_term"],
            "spectral_centroid_hz": spec["centroid_hz"]["mean"],
            "brightness": spec["summary"]["brightness"],
            "bands": [{"name": b["name"], "energy_share": b["energy_share"]} for b in spec["bands"]],
        }
        if name in ("vocals", "bass", "other"):
            pb = analyze_pitch(sig.mono, sig.sr, source="vocals" if name != "bass" else "bass", flats=flats)
            stem["pitch"] = {k: pb.get(k) for k in ("lowest_note", "highest_note", "range_description",
                                                     "most_frequent_note", "average_note", "voiced_fraction",
                                                     "confidence", "confidence_level", "message", "contour")}
        if name == "drums":
            tb, rb, _ = analyze_tempo(sig)
            stem["tempo"] = {"bpm": tb.get("bpm"), "confidence": tb.get("confidence"),
                             "confidence_level": tb.get("confidence_level"), "onset_density": rb.get("onset_density")}
        playback = _to_playback(paths[name])
        stem["audio_file"] = os.path.relpath(playback, os.path.dirname(out_dir)).replace("\\", "/")
        if playback != paths[name]:
            os.remove(paths[name])
        out["stems"][name] = stem
    total = sum(energies.values()) or 1.0
    for name, e in energies.items():
        out["stems"][name]["energy_share"] = round(e / total, 4)
    progress(1.0, "Stem analysis complete")
    return annotate(out, 0.7, "estimated",
                    "Stems are model estimates; artefacts and bleed between stems are normal.")
