"""Kyutai Pocket TTS provider (local, CPU, CC-BY-4.0).

Voice cloning = running the reference audio through the model to obtain a conditioned model state
(KV cache), which is exported as safetensors and stored encrypted. The state is specific to the
language model that produced it, so profiles keep one state per language.
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

import numpy as np

from ..config import get_settings
from .base import Capabilities, ProviderUnavailable, SynthesisParams, VoiceArtifact, VoiceProvider

log = logging.getLogger(__name__)
settings = get_settings()

LANGUAGES = {
    "en": ("english", "English"),
    "fr": ("french", "French"),
    "de": ("german", "German"),
    "es": ("spanish", "Spanish"),
    "it": ("italian", "Italian"),
    "pt": ("portuguese", "Portuguese"),
    "nl": ("dutch", "Dutch"),
}


class PocketTTSProvider(VoiceProvider):
    id = "pocket_tts"
    name = "Kyutai Pocket TTS (local)"

    def __init__(self) -> None:
        self._models: dict[str, Any] = {}
        self._load_lock = threading.Lock()
        self._gen_lock = threading.Lock()  # generate_audio is not thread-safe
        self._state_cache: dict[str, Any] = {}
        self._load_errors: dict[str, str] = {}
        if settings.hf_token:
            os.environ.setdefault("HF_TOKEN", settings.hf_token)
        if settings.pocket_tts_threads:
            import torch

            torch.set_num_threads(settings.pocket_tts_threads)

    # ------------------------------------------------------------ info
    def capabilities(self) -> Capabilities:
        return Capabilities(
            voice_cloning=True,
            languages={code: label for code, (_, label) in LANGUAGES.items()},
            native_speed=False,  # applied as pitch-preserving time-stretch in post
            native_pitch=False,  # applied as formant-naive pitch shift in post
            emotions=[],  # Pocket TTS reproduces the reference's style; no emotion conditioning
            expressiveness=True,  # sampling temperature
            deterministic_seed=True,
            max_chars_per_request=400,
            sample_rate=24_000,
            min_sample_seconds=5.0,
            recommended_sample_seconds=(10.0, 30.0),
            local=True,
            licence="CC-BY-4.0 (model weights; gated on Hugging Face)",
            notes=[
                "Speaking style and emotion follow the reference recording. Record the sample in the tone you want.",
                "Speed and pitch are applied by audio post-processing.",
                "Prompts longer than 30 s are truncated.",
            ],
        )

    def status(self) -> dict[str, Any]:
        loaded = {lang: bool(getattr(m, "has_voice_cloning", False)) for lang, m in self._models.items()}
        return {
            "ready": not self._load_errors and all(loaded.values()) if loaded else bool(settings.hf_token),
            "hf_token_configured": bool(settings.hf_token or os.environ.get("HF_TOKEN")),
            "loaded_languages": loaded,
            "errors": self._load_errors,
        }

    # ------------------------------------------------------------ model management
    def _model(self, language: str):
        if language not in LANGUAGES:
            raise ProviderUnavailable(f"Language '{language}' is not supported by Pocket TTS")
        with self._load_lock:
            if language in self._models:
                return self._models[language]
            from pocket_tts import TTSModel

            log.info("Loading Pocket TTS model for %s", language)
            model = TTSModel.load_model(language=LANGUAGES[language][0])
            if not getattr(model, "has_voice_cloning", False):
                msg = (
                    "Pocket TTS loaded WITHOUT voice-cloning weights. Accept the terms at "
                    "https://huggingface.co/kyutai/pocket-tts and set HF_TOKEN in backend/.env, then restart."
                )
                self._load_errors[language] = msg
                raise ProviderUnavailable(msg)
            self._load_errors.pop(language, None)
            self._models[language] = model
            return model

    def warmup(self, language: str = "en") -> None:
        self._model(language)

    # ------------------------------------------------------------ cloning
    def create_voice(self, sample_wav: Path, *, language: str, name: str) -> VoiceArtifact:
        from pocket_tts import export_model_state

        model = self._model(language)
        with self._gen_lock:
            state = model.get_state_for_audio_prompt(Path(sample_wav), truncate=True)
        fd, tmp = tempfile.mkstemp(suffix=".safetensors", dir=settings.data_dir / "tmp")
        os.close(fd)
        try:
            export_model_state(state, tmp)
            data = Path(tmp).read_bytes()
        finally:
            os.remove(tmp)
        return VoiceArtifact(data=data, file_suffix=".safetensors", meta={"language": language, "model": LANGUAGES[language][0]})

    def _load_state(self, model, voice: VoiceArtifact, cache_key: str | None):
        if cache_key and cache_key in self._state_cache:
            return self._state_cache[cache_key]
        if not voice.data:
            raise ProviderUnavailable("Voice state is missing")
        fd, tmp = tempfile.mkstemp(suffix=".safetensors", dir=settings.data_dir / "tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(voice.data)
            state = model.get_state_for_audio_prompt(Path(tmp))
        finally:
            os.remove(tmp)
        if cache_key:
            if len(self._state_cache) > 16:
                self._state_cache.pop(next(iter(self._state_cache)))
            self._state_cache[cache_key] = state
        return state

    # ------------------------------------------------------------ synthesis
    def synthesize(self, voice: VoiceArtifact, text: str, params: SynthesisParams) -> tuple[np.ndarray, int]:
        import torch

        language = voice.meta.get("language", params.language)
        model = self._model(language)
        with self._gen_lock:
            state = self._load_state(model, voice, voice.meta.get("cache_key"))
            default_temp = model.temp
            try:
                if params.temperature is not None:
                    model.temp = float(params.temperature)
                if params.seed is not None:
                    torch.manual_seed(int(params.seed))
                audio = model.generate_audio(state, text, copy_state=True)
            finally:
                model.temp = default_temp
        return audio.detach().cpu().numpy().astype(np.float32).reshape(-1), int(model.sample_rate)

    def forget(self, cache_key_prefix: str) -> None:
        for k in [k for k in self._state_cache if k.startswith(cache_key_prefix)]:
            self._state_cache.pop(k, None)
