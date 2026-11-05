"""Provider abstraction. Each provider declares its real capabilities; the API and UI only expose
controls a provider actually supports (or that the post-processing pipeline can apply)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class Capabilities:
    voice_cloning: bool
    languages: dict[str, str]  # code -> label
    native_speed: bool = False  # provider-side speed control (else we time-stretch in post)
    native_pitch: bool = False
    emotions: list[str] = field(default_factory=list)  # empty = unsupported
    expressiveness: bool = False  # sampling temperature / stability knob
    deterministic_seed: bool = False
    max_chars_per_request: int = 400
    sample_rate: int = 24_000
    min_sample_seconds: float = 5.0
    recommended_sample_seconds: tuple[float, float] = (10.0, 30.0)
    local: bool = True
    licence: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VoiceArtifact:
    """What a provider returns after cloning: an opaque serialized voice (stored encrypted) or a remote id."""

    data: bytes | None
    remote_id: str | None = None
    file_suffix: str = ".bin"
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class SynthesisParams:
    language: str = "en"
    temperature: float | None = None
    emotion: str | None = None
    seed: int | None = None


class VoiceProvider(ABC):
    id: str
    name: str

    @abstractmethod
    def capabilities(self) -> Capabilities: ...

    def status(self) -> dict[str, Any]:
        """Readiness info (model downloaded? credentials present?)."""
        return {"ready": True}

    @abstractmethod
    def create_voice(self, sample_wav: Path, *, language: str, name: str) -> VoiceArtifact:
        """Extract a reusable voice representation (speaker embedding / conditioning state)."""

    @abstractmethod
    def synthesize(self, voice: VoiceArtifact, text: str, params: SynthesisParams) -> tuple[np.ndarray, int]:
        """Return mono float32 audio and its sample rate."""

    def delete_voice(self, voice: VoiceArtifact) -> None:  # remote providers override
        return None


class ProviderUnavailable(RuntimeError):
    pass
