"""Application settings, loaded from environment variables / backend/.env."""
from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Voice Studio"
    environment: str = "development"

    # Database: SQLite by default, any SQLAlchemy URL works (e.g. postgresql+psycopg://user:pw@host/db)
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'voice_studio.db').as_posix()}"

    # Storage
    storage_backend: str = "local"  # "local" | "s3"
    storage_local_dir: Path = BACKEND_DIR / "data" / "storage"
    s3_bucket: str = ""
    s3_endpoint_url: str = ""  # e.g. http://localhost:9000 for MinIO; empty for AWS
    s3_region: str = "us-east-1"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""

    # Secrets. If empty, generated once and persisted in data/secrets.json (development only).
    jwt_secret: str = ""
    encryption_key: str = ""  # Fernet key for voice data at rest
    jwt_expire_minutes: int = 60 * 24

    # CORS
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Providers
    default_provider: str = "pocket_tts"
    enabled_providers: str = "pocket_tts"  # comma separated, e.g. "pocket_tts,xtts"
    hf_token: str = ""  # Hugging Face token (Pocket TTS weights are gated)
    pocket_tts_threads: int = 0  # 0 = torch default

    # Limits
    max_upload_mb: int = 50
    min_sample_seconds: float = 5.0
    max_sample_seconds: float = 300.0
    max_script_chars: int = 100_000
    rate_limit_per_minute: int = 600
    generation_rate_limit_per_hour: int = 60

    @property
    def data_dir(self) -> Path:
        return BACKEND_DIR / "data"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def enabled_provider_list(self) -> list[str]:
        return [p.strip() for p in self.enabled_providers.split(",") if p.strip()]


def _ensure_secrets(s: Settings) -> Settings:
    """Generate and persist dev secrets so restarts don't invalidate tokens / encrypted data."""
    import json

    from cryptography.fernet import Fernet

    s.data_dir.mkdir(parents=True, exist_ok=True)
    path = s.data_dir / "secrets.json"
    stored = json.loads(path.read_text()) if path.exists() else {}
    changed = False
    if not s.jwt_secret:
        if "jwt_secret" not in stored:
            stored["jwt_secret"] = secrets.token_urlsafe(48)
            changed = True
        s.jwt_secret = stored["jwt_secret"]
    if not s.encryption_key:
        if "encryption_key" not in stored:
            stored["encryption_key"] = Fernet.generate_key().decode()
            changed = True
        s.encryption_key = stored["encryption_key"]
    if changed:
        if s.environment == "production":
            raise RuntimeError("JWT_SECRET and ENCRYPTION_KEY must be set explicitly in production")
        path.write_text(json.dumps(stored, indent=2))
    return s


@lru_cache
def get_settings() -> Settings:
    return _ensure_secrets(Settings())
