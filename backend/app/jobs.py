"""DB-backed background job queue with a single worker thread.

TTS on CPU is compute-bound and the model is not thread-safe, so one worker is the right default.
Jobs survive restarts (running jobs are re-queued on startup). For multi-host deployments, swap
this for a Redis/RQ or Celery worker that calls the same `run_job` function.
"""
from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable

from sqlalchemy import select, update

from . import audio as A
from .db import SessionLocal
from .models import AudioSegment, GenerationJob, VoiceoverProject, VoiceProfile, VoiceSample, utcnow
from .providers import ProviderUnavailable, get_provider
from .security import audit
from .services import cloning_input, ensure_voice, project_settings, segment_key, synthesize_text
from .storage import storage

log = logging.getLogger(__name__)

PREVIEW_TEXT = {
    "en": "Hello! This is a preview of my cloned voice, generated for this voiceover studio.",
    "fr": "Bonjour ! Ceci est un aperçu de ma voix clonée, générée pour ce studio de voix off.",
    "de": "Hallo! Dies ist eine Vorschau meiner geklonten Stimme, erzeugt für dieses Voiceover-Studio.",
    "es": "¡Hola! Esta es una vista previa de mi voz clonada, generada para este estudio de locución.",
    "it": "Ciao! Questa è un'anteprima della mia voce clonata, generata per questo studio di doppiaggio.",
    "pt": "Olá! Esta é uma prévia da minha voz clonada, gerada para este estúdio de locução.",
    "nl": "Hallo! Dit is een voorbeeld van mijn gekloonde stem, gemaakt voor deze voice-over studio.",
}


class JobCancelled(Exception):
    pass


def _update(job_id: str, **fields) -> None:
    with SessionLocal() as db:
        db.execute(update(GenerationJob).where(GenerationJob.id == job_id).values(**fields))
        db.commit()


def _is_cancelled(job_id: str) -> bool:
    with SessionLocal() as db:
        job = db.get(GenerationJob, job_id)
        return job is None or job.status == "cancelled"


# ------------------------------------------------------------------ handlers
def _create_profile(job: GenerationJob, progress: Callable[[float, str], None]) -> dict:
    with SessionLocal() as db:
        profile = db.get(VoiceProfile, job.voice_profile_id)
        if profile is None:
            raise RuntimeError("Voice profile was deleted")
        profile.status = "processing"
        db.commit()
        sample = db.scalars(select(VoiceSample).where(VoiceSample.voice_profile_id == profile.id)).first()
        if sample is None:
            raise RuntimeError("No reference sample attached")

        progress(0.1, "Analysing voice characteristics")
        ref = cloning_input(sample)
        analysis = A.analyze_voice(ref, A.WORK_SR)
        analysis["reference_seconds_used"] = round(ref.size / A.WORK_SR, 2)

        progress(0.3, "Loading voice model")
        get_provider(profile.provider)  # validates provider is enabled
        progress(0.45, "Extracting speaker conditioning")
        ensure_voice(db, profile, profile.language)

        progress(0.75, "Rendering preview")
        profile.status = "ready"  # needed by synthesize_text
        text = PREVIEW_TEXT.get(profile.language, PREVIEW_TEXT["en"])
        audio, sr, _ = synthesize_text(db, profile, text, {"language": profile.language}, seed=1234)
        key = f"voices/{profile.user_id}/{profile.id}/preview.wav"
        storage.put(key, A.to_wav_bytes(audio, sr))
        analysis["preview_seconds"] = round(audio.size / sr, 2)
        profile.preview_audio_key, profile.preview_text = key, text
        profile.analysis, profile.error = analysis, None
        db.commit()
        audit("voice_profile.ready", user_id=profile.user_id, target_type="voice_profile", target_id=profile.id)
        return {"voice_profile_id": profile.id}


def _generate_segments(job: GenerationJob, progress: Callable[[float, str], None]) -> dict:
    ids: list[str] = job.payload.get("segment_ids") or []
    done = failed = 0
    total_seconds = 0.0
    for i, seg_id in enumerate(ids):
        if _is_cancelled(job.id):
            with SessionLocal() as db:
                db.execute(
                    update(AudioSegment)
                    .where(AudioSegment.id.in_(ids[i:]), AudioSegment.status.in_(["queued", "generating"]))
                    .values(status="pending")
                )
                db.commit()
            raise JobCancelled()
        progress(i / max(1, len(ids)), f"Generating segment {i + 1} of {len(ids)}")
        with SessionLocal() as db:
            seg = db.get(AudioSegment, seg_id)
            if seg is None:
                continue
            project = db.get(VoiceoverProject, seg.project_id)
            profile = db.get(VoiceProfile, project.voice_profile_id) if project and project.voice_profile_id else None
            if profile is None:
                seg.status, seg.error = "failed", "Project has no voice profile"
                db.commit()
                failed += 1
                continue
            seg.status = "generating"
            db.commit()
            try:
                st = project_settings(project)
                if not (project.settings or {}).get("seed"):
                    project.settings = {**(project.settings or {}), "seed": st["seed"]}
                seed = int(st["seed"]) + seg.take * 7919  # stable per take -> consistent voice; new take = new variation
                audio, sr, meta = synthesize_text(db, profile, seg.text, st, seed)
                old_key = seg.audio_key
                seg.audio_key = segment_key(project, seg)
                storage.put(seg.audio_key, A.to_wav_bytes(audio, sr))
                if old_key and old_key != seg.audio_key:
                    storage.delete(old_key)
                seg.duration_s = round(audio.size / sr, 3)
                seg.generation_params = meta
                seg.status, seg.error = "ready", None
                total_seconds += seg.duration_s
                done += 1
            except ProviderUnavailable:
                seg.status = "failed"
                seg.error = "Voice provider unavailable"
                db.commit()
                raise
            except Exception as e:  # keep going with remaining segments
                log.exception("segment %s failed", seg_id)
                seg.status, seg.error = "failed", str(e)[:500]
                failed += 1
            db.commit()
    return {"generated": done, "failed": failed, "audio_seconds": round(total_seconds, 2)}


HANDLERS = {"create_profile": _create_profile, "generate_segments": _generate_segments}


# ------------------------------------------------------------------ worker
class Worker:
    def __init__(self) -> None:
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with SessionLocal() as db:  # crash recovery
            db.execute(update(GenerationJob).where(GenerationJob.status == "running").values(status="queued"))
            db.execute(
                update(AudioSegment).where(AudioSegment.status == "generating").values(status="queued")
            )
            db.commit()
        self._thread = threading.Thread(target=self._loop, name="generation-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def notify(self) -> None:
        self._wake.set()

    def _next_job(self) -> GenerationJob | None:
        with SessionLocal() as db:
            job = db.scalars(
                select(GenerationJob).where(GenerationJob.status == "queued").order_by(GenerationJob.created_at)
            ).first()
            if job:
                job.status, job.started_at, job.message = "running", utcnow(), "Starting"
                db.commit()
            return job

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self._next_job()
            if job is None:
                self._wake.wait(timeout=2.0)
                self._wake.clear()
                continue
            self.run_job(job)

    def run_job(self, job: GenerationJob) -> None:
        def progress(p: float, msg: str) -> None:
            _update(job.id, progress=max(0.0, min(1.0, p)), message=msg)

        try:
            result = HANDLERS[job.kind](job, progress)
            _update(job.id, status="succeeded", progress=1.0, message="Done", result=result, finished_at=utcnow())
        except JobCancelled:
            _update(job.id, status="cancelled", message="Cancelled", finished_at=utcnow())
        except Exception as e:
            log.error("job %s failed: %s\n%s", job.id, e, traceback.format_exc())
            _update(job.id, status="failed", error=str(e)[:1000], message="Failed", finished_at=utcnow())
            if job.kind == "create_profile" and job.voice_profile_id:
                with SessionLocal() as db:
                    p = db.get(VoiceProfile, job.voice_profile_id)
                    if p:
                        p.status, p.error = "failed", str(e)[:1000]
                        db.commit()


worker = Worker()


def enqueue(db, job: GenerationJob) -> GenerationJob:
    db.add(job)
    db.commit()
    worker.notify()
    return job
