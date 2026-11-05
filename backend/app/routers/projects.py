"""Scripts, voiceover projects, segments, generation, mixing and export."""
from __future__ import annotations

import io
import re
import zipfile
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audio as A
from ..config import get_settings
from ..db import get_db
from ..jobs import enqueue
from ..models import AudioSegment, GeneratedAudio, GenerationJob, Script, User, VoiceoverProject, VoiceProfile
from ..providers import get_provider
from ..security import audit, get_current_user, limit_generation
from ..services import (
    AUDIO_AFFECTING,
    DEFAULT_PROJECT_SETTINGS,
    build_mix,
    disclosure_metadata,
    ordered_segments,
    owned,
    owned_segment,
    project_settings,
    rebuild_script_from_segments,
    resegment,
)
from ..storage import storage
from ..text import split_paragraphs, word_count

router = APIRouter(tags=["projects"])
settings = get_settings()


# ====================================================================== scripts
class ScriptIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=settings.max_script_chars)
    language: str = "en"


class ScriptPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, max_length=settings.max_script_chars)
    language: str | None = None


def script_out(s: Script) -> dict:
    return {
        "id": s.id, "title": s.title, "content": s.content, "language": s.language,
        "word_count": word_count(s.content), "char_count": len(s.content),
        "paragraph_count": len(split_paragraphs(s.content)), "created_at": s.created_at, "updated_at": s.updated_at,
    }


@router.get("/scripts")
def list_scripts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Script).where(Script.user_id == user.id).order_by(Script.updated_at.desc()))
    return [script_out(s) for s in rows]


@router.post("/scripts")
def create_script(body: ScriptIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = Script(user_id=user.id, **body.model_dump())
    db.add(s)
    db.commit()
    return script_out(s)


@router.get("/scripts/{script_id}")
def get_script(script_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return script_out(owned(db, Script, script_id, user.id))


@router.patch("/scripts/{script_id}")
def update_script(script_id: str, body: ScriptPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = owned(db, Script, script_id, user.id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    for p in db.scalars(select(VoiceoverProject).where(VoiceoverProject.script_id == s.id)):
        resegment(db, p, s.content)
    db.commit()
    return script_out(s)


# ====================================================================== projects
class ProjectSettings(BaseModel):
    speed: float | None = Field(default=None, ge=0.5, le=2.0)
    pitch_semitones: float | None = Field(default=None, ge=-12, le=12)
    pause_ms: int | None = Field(default=None, ge=0, le=5000)
    paragraph_pause_ms: int | None = Field(default=None, ge=0, le=10000)
    language: str | None = None
    temperature: float | None = Field(default=None, ge=0.05, le=1.5)
    pronunciations: list[dict[str, Any]] | None = None
    seed: int | None = None


class ExportSettings(BaseModel):
    format: Literal["wav", "mp3"] = "mp3"
    bitrate_kbps: int = Field(default=192, ge=64, le=320)
    sample_rate: int = Field(default=44100)


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    voice_profile_id: str | None = None
    content: str = Field(default="", max_length=settings.max_script_chars)
    script_id: str | None = None
    settings: ProjectSettings | None = None


class ProjectPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    voice_profile_id: str | None = None
    content: str | None = Field(default=None, max_length=settings.max_script_chars)
    settings: ProjectSettings | None = None
    export_settings: ExportSettings | None = None


def segment_out(s: AudioSegment) -> dict:
    return {
        "id": s.id, "position": s.position, "paragraph_index": s.paragraph_index, "text": s.text,
        "pause_after_ms": s.pause_after_ms, "status": s.status, "error": s.error, "duration_s": s.duration_s,
        "take": s.take, "generation_params": s.generation_params, "updated_at": s.updated_at,
    }


def project_out(p: VoiceoverProject, db: Session, with_segments: bool = True) -> dict:
    segs = ordered_segments(db, p.id)
    counts: dict[str, int] = {}
    for s in segs:
        counts[s.status] = counts.get(s.status, 0) + 1
    active_job = db.scalars(
        select(GenerationJob).where(GenerationJob.project_id == p.id, GenerationJob.status.in_(["queued", "running"]))
        .order_by(GenerationJob.created_at.desc())
    ).first()
    out = {
        "id": p.id, "title": p.title, "voice_profile_id": p.voice_profile_id,
        "voice_name": p.voice_profile.name if p.voice_profile else None,
        "script": script_out(p.script), "settings": {**DEFAULT_PROJECT_SETTINGS, **(p.settings or {})},
        "export_settings": {**ExportSettings().model_dump(), **(p.export_settings or {})},
        "segment_counts": counts, "segment_total": len(segs),
        "duration_s": round(sum(s.duration_s or 0 for s in segs if s.status == "ready"), 2),
        "active_job_id": active_job.id if active_job else None,
        "created_at": p.created_at, "updated_at": p.updated_at,
    }
    if with_segments:
        out["segments"] = [segment_out(s) for s in segs]
    return out


def _check_voice(db: Session, user: User, voice_id: str | None) -> None:
    if voice_id:
        v = owned(db, VoiceProfile, voice_id, user.id)
        if v.status != "ready":
            raise HTTPException(409, "Voice profile is not ready")


def _mark_stale(db: Session, project_id: str) -> None:
    for s in ordered_segments(db, project_id):
        if s.status == "ready":
            s.status = "stale"


@router.get("/projects")
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(VoiceoverProject).where(VoiceoverProject.user_id == user.id).order_by(VoiceoverProject.updated_at.desc()))
    return [project_out(p, db, with_segments=False) for p in rows]


@router.post("/projects")
def create_project(body: ProjectCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check_voice(db, user, body.voice_profile_id)
    if body.script_id:
        script = owned(db, Script, body.script_id, user.id)
    else:
        lang = "en"
        if body.voice_profile_id:
            lang = db.get(VoiceProfile, body.voice_profile_id).language
        script = Script(user_id=user.id, title=body.title, content=body.content, language=lang)
        db.add(script)
        db.flush()
    p = VoiceoverProject(user_id=user.id, title=body.title, script_id=script.id, voice_profile_id=body.voice_profile_id,
                         settings={k: v for k, v in (body.settings.model_dump() if body.settings else {}).items() if v is not None})
    db.add(p)
    db.flush()
    p.settings = project_settings(p)  # pins the seed for consistent takes
    resegment(db, p, script.content)
    db.commit()
    return project_out(p, db)


@router.get("/projects/{project_id}")
def get_project(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return project_out(owned(db, VoiceoverProject, project_id, user.id), db)


@router.patch("/projects/{project_id}")
def update_project(project_id: str, body: ProjectPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = owned(db, VoiceoverProject, project_id, user.id)
    data = body.model_dump(exclude_unset=True)
    if "title" in data:
        p.title = data["title"]
    if "voice_profile_id" in data and data["voice_profile_id"] != p.voice_profile_id:
        _check_voice(db, user, data["voice_profile_id"])
        p.voice_profile_id = data["voice_profile_id"]
        _mark_stale(db, p.id)
    if body.settings is not None:
        new = {k: v for k, v in body.settings.model_dump(exclude_unset=True).items()}
        if "language" in new and new["language"] and p.voice_profile:
            caps = get_provider(p.voice_profile.provider).capabilities()
            if new["language"] not in caps.languages:
                raise HTTPException(422, f"Language '{new['language']}' not supported by this voice's provider")
        old = {**DEFAULT_PROJECT_SETTINGS, **(p.settings or {})}
        merged = {**old, **new}
        if any(old.get(k) != merged.get(k) for k in AUDIO_AFFECTING):
            _mark_stale(db, p.id)
        p.settings = merged
    if body.export_settings is not None:
        p.export_settings = body.export_settings.model_dump()
    if "content" in data:
        p.script.content = data["content"]
        resegment(db, p, data["content"])
    db.commit()
    return project_out(p, db)


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = owned(db, VoiceoverProject, project_id, user.id)
    for s in ordered_segments(db, p.id):
        if s.audio_key:
            storage.delete(s.audio_key)
    for g in db.scalars(select(GeneratedAudio).where(GeneratedAudio.project_id == p.id)):
        storage.delete(g.storage_key)
    script = p.script
    db.delete(p)
    db.flush()
    if not db.scalars(select(VoiceoverProject).where(VoiceoverProject.script_id == script.id)).first():
        db.delete(script)
    db.commit()
    audit("project.delete", user_id=user.id, target_type="project", target_id=project_id, request=request, db=db)
    return {"ok": True}


# ====================================================================== segments
class SegmentPatch(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=1000)
    pause_after_ms: int | None = Field(default=None, ge=-1, le=10000)  # -1 resets to project default


class OrderIn(BaseModel):
    segment_ids: list[str]


@router.patch("/segments/{segment_id}")
def update_segment(segment_id: str, body: SegmentPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    seg = owned_segment(db, segment_id, user.id)
    if body.pause_after_ms is not None:
        seg.pause_after_ms = None if body.pause_after_ms < 0 else body.pause_after_ms
    if body.text is not None and body.text.strip() != seg.text:
        seg.text = body.text.strip()
        if seg.status == "ready":
            seg.status = "stale"
        project = db.get(VoiceoverProject, seg.project_id)
        project.script.content = rebuild_script_from_segments(ordered_segments(db, project.id))
    db.commit()
    return segment_out(seg)


@router.put("/projects/{project_id}/segments/order")
def reorder_segments(project_id: str, body: OrderIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = owned(db, VoiceoverProject, project_id, user.id)
    segs = {s.id: s for s in ordered_segments(db, p.id)}
    if set(body.segment_ids) != set(segs):
        raise HTTPException(422, "segment_ids must contain every segment of the project exactly once")
    for pos, sid in enumerate(body.segment_ids):
        segs[sid].position = pos
    db.flush()
    p.script.content = rebuild_script_from_segments(ordered_segments(db, p.id))
    db.commit()
    return project_out(p, db)


@router.get("/segments/{segment_id}/audio")
def segment_audio(segment_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    seg = owned_segment(db, segment_id, user.id)
    if not seg.audio_key:
        raise HTTPException(404, "Segment has not been generated")
    return Response(storage.get(seg.audio_key), media_type="audio/wav", headers={"Cache-Control": "private, no-store"})


# ====================================================================== generation
class GenerateIn(BaseModel):
    segment_ids: list[str] | None = None  # None = all segments that are not ready
    new_take: bool = False  # regenerate with a different variation


def _start_generation(db: Session, user: User, p: VoiceoverProject, segs: list[AudioSegment], new_take: bool) -> GenerationJob:
    if not p.voice_profile_id:
        raise HTTPException(409, "Select a voice for this project first")
    _check_voice(db, user, p.voice_profile_id)
    if db.scalars(select(GenerationJob).where(GenerationJob.project_id == p.id,
                                              GenerationJob.status.in_(["queued", "running"]))).first():
        raise HTTPException(409, "A generation is already running for this project")
    if not segs:
        raise HTTPException(409, "Nothing to generate")
    for s in segs:
        if new_take and s.audio_key:
            s.take += 1
        s.status, s.error = "queued", None
    job = GenerationJob(user_id=user.id, kind="generate_segments", project_id=p.id, voice_profile_id=p.voice_profile_id,
                        provider=p.voice_profile.provider, payload={"segment_ids": [s.id for s in segs]}, message="Queued")
    return enqueue(db, job)


@router.post("/projects/{project_id}/generate")
def generate(project_id: str, body: GenerateIn, request: Request, user: User = Depends(limit_generation), db: Session = Depends(get_db)):
    p = owned(db, VoiceoverProject, project_id, user.id)
    segs = ordered_segments(db, p.id)
    if body.segment_ids is not None:
        wanted = set(body.segment_ids)
        segs = [s for s in segs if s.id in wanted]
    else:
        segs = [s for s in segs if s.status != "ready"]
    job = _start_generation(db, user, p, segs, body.new_take)
    audit("generation.start", user_id=user.id, target_type="project", target_id=p.id, request=request, db=db,
          details={"segments": len(segs), "chars": sum(len(s.text) for s in segs), "voice_profile_id": p.voice_profile_id})
    return {"job_id": job.id, "segments": len(segs)}


@router.post("/segments/{segment_id}/regenerate")
def regenerate_segment(segment_id: str, request: Request, user: User = Depends(limit_generation), db: Session = Depends(get_db)):
    seg = owned_segment(db, segment_id, user.id)
    p = db.get(VoiceoverProject, seg.project_id)
    job = _start_generation(db, user, p, [seg], new_take=True)
    audit("generation.regenerate", user_id=user.id, target_type="segment", target_id=seg.id, request=request, db=db)
    return {"job_id": job.id}


# ====================================================================== mix / export
@router.get("/projects/{project_id}/mix")
def project_mix(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Combined preview of all ready segments. Timeline map is returned in the X-Timeline header."""
    import json

    p = owned(db, VoiceoverProject, project_id, user.id)
    audio, sr, timeline = build_mix(db, p)
    return Response(A.to_wav_bytes(audio, sr), media_type="audio/wav",
                    headers={"X-Timeline": json.dumps(timeline), "Access-Control-Expose-Headers": "X-Timeline",
                             "Cache-Control": "private, no-store"})


@router.get("/projects/{project_id}/timeline")
def project_timeline(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = owned(db, VoiceoverProject, project_id, user.id)
    try:
        _, _, timeline = build_mix(db, p)
    except HTTPException:
        timeline = []
    return timeline


class ExportIn(ExportSettings):
    scope: Literal["full", "segments"] = "full"
    segment_ids: list[str] | None = None


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", s).strip("-")[:60] or "voiceover"


def generated_out(g: GeneratedAudio) -> dict:
    return {"id": g.id, "project_id": g.project_id, "kind": g.kind, "title": g.title, "format": g.format,
            "bitrate_kbps": g.bitrate_kbps, "sample_rate": g.sample_rate, "duration_s": g.duration_s,
            "size_bytes": g.size_bytes, "created_at": g.created_at}


@router.post("/projects/{project_id}/export")
def export_project(project_id: str, body: ExportIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = owned(db, VoiceoverProject, project_id, user.id)
    if body.sample_rate not in (22050, 24000, 44100, 48000):
        raise HTTPException(422, "Sample rate must be 22050, 24000, 44100 or 48000")
    meta = disclosure_metadata(p, p.voice_profile)
    base = _slug(p.title)
    enc = dict(bitrate_kbps=body.bitrate_kbps, out_sr=body.sample_rate, metadata=meta)
    if body.scope == "full":
        audio, sr, _ = build_mix(db, p, body.segment_ids)
        data = A.encode(audio, sr, body.format, **enc)
        kind, fmt, filename, duration = "mix", body.format, f"{base}.{body.format}", audio.size / sr
    else:
        segs = [s for s in ordered_segments(db, p.id) if s.status == "ready" and s.audio_key
                and (body.segment_ids is None or s.id in body.segment_ids)]
        if not segs:
            raise HTTPException(409, "No generated segments to export")
        buf = io.BytesIO()
        duration = 0.0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for i, s in enumerate(segs, 1):
                audio, sr = A.read_wav_bytes(storage.get(s.audio_key))
                duration += audio.size / sr
                z.writestr(f"{base}_{i:03d}.{body.format}", A.encode(audio, sr, body.format, **enc))
            z.writestr("README.txt", "AI-generated synthetic speech produced with Voice Studio.\n"
                       f"Voice: {p.voice_profile.name if p.voice_profile else 'n/a'}\n")
        data, kind, fmt, filename = buf.getvalue(), "bundle", "zip", f"{base}_segments.zip"
    g = GeneratedAudio(user_id=user.id, project_id=p.id, voice_profile_id=p.voice_profile_id, kind=kind, title=filename,
                       storage_key="", format=fmt, bitrate_kbps=body.bitrate_kbps if body.format == "mp3" else None,
                       sample_rate=body.sample_rate, duration_s=round(duration, 2), size_bytes=len(data),
                       provider=p.voice_profile.provider if p.voice_profile else None, meta={"disclosure": meta})
    db.add(g)
    db.flush()
    g.storage_key = f"exports/{user.id}/{g.id}/{filename}"
    storage.put(g.storage_key, data)
    p.export_settings = ExportSettings(format=body.format, bitrate_kbps=body.bitrate_kbps, sample_rate=body.sample_rate).model_dump()
    db.commit()
    audit("export.create", user_id=user.id, target_type="generated_audio", target_id=g.id, request=request, db=db,
          details={"format": fmt, "scope": body.scope})
    return generated_out(g)


@router.get("/exports")
def list_exports(project_id: str | None = None, limit: int = 20, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(GeneratedAudio).where(GeneratedAudio.user_id == user.id)
    if project_id:
        q = q.where(GeneratedAudio.project_id == project_id)
    return [generated_out(g) for g in db.scalars(q.order_by(GeneratedAudio.created_at.desc()).limit(min(limit, 100)))]


@router.get("/exports/{export_id}/download")
def download_export(export_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    g = owned(db, GeneratedAudio, export_id, user.id)
    media = {"mp3": "audio/mpeg", "wav": "audio/wav", "zip": "application/zip"}[g.format]
    return Response(storage.get(g.storage_key), media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{g.title}"', "Cache-Control": "private, no-store"})


@router.delete("/exports/{export_id}")
def delete_export(export_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    g = owned(db, GeneratedAudio, export_id, user.id)
    storage.delete(g.storage_key)
    db.delete(g)
    db.commit()
    return {"ok": True}
