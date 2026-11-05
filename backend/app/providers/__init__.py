"""Provider registry. Add new providers (ElevenLabs, XTTS, ...) by implementing VoiceProvider
and registering a factory here; enable them with ENABLED_PROVIDERS."""
from __future__ import annotations

from collections.abc import Callable

from ..config import get_settings
from .base import Capabilities, ProviderUnavailable, SynthesisParams, VoiceArtifact, VoiceProvider


def _pocket() -> VoiceProvider:
    from .pocket_tts import PocketTTSProvider

    return PocketTTSProvider()


FACTORIES: dict[str, Callable[[], VoiceProvider]] = {"pocket_tts": _pocket}
_instances: dict[str, VoiceProvider] = {}


def get_provider(provider_id: str | None = None) -> VoiceProvider:
    settings = get_settings()
    pid = provider_id or settings.default_provider
    if pid not in settings.enabled_provider_list or pid not in FACTORIES:
        raise ProviderUnavailable(f"Provider '{pid}' is not enabled")
    if pid not in _instances:
        _instances[pid] = FACTORIES[pid]()
    return _instances[pid]


def list_providers() -> list[VoiceProvider]:
    settings = get_settings()
    return [get_provider(p) for p in settings.enabled_provider_list if p in FACTORIES]


__all__ = [
    "Capabilities",
    "ProviderUnavailable",
    "SynthesisParams",
    "VoiceArtifact",
    "VoiceProvider",
    "get_provider",
    "list_providers",
]
