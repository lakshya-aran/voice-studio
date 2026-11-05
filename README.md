# Voice Studio

A voice cloning and voiceover production studio. Record or upload a voice sample, verify the speaker's
consent, clone the voice, then turn scripts into voiceovers you can edit line by line and export.

Cloning and speech generation run **locally on the CPU** with
[Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts) (CC-BY-4.0). No GPU or cloud API is required.
On a typical laptop it generates speech about 3–4× faster than real time.

- **Frontend:** React 19, TypeScript, Tailwind CSS 4, WaveSurfer.js 8, TanStack Query
- **Backend:** Python FastAPI, SQLAlchemy (SQLite or PostgreSQL), DB-backed job queue
- **Storage:** local disk or any S3-compatible bucket; voice data encrypted at rest
- **Audio:** numpy + soundfile + a bundled ffmpeg binary (no system ffmpeg needed)

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design, data model and provider abstraction.

## Features

- **Voice samples:**
  - Upload WAV/MP3/M4A/FLAC or record in the browser, with a live level meter.
  - Trim on the waveform.
  - Quality report: speech length, SNR, peak, clipping, silence.
- **Consent:**
  - Signed attestation.
  - Spoken consent statement with a random code phrase, stored encrypted.
  - Third-party voices need the speaker's email.
- **Voice profiles:**
  - Cloned speaker state stored per language.
  - Pitch and pace analysis.
  - Preview, plus a side-by-side comparison with the original.
  - "Try a line".
  - Deletion of all voice data.
- **Studio:**
  - Script editor with word, character and paragraph counts.
  - Automatic sentence segmentation.
  - Per-line generation, regeneration (new take) and editing.
  - Drag or keyboard reordering.
  - Pause per line, per sentence and per paragraph.
  - Speed, pitch, expressiveness and language.
  - Pronunciation dictionary.
  - Waveform transport with a clickable line timeline. Space toggles play.
- **Export:**
  - Full mix or separate lines (ZIP).
  - WAV or MP3 at 96–320 kbps, 24, 44.1 or 48 kHz.
  - Files are tagged as AI-generated.
- **Dashboard:** usage statistics, voices, recent projects, recent exports, and an activity (audit) log.

Controls follow what the model can actually do. Pocket TTS has no emotion conditioning: the clone takes
on the tone of its reference recording, and the UI says so. Speed and pitch are applied as audio
post-processing and are labelled that way.

## Requirements

- Python 3.10–3.14
- Node.js 20+ (tested with Node 26)
- About 1.5 GB of disk space for PyTorch and the model weights
- A Hugging Face account. The Pocket TTS voice-cloning weights are gated.

## Setup

### 1. Get access to the voice-cloning model

1. Sign in at https://huggingface.co and accept the terms at https://huggingface.co/kyutai/pocket-tts.
2. Create a **read** token at https://huggingface.co/settings/tokens.

Without this, the app still runs, but cloning fails with a clear message. It never substitutes a stock voice.

### 2. Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then set HF_TOKEN=hf_...
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

On Linux, install the CPU build of PyTorch first to avoid multi-GB CUDA wheels:
`pip install torch --index-url https://download.pytorch.org/whl/cpu`.

The first clone or generation downloads and loads the model, which takes about a minute. Later ones are fast.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 (proxies /api to :8000)
```

Open http://localhost:5173, create an account, then select **Clone a voice**.

### Tests

```bash
cd backend
python -m pytest -q
```

The full clone → generate → export test runs only when `HF_TOKEN` is configured, because it uses the real model.

## Configuration

All backend settings are environment variables, read from `backend/.env`. See
[`backend/.env.example`](backend/.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `HF_TOKEN` | – | Hugging Face token for the gated Pocket TTS cloning weights |
| `DEFAULT_PROVIDER` / `ENABLED_PROVIDERS` | `pocket_tts` | Voice providers |
| `POCKET_TTS_THREADS` | `0` | Torch CPU threads (0 = default) |
| `DATABASE_URL` | SQLite in `backend/data` | Any SQLAlchemy URL, e.g. `postgresql+psycopg://…` |
| `STORAGE_BACKEND` | `local` | `local` or `s3` (`S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`, keys) |
| `JWT_SECRET`, `ENCRYPTION_KEY` | auto in dev | **Required in production.** `ENCRYPTION_KEY` is a Fernet key |
| `ENVIRONMENT` | `development` | `production` refuses to auto-generate secrets |
| `CORS_ORIGINS` | localhost:5173 | Allowed browser origins |
| `MAX_UPLOAD_MB`, `MAX_SAMPLE_SECONDS`, `MAX_SCRIPT_CHARS` | 50, 300, 100000 | Input limits |
| `RATE_LIMIT_PER_MINUTE`, `GENERATION_RATE_LIMIT_PER_HOUR` | 600, 60 | Abuse limits |

In development, secrets are generated once into `backend/data/secrets.json`. **Back up `ENCRYPTION_KEY`.**
Without it, stored voice samples and voice states cannot be decrypted.

## Deployment

1. **Backend:**
   - Set `ENVIRONMENT=production`, plus `JWT_SECRET`, `ENCRYPTION_KEY`, `HF_TOKEN`, `DATABASE_URL` (PostgreSQL) and
     `STORAGE_BACKEND=s3`.
   - Install `psycopg[binary]` and `boto3`.
   - Run `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1`.
   - Use one worker per process, because the job worker and model live in-process. Scale out by moving jobs to a queue (see ARCHITECTURE.md).
2. **Frontend:** run `npm run build` and serve `frontend/dist` as static files. Route `/api` to the backend with a reverse proxy
   (nginx, Caddy), and fall back to `index.html` for client-side routes.
3. **HTTPS:** serve over HTTPS. The browser only allows microphone recording on secure origins (and localhost).
4. **Persistence:** pre-download the model on the server (`python -c "from pocket_tts import TTSModel; TTSModel.load_model()"`)
   and persist the Hugging Face cache directory.

## Responsible use

Clone a voice only with the explicit consent of its owner. Impersonation, fraud, deception and presenting
synthetic audio as a genuine recording are prohibited, both by this app and by the Pocket TTS licence terms.
Consent records, the spoken consent statement and an audit log are kept for accountability.
