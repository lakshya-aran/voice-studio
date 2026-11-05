"""ORM models. Every user-owned row carries user_id so access control is a simple filter."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class VoiceSample(TimestampMixin, Base):
    """An uploaded or recorded audio file (encrypted at rest). Normalised to mono WAV."""

    __tablename__ = "voice_samples"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    voice_profile_id: Mapped[str | None] = mapped_column(ForeignKey("voice_profiles.id", ondelete="SET NULL"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(16))  # "upload" | "recording"
    storage_key: Mapped[str] = mapped_column(String(512))  # normalised wav (encrypted)
    duration_s: Mapped[float] = mapped_column(Float)
    sample_rate: Mapped[int] = mapped_column(Integer)
    trim_start_s: Mapped[float | None] = mapped_column(Float)
    trim_end_s: Mapped[float | None] = mapped_column(Float)
    quality: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class VoiceConsent(TimestampMixin, Base):
    """Evidence that the speaker authorised cloning of their voice."""

    __tablename__ = "voice_consents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    speaker_name: Mapped[str] = mapped_column(String(160))
    speaker_email: Mapped[str | None] = mapped_column(String(255))
    relationship_to_user: Mapped[str] = mapped_column(String(24))  # "self" | "authorized_third_party"
    statement_version: Mapped[str] = mapped_column(String(16))
    statement_text: Mapped[str] = mapped_column(Text)
    typed_signature: Mapped[str] = mapped_column(String(160))
    consent_phrase: Mapped[str] = mapped_column(String(255))  # random phrase the speaker must read aloud
    consent_recording_key: Mapped[str | None] = mapped_column(String(512))
    consent_recording_duration_s: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | verified | revoked
    verification: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VoiceProfile(TimestampMixin, Base):
    __tablename__ = "voice_profiles"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    consent_id: Mapped[str] = mapped_column(ForeignKey("voice_consents.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(16), default="en")
    accent: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    provider_voice_ref: Mapped[str | None] = mapped_column(String(512))  # storage key / remote voice id
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | processing | ready | failed
    error: Mapped[str | None] = mapped_column(Text)
    analysis: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # pitch, rate, etc.
    preview_audio_key: Mapped[str | None] = mapped_column(String(512))
    preview_text: Mapped[str | None] = mapped_column(Text)

    samples: Mapped[list[VoiceSample]] = relationship(foreign_keys=[VoiceSample.voice_profile_id])
    consent: Mapped[VoiceConsent] = relationship()


class Script(TimestampMixin, Base):
    __tablename__ = "scripts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(16), default="en")


class VoiceoverProject(TimestampMixin, Base):
    __tablename__ = "voiceover_projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    script_id: Mapped[str] = mapped_column(ForeignKey("scripts.id", ondelete="CASCADE"))
    voice_profile_id: Mapped[str | None] = mapped_column(ForeignKey("voice_profiles.id", ondelete="SET NULL"))
    # speed, pitch_semitones, pause_ms, paragraph_pause_ms, language, temperature, pronunciations[], seed
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    export_settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    script: Mapped[Script] = relationship()
    voice_profile: Mapped[VoiceProfile | None] = relationship()


class AudioSegment(TimestampMixin, Base):
    """One sentence/chunk of a project's script and its generated take."""

    __tablename__ = "audio_segments"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("voiceover_projects.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    paragraph_index: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    pause_after_ms: Mapped[int | None] = mapped_column(Integer)  # None = use project default
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|queued|generating|ready|failed|stale
    error: Mapped[str | None] = mapped_column(Text)
    audio_key: Mapped[str | None] = mapped_column(String(512))
    duration_s: Mapped[float | None] = mapped_column(Float)
    take: Mapped[int] = mapped_column(Integer, default=0)
    generation_params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class GenerationJob(TimestampMixin, Base):
    __tablename__ = "generation_jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # create_profile | generate_segments | render | export
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued|running|succeeded|failed|cancelled
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    message: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    provider: Mapped[str | None] = mapped_column(String(32))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("voiceover_projects.id", ondelete="CASCADE"), index=True)
    voice_profile_id: Mapped[str | None] = mapped_column(ForeignKey("voice_profiles.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GeneratedAudio(TimestampMixin, Base):
    """A rendered deliverable: full mix or exported segment(s)."""

    __tablename__ = "generated_audios"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("voiceover_projects.id", ondelete="CASCADE"), index=True)
    voice_profile_id: Mapped[str | None] = mapped_column(ForeignKey("voice_profiles.id", ondelete="SET NULL"))
    job_id: Mapped[str | None] = mapped_column(ForeignKey("generation_jobs.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16))  # mix | segment | bundle
    title: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(512))
    format: Mapped[str] = mapped_column(String(8))  # wav | mp3 | zip
    bitrate_kbps: Mapped[int | None] = mapped_column(Integer)
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    duration_s: Mapped[float | None] = mapped_column(Float)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str | None] = mapped_column(String(32))
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[str | None] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
