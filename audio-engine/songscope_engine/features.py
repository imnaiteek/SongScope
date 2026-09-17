"""Shared harmonic features: tuning-aware constant-Q transform and chroma (HPCP-style)."""

from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np

from .decode import AudioSignal

BINS_PER_OCTAVE = 36
N_OCTAVES = 7
FMIN = librosa.note_to_hz("C1")


@dataclass
class HarmonicFeatures:
    chroma: np.ndarray  # (12, T) energy-preserving (not frame-normalised), full range
    chroma_treble: np.ndarray  # (12, T) >= ~C3
    chroma_bass: np.ndarray  # (12, T) ~C1..B2
    frame_energy: np.ndarray  # (T,)
    tuning_cents: float
    frame_rate: float
    tonalness: np.ndarray  # (T,) peakiness of chroma, 0..1


def _fold(C: np.ndarray, start_bin: int, stop_bin: int, tuning_bins: float = 0.0) -> np.ndarray:
    sub = C[start_bin:stop_bin]
    n = sub.shape[0]
    fmin = FMIN * 2 ** (start_bin / BINS_PER_OCTAVE)
    M = librosa.filters.cq_to_chroma(n, bins_per_octave=BINS_PER_OCTAVE, n_chroma=12, fmin=fmin)
    return M @ sub


def compute_harmonic_features(sig: AudioSignal) -> HarmonicFeatures:
    y = sig.harmonic
    tuning = float(librosa.estimate_tuning(y=y, sr=sig.sr, bins_per_octave=12))  # fraction of a semitone
    C = np.abs(
        librosa.cqt(y, sr=sig.sr, hop_length=sig.hop, fmin=FMIN, n_bins=BINS_PER_OCTAVE * N_OCTAVES,
                    bins_per_octave=BINS_PER_OCTAVE, tuning=tuning)
    )
    C = np.log1p(100.0 * C / (C.max() + 1e-12))  # logarithmic compression, as used for HPCP/chroma
    split = BINS_PER_OCTAVE * 2  # C1..B2 = bass register
    bass = _fold(C, 0, split)
    treble = _fold(C, split, C.shape[0])
    full = bass + treble
    energy = C.sum(axis=0)
    norm = full / (full.max(axis=0, keepdims=True) + 1e-12)
    tonalness = 1.0 - (norm.mean(axis=0))  # flat chroma -> low tonalness
    return HarmonicFeatures(
        chroma=full, chroma_treble=treble, chroma_bass=bass, frame_energy=energy,
        tuning_cents=tuning * 100.0, frame_rate=sig.sr / sig.hop, tonalness=np.clip(tonalness, 0, 1),
    )


def unit_columns(X: np.ndarray) -> np.ndarray:
    return X / (np.linalg.norm(X, axis=0, keepdims=True) + 1e-12)
