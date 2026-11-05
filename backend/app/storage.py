"""Object storage abstraction (local filesystem or S3-compatible). Sensitive objects are Fernet-encrypted."""
from __future__ import annotations

import os
import tempfile
from abc import ABC, abstractmethod
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

from .config import get_settings
from .security import decrypt, encrypt

settings = get_settings()


class Storage(ABC):
    @abstractmethod
    def put(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    # ---- helpers
    def put_secure(self, key: str, data: bytes) -> None:
        self.put(key, encrypt(data))

    def get_secure(self, key: str) -> bytes:
        return decrypt(self.get(key))

    @contextmanager
    def temp_file(self, key: str, suffix: str, secure: bool = False) -> Iterator[Path]:
        """Materialise an object as a short-lived local file (for ffmpeg / model input)."""
        data = self.get_secure(key) if secure else self.get(key)
        fd, name = tempfile.mkstemp(suffix=suffix, dir=settings.data_dir / "tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            yield Path(name)
        finally:
            try:
                os.remove(name)
            except OSError:
                pass


class LocalStorage(Storage):
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("invalid storage key")
        return p

    def put(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, p)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            pass

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class S3Storage(Storage):
    def __init__(self) -> None:
        import boto3  # optional dependency

        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
        )

    def put(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ServerSideEncryption="AES256")

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False


def _build() -> Storage:
    (settings.data_dir / "tmp").mkdir(parents=True, exist_ok=True)
    if settings.storage_backend == "s3":
        return S3Storage()
    return LocalStorage(settings.storage_local_dir)


storage: Storage = _build()
