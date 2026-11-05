"""API flow tests. The cloning test needs real Pocket TTS voice-cloning weights (HF_TOKEN)."""
import os
import time

import pytest

from .conftest import speech_fixture, tone_wav


def _wait_job(client, auth, job_id, timeout=600):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{job_id}", headers=auth).json()
        if j["status"] in ("succeeded", "failed", "cancelled"):
            return j
        time.sleep(0.5)
    raise TimeoutError(job_id)


def test_auth_required(client):
    assert client.get("/api/voices").status_code == 401


def test_login(client, auth):
    r = client.post("/api/auth/login", json={"email": "tester@example.com", "password": "correct-horse-1"})
    assert r.status_code == 200
    assert client.post("/api/auth/login", json={"email": "tester@example.com", "password": "nope-nope"}).status_code == 401


def test_rejects_bad_upload(client, auth):
    r = client.post("/api/samples", headers=auth, files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_upload_trim_and_quality(client, auth):
    r = client.post("/api/samples", headers=auth, files={"file": ("tone.wav", tone_wav(8), "audio/wav")})
    assert r.status_code == 200, r.text
    s = r.json()
    assert 7.9 < s["duration_s"] < 8.1 and "score" in s["quality"]
    r = client.post(f"/api/samples/{s['id']}/trim", headers=auth, json={"start_s": 1, "end_s": 6})
    assert r.json()["trim_start_s"] == 1 and r.json()["trim_end_s"] == 6
    assert client.get(f"/api/samples/{s['id']}/audio", headers=auth).content[:4] == b"RIFF"


def _consent(client, auth, name="Test User"):
    r = client.post("/api/consents", headers=auth, json={
        "speaker_name": name, "relationship": "self", "typed_signature": name,
        "confirm_identity_or_authorization": True, "confirm_no_impersonation": True, "confirm_disclosure": True})
    assert r.status_code == 200, r.text
    return r.json()


def test_consent_requires_matching_signature(client, auth):
    r = client.post("/api/consents", headers=auth, json={
        "speaker_name": "Jane Doe", "relationship": "self", "typed_signature": "Someone Else",
        "confirm_identity_or_authorization": True, "confirm_no_impersonation": True, "confirm_disclosure": True})
    assert r.status_code == 422


def test_cannot_clone_without_verified_consent(client, auth):
    c = _consent(client, auth)
    s = client.post("/api/samples", headers=auth, files={"file": ("tone.wav", tone_wav(8), "audio/wav")}).json()
    r = client.post("/api/voices", headers=auth, json={"name": "V", "sample_id": s["id"], "consent_id": c["id"]})
    assert r.status_code == 403


def test_other_users_cannot_access(client, auth):
    s = client.post("/api/samples", headers=auth, files={"file": ("tone.wav", tone_wav(6), "audio/wav")}).json()
    r = client.post("/api/auth/register", json={"email": "other@example.com", "name": "Other", "password": "another-pass-1"})
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get(f"/api/samples/{s['id']}/audio", headers=other).status_code == 404


def test_project_segmentation_and_reorder(client, auth):
    content = "First sentence of the script is here. Second sentence follows it.\n\nA new paragraph begins now."
    p = client.post("/api/projects", headers=auth, json={"title": "Demo", "content": content}).json()
    assert p["segment_total"] == 3
    ids = [s["id"] for s in p["segments"]]
    p2 = client.put(f"/api/projects/{p['id']}/segments/order", headers=auth, json={"segment_ids": ids[::-1]}).json()
    assert p2["segments"][0]["text"] == "A new paragraph begins now."
    r = client.post(f"/api/projects/{p['id']}/generate", headers=auth, json={})
    assert r.status_code == 409  # no voice selected


@pytest.mark.skipif(not os.environ.get("HF_TOKEN") and not os.path.exists(".env"), reason="needs Pocket TTS cloning weights")
def test_full_clone_generate_export(client, auth):
    speech = speech_fixture().read_bytes()
    s = client.post("/api/samples", headers=auth, files={"file": ("speech.wav", speech, "audio/wav")}).json()
    assert s["quality"]["usable"], s["quality"]
    c = _consent(client, auth)
    r = client.post(f"/api/consents/{c['id']}/recording", headers=auth, files={"file": ("consent.wav", speech, "audio/wav")})
    assert r.json()["status"] == "verified"
    r = client.post("/api/voices", headers=auth, json={"name": "Test Voice", "sample_id": s["id"], "consent_id": c["id"], "language": "en"})
    assert r.status_code == 200, r.text
    job = _wait_job(client, auth, r.json()["job_id"])
    assert job["status"] == "succeeded", job
    vid = r.json()["voice"]["id"]
    v = client.get(f"/api/voices/{vid}", headers=auth).json()
    assert v["status"] == "ready" and v["has_preview"]

    p = client.post("/api/projects", headers=auth, json={
        "title": "Clone test", "voice_profile_id": vid,
        "content": "Welcome to the studio. This voiceover was generated from a cloned voice.\n\nThanks for listening."}).json()
    r = client.post(f"/api/projects/{p['id']}/generate", headers=auth, json={})
    assert _wait_job(client, auth, r.json()["job_id"])["status"] == "succeeded"
    p = client.get(f"/api/projects/{p['id']}", headers=auth).json()
    assert all(s["status"] == "ready" for s in p["segments"])

    mix = client.get(f"/api/projects/{p['id']}/mix", headers=auth)
    assert mix.status_code == 200 and mix.content[:4] == b"RIFF"
    e = client.post(f"/api/projects/{p['id']}/export", headers=auth, json={"format": "mp3", "bitrate_kbps": 192}).json()
    dl = client.get(f"/api/exports/{e['id']}/download", headers=auth)
    assert dl.content[:3] == b"ID3"
