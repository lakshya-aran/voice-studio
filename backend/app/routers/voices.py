"""Audio upload/validation, consent verification, and voice profile management."""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audio as A
from ..config import get_settings
from ..db import get_db
from ..jobs import enqueue
from ..models import GenerationJob, User, VoiceConsent, VoiceoverProject, VoiceProfile, VoiceSample, utcnow
from ..providers import ProviderUnavailable, get_provider
from ..security import audit, get_current_user, limit_generation
from ..services import delete_voice_states, load_sample_audio, owned, synthesize_text
from ..storage import storage

router = APIRouter(tags=["voices"])
settings = get_settings()

CONSENT_VERSION = "2026-11"
CONSENT_STATEMENT = (
    "I, {speaker}, am the person whose voice appears in the submitted recording. I give my explicit consent "
    "for {account} to create a synthetic copy of my voice in Voice Studio and to generate speech with it. "
    "I understand the synthetic voice must not be used to impersonate me or anyone else, to deceive listeners "
    "into believing the audio is a genuine recording, or for fraud, harassment or any unlawful purpose. "
    "I may revoke this consent at any time, which deletes the voice profile."
)
_WORDS = (
    "amber river quiet forest silver morning gentle harbor golden valley crystal meadow bright canyon "
    "velvet lantern hollow summit copper island maple thunder orchard willow cobalt prairie"
).split()


async def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    suffix = Path(file.filename or "audio.wav").suffix.lower() or ".wav"
    if suffix not in A.SUPPORTED_UPLOAD_EXT:
        raise HTTPException(415, f"Unsupported file type {suffix}. Use WAV, MP3, M4A or FLAC.")
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB")
    if not data:
        raise HTTPException(400, "Empty file")
    return data, suffix


# ====================================================================== samples
def sample_out(s: VoiceSample) -> dict:
    return {
        "id": s.id,
        "original_filename": s.original_filename,
        "source": s.source,
        "duration_s": s.duration_s,
        "trim_start_s": s.trim_start_s,
        "trim_end_s": s.trim_end_s,
        "quality": s.quality,
        "voice_profile_id": s.voice_profile_id,
        "created_at": s.created_at,
    }


@router.post("/samples")
async def upload_sample(
    request: Request,
    file: UploadFile = File(...),
    source: Literal["upload", "recording"] = Form("upload"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    data, suffix = await _read_upload(file)
    try:
        audio = A.decode_bytes(data, suffix)
    except A.AudioError as e:
        raise HTTPException(422, f"Could not decode audio: {e}")
    duration = audio.size / A.WORK_SR
    if duration > settings.max_sample_seconds:
        raise HTTPException(422, f"Sample is {duration:.0f}s; maximum is {settings.max_sample_seconds:.0f}s. Trim it first.")
    quality = A.analyze_quality(audio, A.WORK_SR)
    sample = VoiceSample(
        user_id=user.id,
        original_filename=(file.filename or f"recording{suffix}")[:255],
        source=source,
        storage_key="",
        duration_s=round(duration, 3),
        sample_rate=A.WORK_SR,
        quality=quality,
    )
    db.add(sample)
    db.flush()
    sample.storage_key = f"samples/{user.id}/{sample.id}.wav.enc"
    storage.put_secure(sample.storage_key, A.to_wav_bytes(audio))
    db.commit()
    audit("sample.upload", user_id=user.id, target_type="voice_sample", target_id=sample.id, request=request, db=db,
          details={"duration_s": sample.duration_s, "source": source})
    return sample_out(sample)


@router.get("/samples/{sample_id}")
def get_sample(sample_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return sample_out(owned(db, VoiceSample, sample_id, user.id))


@router.get("/samples/{sample_id}/audio")
def sample_audio(sample_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = owned(db, VoiceSample, sample_id, user.id)
    return Response(storage.get_secure(s.storage_key), media_type="audio/wav", headers={"Cache-Control": "private, no-store"})


class TrimIn(BaseModel):
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)


@router.post("/samples/{sample_id}/trim")
def trim_sample(sample_id: str, body: TrimIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Set the selection used for cloning and return a quality report for that selection."""
    s = owned(db, VoiceSample, sample_id, user.id)
    end = min(body.end_s, s.duration_s)
    if end - body.start_s < 1.0:
        raise HTTPException(422, "Selection must be at least 1 second")
    s.trim_start_s, s.trim_end_s = round(body.start_s, 3), round(end, 3)
    s.quality = A.analyze_quality(load_sample_audio(s), A.WORK_SR)
    db.commit()
    return sample_out(s)


# ====================================================================== consent
class ConsentStartIn(BaseModel):
    speaker_name: str = Field(min_length=2, max_length=160)
    speaker_email: str | None = Field(default=None, max_length=255)
    relationship: Literal["self", "authorized_third_party"]
    typed_signature: str = Field(min_length=2, max_length=160)
    confirm_identity_or_authorization: bool
    confirm_no_impersonation: bool
    confirm_disclosure: bool


def consent_out(c: VoiceConsent) -> dict:
    return {
        "id": c.id,
        "speaker_name": c.speaker_name,
        "speaker_email": c.speaker_email,
        "relationship": c.relationship_to_user,
        "statement_version": c.statement_version,
        "statement_text": c.statement_text,
        "consent_phrase": c.consent_phrase,
        "status": c.status,
        "verification": c.verification,
        "has_recording": bool(c.consent_recording_key),
        "created_at": c.created_at,
        "verified_at": c.verified_at,
        "revoked_at": c.revoked_at,
    }


@router.post("/consents")
def start_consent(body: ConsentStartIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not (body.confirm_identity_or_authorization and body.confirm_no_impersonation and body.confirm_disclosure):
        raise HTTPException(422, "All consent confirmations are required")
    if body.relationship == "authorized_third_party" and not body.speaker_email:
        raise HTTPException(422, "Speaker email is required when cloning someone else's voice")
    if body.typed_signature.strip().lower() != body.speaker_name.strip().lower():
        raise HTTPException(422, "The signature must match the speaker's full name")
    phrase = "My voice, my consent: " + " ".join(secrets.choice(_WORDS) for _ in range(4)) + f" {secrets.randbelow(90) + 10}."
    c = VoiceConsent(
        user_id=user.id,
        speaker_name=body.speaker_name.strip(),
        speaker_email=body.speaker_email,
        relationship_to_user=body.relationship,
        statement_version=CONSENT_VERSION,
        statement_text=CONSENT_STATEMENT.format(speaker=body.speaker_name.strip(), account=f"{user.name} <{user.email}>"),
        typed_signature=body.typed_signature.strip(),
        consent_phrase=phrase,
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:512],
    )
    db.add(c)
    db.commit()
    audit("consent.start", user_id=user.id, target_type="voice_consent", target_id=c.id, request=request, db=db,
          details={"relationship": body.relationship})
    return consent_out(c)


@router.post("/consents/{consent_id}/recording")
async def consent_recording(
    consent_id: str,
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The speaker records themself reading the statement + the random phrase. Stored as evidence."""
    c = owned(db, VoiceConsent, consent_id, user.id)
    if c.status == "revoked":
        raise HTTPException(409, "Consent was revoked")
    data, suffix = await _read_upload(file)
    try:
        audio = A.decode_bytes(data, suffix)
    except A.AudioError as e:
        raise HTTPException(422, f"Could not decode audio: {e}")
    q = A.analyze_quality(audio, A.WORK_SR)
    if q["speech_seconds"] < 4 or q["peak_dbfs"] < -35:
        raise HTTPException(422, "The consent recording is too short or too quiet. Read the full statement and phrase aloud.")
    if c.consent_recording_key:
        storage.delete(c.consent_recording_key)
    c.consent_recording_key = f"consents/{user.id}/{c.id}.wav.enc"
    storage.put_secure(c.consent_recording_key, A.to_wav_bytes(audio))
    c.consent_recording_duration_s = round(audio.size / A.WORK_SR, 2)
    c.verification = {
        "method": "signed_attestation+spoken_statement",
        "attestation": {"typed_signature_matches_name": True, "statement_version": c.statement_version},
        "spoken_statement": {"duration_s": c.consent_recording_duration_s, "speech_seconds": q["speech_seconds"],
                             "pitch": A.estimate_pitch(audio, A.WORK_SR)},
        "phrase_transcription_check": "not_performed (no speech recognizer configured)",
    }
    c.status, c.verified_at = "verified", utcnow()
    db.commit()
    audit("consent.verified", user_id=user.id, target_type="voice_consent", target_id=c.id, request=request, db=db)
    return consent_out(c)


@router.get("/consents/{consent_id}")
def get_consent(consent_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return consent_out(owned(db, VoiceConsent, consent_id, user.id))


# ====================================================================== voice profiles
class VoiceCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    language: str = "en"
    accent: str | None = Field(default=None, max_length=64)
    sample_id: str
    consent_id: str
    provider: str | None = None


class VoiceUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    accent: str | None = Field(default=None, max_length=64)


def profile_out(p: VoiceProfile, db: Session) -> dict:
    sample = db.scalars(select(VoiceSample).where(VoiceSample.voice_profile_id == p.id)).first()
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "language": p.language,
        "accent": p.accent,
        "provider": p.provider,
        "status": p.status,
        "error": p.error,
        "analysis": p.analysis,
        "preview_text": p.preview_text,
        "has_preview": bool(p.preview_audio_key),
        "sample": sample_out(sample) if sample else None,
        "consent": {"id": p.consent.id, "speaker_name": p.consent.speaker_name, "status": p.consent.status,
                    "relationship": p.consent.relationship_to_user, "verified_at": p.consent.verified_at} if p.consent else None,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


@router.get("/voices")
def list_voices(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(VoiceProfile).where(VoiceProfile.user_id == user.id).order_by(VoiceProfile.created_at.desc()))
    return [profile_out(p, db) for p in rows]


@router.post("/voices")
def create_voice(body: VoiceCreateIn, request: Request, user: User = Depends(limit_generation), db: Session = Depends(get_db)):
    consent = owned(db, VoiceConsent, body.consent_id, user.id)
    if consent.status != "verified":
        raise HTTPException(403, "Speaker consent must be verified before cloning")
    sample = owned(db, VoiceSample, body.sample_id, user.id)
    if sample.voice_profile_id:
        raise HTTPException(409, "This sample is already used by another voice")
    try:
        provider = get_provider(body.provider)
    except ProviderUnavailable as e:
        raise HTTPException(400, str(e))
    caps = provider.capabilities()
    if body.language not in caps.languages:
        raise HTTPException(422, f"{provider.name} does not support language '{body.language}'")
    selected = (sample.trim_end_s or sample.duration_s) - (sample.trim_start_s or 0)
    if selected < caps.min_sample_seconds:
        raise HTTPException(422, f"Select at least {caps.min_sample_seconds:.0f}s of speech for cloning")
    if not sample.quality.get("usable", True):
        raise HTTPException(422, "Sample quality is too low to clone: " + "; ".join(sample.quality.get("issues", [])))
    profile = VoiceProfile(
        user_id=user.id,
        consent_id=consent.id,
        name=body.name.strip(),
        description=body.description,
        language=body.language,
        accent=body.accent,
        provider=provider.id,
        status="pending",
    )
    db.add(profile)
    db.flush()
    sample.voice_profile_id = profile.id
    job = GenerationJob(user_id=user.id, kind="create_profile", provider=provider.id, voice_profile_id=profile.id,
                        message="Queued")
    enqueue(db, job)
    audit("voice_profile.create", user_id=user.id, target_type="voice_profile", target_id=profile.id, request=request,
          details={"provider": provider.id, "consent_id": consent.id}, db=db)
    return {"voice": profile_out(profile, db), "job_id": job.id}


@router.get("/voices/{voice_id}")
def get_voice(voice_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return profile_out(owned(db, VoiceProfile, voice_id, user.id), db)


@router.patch("/voices/{voice_id}")
def update_voice(voice_id: str, body: VoiceUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = owned(db, VoiceProfile, voice_id, user.id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    return profile_out(p, db)


@router.get("/voices/{voice_id}/preview")
def voice_preview(voice_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = owned(db, VoiceProfile, voice_id, user.id)
    if not p.preview_audio_key:
        raise HTTPException(404, "No preview yet")
    return Response(storage.get(p.preview_audio_key), media_type="audio/wav", headers={"Cache-Control": "private, no-store"})


class TryIn(BaseModel):
    text: str = Field(min_length=1, max_length=400)
    language: str | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch_semitones: float = Field(default=0.0, ge=-12, le=12)
    temperature: float | None = Field(default=None, ge=0.05, le=1.5)


@router.post("/voices/{voice_id}/try")
def try_voice(voice_id: str, body: TryIn, request: Request, user: User = Depends(limit_generation), db: Session = Depends(get_db)):
    """Quick synchronous synthesis for auditioning a voice (short text only)."""
    p = owned(db, VoiceProfile, voice_id, user.id)
    try:
        audio, sr, _ = synthesize_text(db, p, body.text, body.model_dump(), seed=None)
    except ProviderUnavailable as e:
        raise HTTPException(503, str(e))
    audit("voice_profile.try", user_id=user.id, target_type="voice_profile", target_id=p.id, request=request, db=db,
          details={"chars": len(body.text)})
    meta = {"comment": "AI-generated synthetic speech (Voice Studio)"}
    return Response(A.encode(audio, sr, "wav", metadata=meta), media_type="audio/wav")


@router.delete("/voices/{voice_id}")
def delete_voice(voice_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Deletes the voice, its samples, derived voice states and previews. Consent metadata is kept
    (marked revoked) for the audit trail, but the consent recording itself is deleted."""
    p = owned(db, VoiceProfile, voice_id, user.id)
    delete_voice_states(p)
    if p.preview_audio_key:
        storage.delete(p.preview_audio_key)
    for s in db.scalars(select(VoiceSample).where(VoiceSample.voice_profile_id == p.id)):
        storage.delete(s.storage_key)
        db.delete(s)
    consent = p.consent
    for proj in db.scalars(select(VoiceoverProject).where(VoiceoverProject.voice_profile_id == p.id)):
        proj.voice_profile_id = None
    db.delete(p)
    db.flush()
    if consent and not db.scalars(select(VoiceProfile).where(VoiceProfile.consent_id == consent.id)).first():
        if consent.consent_recording_key:
            storage.delete(consent.consent_recording_key)
            consent.consent_recording_key = None
        consent.status, consent.revoked_at = "revoked", utcnow()
    db.commit()
    audit("voice_profile.delete", user_id=user.id, target_type="voice_profile", target_id=voice_id, request=request, db=db)
    return {"ok": True}
