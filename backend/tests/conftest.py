import io
import os

import numpy as np
import pytest
import soundfile as sf


@pytest.fixture(scope="session", autouse=True)
def _env(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    os.environ["SONGSCOPE_DATA_DIR"] = str(data)
    os.environ["SONGSCOPE_DATABASE_URL"] = "sqlite:///" + str(data / "test.db").replace("\\", "/")
    os.environ["SONGSCOPE_EMBEDDED_WORKER"] = "false"
    os.environ["SONGSCOPE_MAX_UPLOAD_MB"] = "3"
    os.environ["SONGSCOPE_MAX_DURATION_SECONDS"] = "60"
    os.environ["SONGSCOPE_RATE_LIMIT_PER_MINUTE"] = "0"
    os.environ.pop("ANTHROPIC_API_KEY", None)
    from songscope_api import config, db

    config.get_settings.cache_clear()
    db.reset_engine()
    yield


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from songscope_api.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(scope="session")
def song_wav_bytes():
    """12 s excerpt of the synthetic pop song (E major, 124 BPM)."""
    from songscope_engine import synth

    stereo, _ = synth.render(synth.pop_song_e_major())
    clip = stereo[:, 23 * synth.SR : 35 * synth.SR]
    buf = io.BytesIO()
    sf.write(buf, clip.T, synth.SR, format="WAV", subtype="PCM_16")
    return buf.getvalue()


@pytest.fixture()
def tone_wav_bytes():
    t = np.arange(44100 * 3) / 44100
    y = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, np.stack([y, y]).T, 44100, format="WAV", subtype="PCM_16")
    return buf.getvalue()
