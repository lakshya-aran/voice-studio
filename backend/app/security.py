"""Password hashing (stdlib scrypt), JWT auth, Fernet encryption, rate limiting, audit logging."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import SessionLocal, get_db
from .models import AuditLog, User

settings = get_settings()

# ---------------------------------------------------------------- passwords
_SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, dk_b64 = stored.split("$")
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except Exception:
        return False


# ---------------------------------------------------------------- JWT
def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": user_id, "iat": now, "exp": now + timedelta(minutes=settings.jwt_expire_minutes)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)
) -> User:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, payload.get("sub"))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


# ---------------------------------------------------------------- encryption at rest
_fernet = Fernet(settings.encryption_key.encode())


def encrypt(data: bytes) -> bytes:
    return _fernet.encrypt(data)


def decrypt(data: bytes) -> bytes:
    return _fernet.decrypt(data)


# ---------------------------------------------------------------- rate limiting (in-process sliding window)
class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_s: float) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                retry = int(window_s - (now - q[0])) + 1
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded", headers={"Retry-After": str(retry)}
                )
            q.append(now)


rate_limiter = RateLimiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def limit_generation(request: Request, user: User = Depends(get_current_user)) -> User:
    rate_limiter.check(f"gen:{user.id}", settings.generation_rate_limit_per_hour, 3600)
    return user


# ---------------------------------------------------------------- audit log
def audit(
    action: str,
    *,
    user_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    request: Request | None = None,
    details: dict[str, Any] | None = None,
    db: Session | None = None,
) -> None:
    entry = AuditLog(
        action=action,
        user_id=user_id,
        target_type=target_type,
        target_id=target_id,
        ip_address=client_ip(request) if request else None,
        details=details or {},
    )
    if db is not None:
        db.add(entry)
        db.commit()
        return
    with SessionLocal() as s:
        s.add(entry)
        s.commit()
