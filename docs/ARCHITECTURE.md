# Architecture

## Overview

```
┌────────────────────────── Browser (React + TS + Tailwind + WaveSurfer) ──────────────────────────┐
│ Dashboard · Voice library · Clone wizard (sample → consent → create) · Studio · Activity log      │
└───────────────────────────────────────────────┬───────────────────────────────────────────────────┘
                                                │ REST /api (JWT bearer)
┌───────────────────────────────────────────────▼───────────────────────────────────────────────────┐
│ FastAPI                                                                                            │
│  routers/auth      register, login, me                                                             │
│  routers/voices    samples (upload, trim, quality) · consents · voice profiles · try-a-line        │
│  routers/projects  scripts · projects · segments · generate · mix · export                         │
│  routers/misc      jobs · providers · dashboard · audit log                                        │
│                                                                                                    │
│  services.py  segmentation reconcile · voice-state cache · synthesis pipeline · mixing             │
│  jobs.py      DB-backed queue + single worker thread (create_profile, generate_segments)           │
│  audio.py     ffmpeg (bundled) decode/encode · quality analysis · pitch estimate · effects · mix   │
│  text.py      paragraph/sentence segmentation · pronunciation rules                               │
│  security.py  scrypt passwords · JWT · Fernet encryption · rate limiting · audit                   │
│  storage.py   LocalStorage | S3Storage (+ encrypted put/get)                                      │
│  providers/   VoiceProvider ABC → PocketTTSProvider (more can be registered)                       │
└───────────────┬───────────────────────────────┬───────────────────────────────┬───────────────────┘
                │ SQLAlchemy                    │ objects                       │ model
          SQLite / PostgreSQL           data/storage or S3            Pocket TTS (CPU, local)
```

## Provider abstraction

`providers/base.py` defines:

- `Capabilities`: what a provider really supports (languages, native speed/pitch, emotions, expressiveness,
  seeds, chunk size, licence, notes). The UI reads `/api/providers` and only offers controls that exist.
  Controls the model lacks are either applied in post-processing (and labelled as such) or shown as
  unsupported. They are never silently ignored.
- `create_voice(sample_wav, language)` → `VoiceArtifact` (opaque bytes or a remote id).
- `synthesize(voice, text, params)` → mono float32 audio and its sample rate.

To add a provider (ElevenLabs, XTTS, …): implement `VoiceProvider`, register a factory in
`providers/__init__.py`, and add its id to `ENABLED_PROVIDERS`. Voice profiles store `provider`, so
providers can coexist.

### Pocket TTS specifics

| Need | How it's met |
|---|---|
| Voice cloning | `get_state_for_audio_prompt(wav)` produces a conditioned KV-cache state. It is exported with `export_model_state` to safetensors, Fernet-encrypted, and stored per profile **per language model** (states are model-specific). Missing languages are built lazily from the stored sample. |
| Refusing to fake cloning | Without the gated weights, Pocket TTS silently loads a no-cloning model. The adapter checks `has_voice_cloning` and raises `ProviderUnavailable`, so a stock voice is never substituted. |
| Consistency across lines | All lines share the same cached voice state and a per-project seed (`seed + take × 7919`). A new take changes only that line's seed. |
| Speed / pitch | Not native. Speed uses an ffmpeg `atempo` time-stretch; pitch uses `asetrate` + `atempo` compensation. |
| Expressiveness | Maps to the model's sampling temperature (default 0.3). |
| Emotion | Not supported. The voice reproduces the style of its reference recording. |
| Long scripts | Text is split into paragraphs → sentences (≤400 chars, very short sentences merged). Each line is a separately generated `AudioSegment`. |

## Generation pipeline (per line)

pronunciation rules → provider TTS → trim leading/trailing silence → speed/pitch → loudness normalise
(−18 dBFS RMS, −0.4 dBFS peak ceiling) → WAV stored at `projects/<user>/<project>/segments/<id>_t<take>.wav`.

Mixing concatenates ready lines with short fades. The pause after each line is its own override,
otherwise the paragraph pause at paragraph breaks, otherwise the sentence pause. The mix endpoint
returns a timeline map (`X-Timeline`) that drives the tape strip in the Studio.

Editing the script re-segments it and keeps audio for unchanged lines. Changing an audio-affecting
setting (voice, language, speed, pitch, expressiveness, pronunciation, seed) marks lines `stale`.
Pause changes need no regeneration.

## Data model

| Table | Purpose |
|---|---|
| users | accounts (scrypt password hash) |
| voice_samples | uploaded/recorded audio, normalised to 24 kHz mono, encrypted; trim range; quality report |
| voice_consents | speaker, relationship, statement text and version, typed signature, random spoken phrase, encrypted spoken-statement recording, IP, user agent, status, timestamps |
| voice_profiles | name, language, accent, provider, status, analysis (pitch, pace), preview |
| scripts | title, content, language |
| voiceover_projects | script, voice, settings (speed, pitch, pauses, language, temperature, pronunciations, seed), export defaults |
| audio_segments | ordered lines: text, paragraph, pause override, status, take, audio key, generation parameters |
| generation_jobs | queue rows: kind, status, progress, message, payload, result, timestamps |
| generated_audios | exports: format, bitrate, sample rate, size, disclosure metadata |
| audit_logs | security-relevant actions with IP and details |

## Responsible-use controls

- **Consent gate.** Cloning requires a `verified` consent owned by the user. To verify, the user must:
  1. Tick three attestations.
  2. Type a signature that matches the speaker's name.
  3. Upload a spoken recording of the statement plus a random code phrase. This is stored encrypted as evidence.

  Automated transcription of the phrase is **not** performed (no ASR is bundled). The verification record states this explicitly.
- **Third-party voices** require the speaker's email, and the speaker must record the statement themselves.
- **Encryption at rest:**
  - Samples, consent recordings and voice states are Fernet-encrypted (`ENCRYPTION_KEY`).
  - The S3 backend also requests SSE.
- **Access control.** Every query filters by `user_id`. Another user's resources return 404.
- **Deletion.** Deleting a voice removes its samples, voice states, preview and consent recording. The
  consent metadata is kept as `revoked` for the audit trail.
- **Disclosure.** Exported files carry ID3/INFO tags stating they are AI-generated synthetic speech.
- **Rate limiting.**
  - Per-IP limit on all API requests.
  - Per-user hourly limit on cloning and generation.
  - Login and registration throttles.
- **Audit log.** Covers uploads, consent, cloning, generation, exports, deletions and logins (including failures).

## Scaling notes

- The worker is in-process and single-threaded because Pocket TTS inference is not thread-safe and is
  CPU-bound. For multiple hosts, move `jobs.run_job` behind Redis/RQ or Celery. The handlers are already
  pure functions over the DB and storage.
- The rate limiter is in-memory. Use Redis for multi-instance deployments.
- Set `DATABASE_URL` to PostgreSQL and `STORAGE_BACKEND=s3` for production.
