import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest

# Isolated data dir per test session (must be set before the app is imported)
_TMP = Path(tempfile.mkdtemp(prefix="voicestudio-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["STORAGE_LOCAL_DIR"] = str(_TMP / "storage")
os.environ["GENERATION_RATE_LIMIT_PER_HOUR"] = "1000"

FIXTURES = Path(__file__).parent / "fixtures"


def speech_fixture() -> Path:
    """Real speech from a Pocket TTS stock voice (CC-BY catalog voice), cached on disk."""
    path = FIXTURES / "speech_sample.wav"
    if not path.exists():
        import soundfile as sf
        from pocket_tts import TTSModel

        FIXTURES.mkdir(exist_ok=True)
        model = TTSModel.load_model(language="english")
        state = model.get_state_for_audio_prompt("alba")
        text = ("The morning light spread slowly across the valley. Birds began to sing in the tall trees, "
                "and somewhere in the distance a dog barked twice. It was going to be a beautiful day.")
        audio = model.generate_audio(state, text).numpy()
        sf.write(path, audio, model.sample_rate)
    return path


def tone_wav(seconds: float = 6.0, sr: int = 24000) -> bytes:
    import io

    import soundfile as sf

    t = np.arange(int(seconds * sr)) / sr
    buf = io.BytesIO()
    sf.write(buf, 0.3 * np.sin(2 * np.pi * 180 * t).astype(np.float32), sr, format="WAV")
    return buf.getvalue()


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(scope="session")
def auth(client):
    r = client.post("/api/auth/register", json={"email": "tester@example.com", "name": "Test User", "password": "correct-horse-1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
