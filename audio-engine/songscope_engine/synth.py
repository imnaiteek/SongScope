"""Deterministic synthetic songs with known ground truth, for tests and demos.

Renders drums, bass, chord pads and a melody for an arbitrary chord chart, so the analysis
engine can be validated against exact tempo, meter, key, chords and section boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import butter, sosfilt

from .theory import CHORD_QUALITIES, SHARP_NAMES

SR = 44100


def _note_pc(name: str) -> int:
    return SHARP_NAMES.index(name)


def parse_chord(label: str) -> tuple[int, str]:
    root = label[:2] if len(label) > 1 and label[1] in "#b" else label[:1]
    suffix = label[len(root):]
    pc = _note_pc(root) if "b" not in root else (_note_pc(root[0]) - 1) % 12
    quality = {"": "maj", "m": "min", "dim": "dim", "aug": "aug", "7": "7", "maj7": "maj7", "m7": "min7",
               "sus2": "sus2", "sus4": "sus4"}[suffix]
    return pc, quality


@dataclass
class Section:
    label: str
    chords: list[str]  # one chord per bar
    energy: float = 1.0
    drums: bool = True
    hats: str = "8th"  # "8th" | "16th" | "none"
    melody: bool = False
    melody_octave: int = 5


@dataclass
class SongSpec:
    bpm: float
    beats_per_bar: int
    sections: list[Section]
    tonic: str
    mode: str
    subdivision: int = 2
    seed: int = 7
    sections_truth: list[dict] = field(default_factory=list)
    chords_truth: list[dict] = field(default_factory=list)


def _env(n: int, attack: float, release: float, sr: int = SR) -> np.ndarray:
    e = np.ones(n)
    a = max(1, int(attack * sr))
    r = max(1, int(release * sr))
    e[:a] = np.linspace(0, 1, min(a, n))[: min(a, n)]
    if r < n:
        e[-r:] *= np.linspace(1, 0, r)
    return e


def _add(buf: np.ndarray, sig: np.ndarray, start: int) -> None:
    end = min(len(buf), start + len(sig))
    if start < len(buf) and end > start:
        buf[start:end] += sig[: end - start]


def _tone(freq: float, dur: float, partials: int = 6, decay: float = 0.6, rng=None) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for k in range(1, partials + 1):
        if freq * k > SR / 2.2:
            break
        out += (decay ** (k - 1)) * np.sin(2 * np.pi * freq * k * t + (rng.uniform(0, 6.28) if rng else 0))
    return out


def _voice(freq: float, dur: float) -> np.ndarray:
    """Vocal-like lead: vibrato (5.5 Hz, +/-30 cents) and a formant-ish harmonic rolloff."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    inst = freq * 2 ** (0.3 * np.sin(2 * np.pi * 5.5 * t) / 12)
    phase = 2 * np.pi * np.cumsum(inst) / SR
    out = np.zeros(n)
    for k in range(1, 7):
        out += (0.6 ** (k - 1)) * np.sin(k * phase)
    return out


def _kick(rng) -> np.ndarray:
    n = int(0.3 * SR)
    t = np.arange(n) / SR
    f = 45 + 90 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 11) * 0.9


def _snare(rng) -> np.ndarray:
    n = int(0.22 * SR)
    t = np.arange(n) / SR
    noise = sosfilt(butter(2, [1200, 6000], btype="band", fs=SR, output="sos"), rng.standard_normal(n))
    return (0.55 * noise * np.exp(-t * 22) + 0.35 * np.sin(2 * np.pi * 185 * t) * np.exp(-t * 30))


def _hat(rng) -> np.ndarray:
    n = int(0.05 * SR)
    t = np.arange(n) / SR
    noise = sosfilt(butter(4, 7000, btype="high", fs=SR, output="sos"), rng.standard_normal(n))
    return 0.22 * noise * np.exp(-t * 90)


def render(spec: SongSpec) -> tuple[np.ndarray, SongSpec]:
    rng = np.random.default_rng(spec.seed)
    beat = 60.0 / spec.bpm
    bar = beat * spec.beats_per_bar
    total_bars = sum(len(s.chords) for s in spec.sections)
    n = int((total_bars * bar + 2.0) * SR)
    drums = np.zeros(n)
    bass = np.zeros(n)
    pads = np.zeros(n)
    lead = np.zeros(n)
    kick, snare, hat = _kick(rng), _snare(rng), _hat(rng)

    spec.sections_truth, spec.chords_truth = [], []
    bar_idx = 0
    for sec in spec.sections:
        sec_start = bar_idx * bar
        for chord in sec.chords:
            t0 = bar_idx * bar
            s0 = int(t0 * SR)
            root, quality = parse_chord(chord)
            spec.chords_truth.append({"start": t0, "end": t0 + bar, "chord": chord})
            # chord pad: voicing around C4
            for iv in CHORD_QUALITIES[quality][0]:
                midi = 48 + ((root + iv) % 12)
                if midi < 52:
                    midi += 12
                f = 440 * 2 ** ((midi - 69) / 12)
                tone = _tone(f, bar, partials=5, decay=0.55, rng=rng) * _env(int(bar * SR), 0.02, 0.08)
                _add(pads, 0.16 * sec.energy * tone, s0)
            # bass: root on every beat, octave 2
            fb = 440 * 2 ** ((36 + root - 69) / 12)
            if fb < 50:
                fb *= 2
            for b in range(spec.beats_per_bar):
                if sec.drums or b == 0:
                    tone = _tone(fb, beat * 0.9, partials=4, decay=0.5) * _env(int(beat * 0.9 * SR), 0.005, 0.05)
                    _add(bass, 0.3 * sec.energy * tone, int((t0 + b * beat) * SR))
            if sec.drums:
                for b in range(spec.beats_per_bar):
                    tb = int((t0 + b * beat) * SR)
                    if spec.beats_per_bar == 3:
                        if b == 0:
                            _add(drums, 1.0 * sec.energy * kick, tb)
                        else:
                            _add(drums, 0.6 * sec.energy * snare, tb)
                    else:
                        if b % 2 == 0:
                            _add(drums, 1.0 * sec.energy * kick, tb)
                        else:
                            _add(drums, 0.8 * sec.energy * snare, tb)
                    if sec.hats != "none":
                        per = {"8th": spec.subdivision, "16th": 2 * spec.subdivision}[sec.hats]
                        for k in range(per):
                            _add(drums, (1.0 if k == 0 else 0.7) * sec.energy * hat, tb + int(k * beat / per * SR))
            if sec.melody:
                scale = [0, 2, 4, 5, 7, 9, 11] if spec.mode == "major" else [0, 2, 3, 5, 7, 8, 10]
                tonic = _note_pc(spec.tonic)
                chord_tones = [(root + iv) % 12 for iv in CHORD_QUALITIES[quality][0]]
                for b in range(spec.beats_per_bar):
                    pc = chord_tones[b % len(chord_tones)] if b % 2 == 0 else (tonic + scale[rng.integers(0, 7)]) % 12
                    midi = 12 * sec.melody_octave + pc
                    f = 440 * 2 ** ((midi - 69) / 12)
                    tone = _voice(f, beat * 0.85) * _env(int(beat * 0.85 * SR), 0.02, 0.06)
                    _add(lead, 0.45 * sec.energy * tone, int((t0 + b * beat) * SR))
            bar_idx += 1
        spec.sections_truth.append({"start": sec_start, "end": bar_idx * bar, "label": sec.label})

    mix = drums * 0.8 + bass + pads + lead
    mix /= np.max(np.abs(mix)) + 1e-9
    mix *= 0.89
    stereo = np.stack([mix, mix]).astype(np.float32)
    return stereo, spec


def pop_song_e_major(bpm: float = 124.0) -> SongSpec:
    verse = ["C#m", "A", "E", "B"] * 2
    chorus = ["E", "B", "C#m", "A"] * 2
    return SongSpec(
        bpm=bpm, beats_per_bar=4, tonic="E", mode="major",
        sections=[
            Section("Intro", ["E", "B", "C#m", "A"], energy=0.45, drums=False),
            Section("Verse", verse, energy=0.6, hats="8th"),
            Section("Chorus", chorus, energy=1.0, hats="16th", melody=True),
            Section("Verse", verse, energy=0.6, hats="8th"),
            Section("Chorus", chorus, energy=1.0, hats="16th", melody=True),
            Section("Bridge", ["F#m", "A", "B", "B"], energy=0.75, hats="none"),
            Section("Chorus", chorus, energy=1.0, hats="16th", melody=True),
            Section("Outro", ["E", "B", "C#m", "A"], energy=0.4, drums=False),
        ],
    )


def waltz_g_major(bpm: float = 150.0) -> SongSpec:
    prog = ["G", "G", "C", "D", "Em", "C", "D", "G"]
    return SongSpec(
        bpm=bpm, beats_per_bar=3, tonic="G", mode="major",
        sections=[Section("A", prog * 3, energy=0.9, hats="8th", melody=True)],
    )


def minor_song_a(bpm: float = 96.0) -> SongSpec:
    prog = ["Am", "Dm", "E", "Am", "F", "Dm", "E", "E"]
    return SongSpec(
        bpm=bpm, beats_per_bar=4, tonic="A", mode="minor",
        sections=[Section("A", prog * 3, energy=0.9, hats="8th", melody=True)],
    )


def sine(freq: float, seconds: float, amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
