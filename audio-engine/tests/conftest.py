import os

import numpy as np
import pytest
import soundfile as sf

from songscope_engine import synth


@pytest.fixture(scope="session")
def sample_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("samples")


def _render(sample_dir, name, spec):
    path = os.path.join(sample_dir, f"{name}.wav")
    stereo, spec = synth.render(spec)
    if not os.path.exists(path):
        sf.write(path, stereo.T, synth.SR, subtype="PCM_16")
    return path, spec


@pytest.fixture(scope="session")
def pop_song(sample_dir):
    return _render(sample_dir, "pop_e_major_124", synth.pop_song_e_major())


@pytest.fixture(scope="session")
def waltz_song(sample_dir):
    return _render(sample_dir, "waltz_g_major_150", synth.waltz_g_major())


@pytest.fixture(scope="session")
def minor_song(sample_dir):
    return _render(sample_dir, "minor_a_96", synth.minor_song_a())


@pytest.fixture(scope="session")
def pop_result(pop_song, tmp_path_factory):
    from songscope_engine.pipeline import run_analysis

    return run_analysis(pop_song[0], str(tmp_path_factory.mktemp("work")))


@pytest.fixture(scope="session")
def noise_file(sample_dir):
    path = os.path.join(sample_dir, "noise.wav")
    rng = np.random.default_rng(0)
    sf.write(path, (0.2 * rng.standard_normal((synth.SR * 20, 2))).astype(np.float32), synth.SR)
    return path
