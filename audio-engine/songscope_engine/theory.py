"""Music-theory helpers: note naming, key spelling, chord vocabulary, Roman numerals."""

from __future__ import annotations

import math

import numpy as np

SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

# Keys conventionally written with flats.
_FLAT_MAJOR_TONICS = {5, 10, 3, 8, 1, 6}  # F Bb Eb Ab Db Gb
_FLAT_MINOR_TONICS = {2, 7, 0, 5, 10, 3}  # Dm Gm Cm Fm Bbm Ebm

MAJOR_SCALE = [0, 2, 4, 5, 7, 9, 11]
NATURAL_MINOR_SCALE = [0, 2, 3, 5, 7, 8, 10]

# Chord vocabulary: quality -> (intervals, suffix). Deliberately conservative.
CHORD_QUALITIES: dict[str, tuple[tuple[int, ...], str]] = {
    "maj": ((0, 4, 7), ""),
    "min": ((0, 3, 7), "m"),
    "dim": ((0, 3, 6), "dim"),
    "aug": ((0, 4, 8), "aug"),
    "sus2": ((0, 2, 7), "sus2"),
    "sus4": ((0, 5, 7), "sus4"),
    "7": ((0, 4, 7, 10), "7"),
    "maj7": ((0, 4, 7, 11), "maj7"),
    "min7": ((0, 3, 7, 10), "m7"),
}


def uses_flats(tonic_pc: int | None, mode: str | None) -> bool:
    if tonic_pc is None:
        return False
    if mode == "minor":
        return tonic_pc in _FLAT_MINOR_TONICS
    return tonic_pc in _FLAT_MAJOR_TONICS


def pc_name(pc: int, flats: bool = False) -> str:
    return (FLAT_NAMES if flats else SHARP_NAMES)[int(pc) % 12]


def key_name(tonic_pc: int, mode: str) -> str:
    flats = uses_flats(tonic_pc, mode)
    return f"{pc_name(tonic_pc, flats)} {'Major' if mode == 'major' else 'Minor'}"


def hz_to_midi(hz: float | np.ndarray) -> float | np.ndarray:
    return 69.0 + 12.0 * np.log2(np.asarray(hz, dtype=float) / 440.0)


def midi_to_hz(midi: float | np.ndarray) -> float | np.ndarray:
    return 440.0 * 2.0 ** ((np.asarray(midi, dtype=float) - 69.0) / 12.0)


def midi_to_note(midi: float, flats: bool = False) -> str:
    m = int(round(float(midi)))
    return f"{pc_name(m % 12, flats)}{m // 12 - 1}"


def hz_to_note(hz: float, flats: bool = False) -> str | None:
    if hz is None or not math.isfinite(hz) or hz <= 0:
        return None
    return midi_to_note(float(hz_to_midi(hz)), flats)


def describe_interval(semitones: int) -> str:
    octaves, rest = divmod(max(0, int(semitones)), 12)
    parts = []
    if octaves:
        parts.append(f"{octaves} octave{'s' if octaves != 1 else ''}")
    if rest or not octaves:
        parts.append(f"{rest} semitone{'s' if rest != 1 else ''}")
    return " + ".join(parts)


def chord_label(root_pc: int, quality: str, flats: bool = False) -> str:
    return pc_name(root_pc, flats) + CHORD_QUALITIES[quality][1]


def chord_template(root_pc: int, quality: str) -> np.ndarray:
    t = np.zeros(12)
    intervals = CHORD_QUALITIES[quality][0]
    for i, iv in enumerate(intervals):
        # root and fifth slightly emphasised; extensions slightly weaker
        weight = 1.0 if i < 3 else 0.8
        t[(root_pc + iv) % 12] = weight
    return t / np.linalg.norm(t)


def simplify_quality(quality: str) -> str:
    """Collapse extensions to their underlying triad family for pattern mining."""
    return {"7": "maj", "maj7": "maj", "min7": "min"}.get(quality, quality)


_MAJOR_DEGREES = {0: "I", 1: "bII", 2: "II", 3: "bIII", 4: "III", 5: "IV", 6: "#IV", 7: "V", 8: "bVI", 9: "VI", 10: "bVII", 11: "VII"}
_MINOR_DEGREES = {0: "I", 1: "bII", 2: "II", 3: "III", 4: "#III", 5: "IV", 6: "#IV", 7: "V", 8: "VI", 9: "#VI", 10: "VII", 11: "#VII"}


def roman_numeral(root_pc: int, quality: str, tonic_pc: int, mode: str) -> str:
    degree = (root_pc - tonic_pc) % 12
    base = (_MAJOR_DEGREES if mode == "major" else _MINOR_DEGREES)[degree]
    accidental = "".join(ch for ch in base if ch in "b#")
    numeral = base.lstrip("b#")
    if quality in ("min", "min7", "dim"):
        numeral = numeral.lower()
    suffix = {"dim": "°", "aug": "+", "7": "7", "maj7": "maj7", "min7": "7", "sus2": "sus2", "sus4": "sus4"}.get(quality, "")
    return f"{accidental}{numeral}{suffix}"


def is_diatonic(root_pc: int, quality: str, tonic_pc: int, mode: str) -> bool:
    scale = MAJOR_SCALE if mode == "major" else NATURAL_MINOR_SCALE
    pcs = {(tonic_pc + s) % 12 for s in scale}
    intervals = CHORD_QUALITIES[quality][0]
    chord_pcs = {(root_pc + iv) % 12 for iv in intervals}
    if chord_pcs <= pcs:
        return True
    # harmonic-minor dominant (V / V7) is idiomatic in minor keys
    if mode == "minor" and (root_pc - tonic_pc) % 12 == 7 and quality in ("maj", "7"):
        return True
    return False
