"""Domain logic shared by routers and the job worker."""
from __future__ import annotations

import os
import random
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audio as A
from .config import get_settings
from .models import AudioSegment, VoiceoverProject, VoiceProfile, VoiceSample
from .providers import SynthesisParams, VoiceArtifact, get_provider
from .storage import storage
from .text import apply_pronunciations, segment_script

DEFAULT_PROJECT_SETTINGS: dict[str, Any] = {
    "speed": 1.0,
    "pitch_semitones": 0.0,
    "pause_ms": 350,
    "paragraph_pause_ms": 900,
    "language": None,  # None = voice profile language
    "temperature": None,  # None = provider default
    "pronunciations": [],
    "seed": None,
}
# settings whose change invalidates already generated audio
AUDIO_AFFECTING = {"speed", "pitch_semitones", "language", "temperature", "pronunciations", "seed"}


def owned(db: Session, model, obj_id: str, user_id: str):
    obj = db.get(model, obj_id)
    if obj is None or getattr(obj, "user_id", None) != user_id:
        raise HTTPException(404, f"{model.__name__} not found")
    return obj


def owned_segment(db: Session, segment_id: str, user_id: str) -> AudioSegment:
    seg = db.get(AudioSegment, segment_id)
    if seg is None:
        raise HTTPException(404, "Segment not found")
    owned(db, VoiceoverProject, seg.project_id, user_id)
    return seg


def project_settings(project: VoiceoverProject) -> dict[str, Any]:
    s = {**DEFAULT_PROJECT_SETTINGS, **(project.settings or {})}
    if s["seed"] is None:
        s["seed"] = random.randint(1, 2**31 - 1)
    return s


# ------------------------------------------------------------------ samples
def load_sample_audio(sample: VoiceSample) -> np.ndarray:
    audio, sr = A.read_wav_bytes(storage.get_secure(sample.storage_key))
    if sample.trim_start_s is not None or sample.trim_end_s is not None:
        start = int((sample.trim_start_s or 0) * sr)
        end = int((sample.trim_end_s or audio.size / sr) * sr)
        audio = audio[start:end]
    return audio


def cloning_input(sample: VoiceSample) -> np.ndarray:
    """Trimmed, loudness-normalised reference (≤30 s) used to build the voice."""
    audio = load_sample_audio(sample)
    audio = A.trim_silence(audio, A.WORK_SR, pad_ms=100)
    audio = audio[: A.WORK_SR * 30]
    return A.normalize_loudness(audio, -20.0)


# ------------------------------------------------------------------ voice state
def voice_state_key(profile: VoiceProfile, language: str) -> str:
    return f"voices/{profile.user_id}/{profile.id}/{profile.provider}_{language}.state.enc"


def ensure_voice(db: Session, profile: VoiceProfile, language: str) -> VoiceArtifact:
    """Return the provider voice for `language`, creating it from the stored sample if needed."""
    provider = get_provider(profile.provider)
    key = voice_state_key(profile, language)
    if not storage.exists(key):
        sample = db.scalars(select(VoiceSample).where(VoiceSample.voice_profile_id == profile.id)).first()
        if sample is None:
            raise HTTPException(409, "Voice profile has no reference sample")
        ref = cloning_input(sample)
        fd, tmp = tempfile.mkstemp(suffix=".wav", dir=get_settings().data_dir / "tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(A.to_wav_bytes(ref))
            artifact = provider.create_voice(Path(tmp), language=language, name=profile.name)
        finally:
            os.remove(tmp)
        storage.put_secure(key, artifact.data or b"")
    data = storage.get_secure(key)
    return VoiceArtifact(data=data, meta={"language": language, "cache_key": f"{profile.id}:{language}"})


def delete_voice_states(profile: VoiceProfile) -> None:
    provider = get_provider(profile.provider)
    for lang in provider.capabilities().languages:
        storage.delete(voice_state_key(profile, lang))
    if hasattr(provider, "forget"):
        provider.forget(f"{profile.id}:")


def synthesize_text(
    db: Session, profile: VoiceProfile, text: str, settings: dict[str, Any], seed: int | None
) -> tuple[np.ndarray, int, dict[str, Any]]:
    """Full pipeline for one chunk: pronunciation -> provider TTS -> trim -> speed/pitch -> loudness."""
    if profile.status != "ready":
        raise HTTPException(409, "Voice profile is not ready")
    language = settings.get("language") or profile.language
    provider = get_provider(profile.provider)
    voice = ensure_voice(db, profile, language)
    spoken = apply_pronunciations(text, settings.get("pronunciations") or [])
    params = SynthesisParams(language=language, temperature=settings.get("temperature"), seed=seed)
    audio, sr = provider.synthesize(voice, spoken, params)
    audio = A.trim_silence(audio, sr)
    audio = A.apply_effects(audio, sr, speed=float(settings.get("speed") or 1.0), pitch_semitones=float(settings.get("pitch_semitones") or 0.0))
    audio = A.normalize_loudness(audio, -18.0)
    meta = {
        "provider": provider.id,
        "language": language,
        "spoken_text": spoken,
        "temperature": settings.get("temperature"),
        "speed": settings.get("speed"),
        "pitch_semitones": settings.get("pitch_semitones"),
        "seed": seed,
    }
    return audio, sr, meta


# ------------------------------------------------------------------ segments
def segment_key(project: VoiceoverProject, seg: AudioSegment) -> str:
    return f"projects/{project.user_id}/{project.id}/segments/{seg.id}_t{seg.take}.wav"


def resegment(db: Session, project: VoiceoverProject, content: str) -> None:
    """Re-split the script and reconcile with existing segments, keeping audio for unchanged text."""
    chunks = segment_script(content)
    existing = list(db.scalars(select(AudioSegment).where(AudioSegment.project_id == project.id)))
    by_text: dict[str, list[AudioSegment]] = {}
    for s in sorted(existing, key=lambda s: s.position):
        by_text.setdefault(s.text, []).append(s)
    keep: set[str] = set()
    for pos, ch in enumerate(chunks):
        candidates = by_text.get(ch.text)
        if candidates:
            seg = candidates.pop(0)
            seg.position, seg.paragraph_index = pos, ch.paragraph_index
        else:
            seg = AudioSegment(project_id=project.id, position=pos, paragraph_index=ch.paragraph_index, text=ch.text)
            db.add(seg)
            db.flush()
        keep.add(seg.id)
    for s in existing:
        if s.id not in keep:
            if s.audio_key:
                storage.delete(s.audio_key)
            db.delete(s)


def rebuild_script_from_segments(segments: list[AudioSegment]) -> str:
    paras: list[list[str]] = []
    last = None
    for s in segments:
        if last is None or s.paragraph_index != last:
            paras.append([])
        paras[-1].append(s.text)
        last = s.paragraph_index
    return "\n\n".join(" ".join(p) for p in paras)


def ordered_segments(db: Session, project_id: str) -> list[AudioSegment]:
    return list(db.scalars(select(AudioSegment).where(AudioSegment.project_id == project_id).order_by(AudioSegment.position)))


def build_mix(db: Session, project: VoiceoverProject, segment_ids: list[str] | None = None) -> tuple[np.ndarray, int, list[dict]]:
    """Concatenate ready segments with pauses. Returns audio, sample-rate and a timeline map."""
    st = project_settings(project)
    segs = [s for s in ordered_segments(db, project.id) if segment_ids is None or s.id in segment_ids]
    ready = [s for s in segs if s.status == "ready" and s.audio_key]
    if not ready:
        raise HTTPException(409, "No generated segments to combine yet")
    parts: list[tuple[np.ndarray, int]] = []
    sr = A.WORK_SR
    timeline: list[dict] = []
    t = 0.0
    for i, s in enumerate(ready):
        audio, sr = A.read_wav_bytes(storage.get(s.audio_key))
        nxt = ready[i + 1] if i + 1 < len(ready) else None
        if s.pause_after_ms is not None:
            pause = s.pause_after_ms
        elif nxt is not None and nxt.paragraph_index != s.paragraph_index:
            pause = int(st["paragraph_pause_ms"])
        else:
            pause = int(st["pause_ms"])
        parts.append((audio, pause))
        dur = audio.size / sr
        timeline.append({"segment_id": s.id, "start": round(t, 3), "end": round(t + dur, 3), "pause_after_ms": pause})
        t += dur + (pause / 1000 if nxt is not None else 0)
    return A.concat_with_pauses(parts, sr), sr, timeline


def disclosure_metadata(project: VoiceoverProject, profile: VoiceProfile | None) -> dict[str, str]:
    """Embedded tags marking the file as synthetic speech (responsible-use requirement)."""
    return {
        "title": project.title,
        "comment": "AI-generated synthetic speech (Voice Studio). Voice used with recorded speaker consent.",
        "encoded_by": "Voice Studio",
        "artist": f"Synthetic voice: {profile.name}" if profile else "Synthetic voice",
    }
