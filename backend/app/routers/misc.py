"""Jobs, providers, dashboard statistics and audit log."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditLog, AudioSegment, GeneratedAudio, GenerationJob, User, VoiceoverProject, VoiceProfile, utcnow
from ..providers import list_providers
from ..security import get_current_user
from ..services import owned
from .projects import generated_out, project_out
from .voices import profile_out

router = APIRouter(tags=["misc"])


def job_out(j: GenerationJob) -> dict:
    return {"id": j.id, "kind": j.kind, "status": j.status, "progress": j.progress, "message": j.message,
            "error": j.error, "result": j.result, "project_id": j.project_id, "voice_profile_id": j.voice_profile_id,
            "created_at": j.created_at, "started_at": j.started_at, "finished_at": j.finished_at}


@router.get("/jobs")
def list_jobs(active: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(GenerationJob).where(GenerationJob.user_id == user.id)
    if active:
        q = q.where(GenerationJob.status.in_(["queued", "running"]))
    return [job_out(j) for j in db.scalars(q.order_by(GenerationJob.created_at.desc()).limit(50))]


@router.get("/jobs/{job_id}")
def get_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return job_out(owned(db, GenerationJob, job_id, user.id))


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    j = owned(db, GenerationJob, job_id, user.id)
    if j.status not in ("queued", "running"):
        raise HTTPException(409, "Job is not active")
    was_queued = j.status == "queued"
    j.status, j.message = "cancelled", "Cancelling" if not was_queued else "Cancelled"
    if was_queued and j.kind == "generate_segments":
        for s in db.scalars(select(AudioSegment).where(AudioSegment.id.in_(j.payload.get("segment_ids", [])))):
            if s.status == "queued":
                s.status = "pending"
    db.commit()
    return job_out(j)


@router.get("/providers")
def providers(user: User = Depends(get_current_user)):
    return [{"id": p.id, "name": p.name, "capabilities": p.capabilities().to_dict(), "status": p.status()}
            for p in list_providers()]


@router.get("/dashboard")
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    uid = user.id
    month_start = utcnow() - timedelta(days=30)
    seg_q = (select(func.count(AudioSegment.id), func.coalesce(func.sum(AudioSegment.duration_s), 0.0))
             .join(VoiceoverProject, VoiceoverProject.id == AudioSegment.project_id)
             .where(VoiceoverProject.user_id == uid, AudioSegment.status == "ready"))
    seg_count, seg_seconds = db.execute(seg_q).one()
    chars_q = (select(func.coalesce(func.sum(func.length(AudioSegment.text)), 0))
               .join(VoiceoverProject, VoiceoverProject.id == AudioSegment.project_id)
               .where(VoiceoverProject.user_id == uid, AudioSegment.status == "ready",
                      AudioSegment.updated_at >= month_start))
    jobs_30d = db.scalar(select(func.count(GenerationJob.id)).where(GenerationJob.user_id == uid,
                                                                    GenerationJob.created_at >= month_start))
    exports_bytes = db.scalar(select(func.coalesce(func.sum(GeneratedAudio.size_bytes), 0)).where(GeneratedAudio.user_id == uid))
    voices = db.scalars(select(VoiceProfile).where(VoiceProfile.user_id == uid).order_by(VoiceProfile.created_at.desc()).limit(6))
    projects = db.scalars(select(VoiceoverProject).where(VoiceoverProject.user_id == uid)
                          .order_by(VoiceoverProject.updated_at.desc()).limit(6))
    exports = db.scalars(select(GeneratedAudio).where(GeneratedAudio.user_id == uid)
                         .order_by(GeneratedAudio.created_at.desc()).limit(6))
    return {
        "user": {"name": user.name, "email": user.email},
        "stats": {
            "voices": db.scalar(select(func.count(VoiceProfile.id)).where(VoiceProfile.user_id == uid)),
            "projects": db.scalar(select(func.count(VoiceoverProject.id)).where(VoiceoverProject.user_id == uid)),
            "segments_generated": seg_count,
            "audio_seconds": round(float(seg_seconds), 1),
            "characters_30d": int(db.scalar(chars_q) or 0),
            "jobs_30d": jobs_30d,
            "export_bytes": int(exports_bytes or 0),
        },
        "voices": [profile_out(v, db) for v in voices],
        "projects": [project_out(p, db, with_segments=False) for p in projects],
        "exports": [generated_out(g) for g in exports],
    }


@router.get("/audit")
def audit_log(limit: int = 100, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).where(AuditLog.user_id == user.id).order_by(AuditLog.created_at.desc()).limit(min(limit, 500)))
    return [{"id": r.id, "created_at": r.created_at, "action": r.action, "target_type": r.target_type,
             "target_id": r.target_id, "ip_address": r.ip_address, "details": r.details} for r in rows]
