"""Render the synthetic test songs (with ground truth) into samples/.

Usage:  python scripts/generate_samples.py
All audio is generated from scratch, so there are no licensing concerns.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "audio-engine"))

from songscope_engine import synth  # noqa: E402

SONGS = {
    "synth_pop_e_major_124bpm": synth.pop_song_e_major,
    "synth_waltz_g_major_150bpm": synth.waltz_g_major,
    "synth_minor_a_96bpm": synth.minor_song_a,
}


def main() -> None:
    out = ROOT / "samples"
    out.mkdir(exist_ok=True)
    for name, factory in SONGS.items():
        stereo, spec = synth.render(factory())
        sf.write(out / f"{name}.wav", stereo.T, synth.SR, subtype="PCM_16")
        truth = {
            "bpm": spec.bpm,
            "meter": f"{spec.beats_per_bar}/4",
            "key": f"{spec.tonic} {'Major' if spec.mode == 'major' else 'Minor'}",
            "sections": spec.sections_truth,
            "chords": spec.chords_truth,
        }
        (out / f"{name}.truth.json").write_text(json.dumps(truth, indent=2))
        print(f"wrote samples/{name}.wav ({stereo.shape[1] / synth.SR:.1f} s)")


if __name__ == "__main__":
    main()
