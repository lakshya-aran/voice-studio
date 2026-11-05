"""Audio utilities built on numpy + soundfile + a bundled ffmpeg binary (imageio-ffmpeg)."""
from __future__ import annotations

import io
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

WORK_SR = 24_000  # Pocket TTS native sample rate; samples are normalised to mono at this rate
SUPPORTED_UPLOAD_EXT = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm", ".aac", ".mp4"}


class AudioError(ValueError):
    pass


@lru_cache
def ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _run_ffmpeg(args: list[str], stdin: bytes | None = None) -> bytes:
    proc = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args],
        input=stdin,
        capture_output=True,
        timeout=600,
    )
    if proc.returncode != 0:
        raise AudioError(proc.stderr.decode(errors="replace").strip()[-500:] or "ffmpeg failed")
    return proc.stdout


# ------------------------------------------------------------------ decode / encode
def decode_file(path: Path, sr: int = WORK_SR) -> np.ndarray:
    """Decode any supported format to mono float32 at `sr`."""
    raw = _run_ffmpeg(["-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "pipe:1"])
    audio = np.frombuffer(raw, dtype=np.float32).copy()
    if audio.size == 0:
        raise AudioError("No audio stream found in file")
    return audio


def decode_bytes(data: bytes, suffix: str, sr: int = WORK_SR) -> np.ndarray:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / f"in{suffix}"
        p.write_bytes(data)
        return decode_file(p, sr)


def to_wav_bytes(audio: np.ndarray, sr: int = WORK_SR, subtype: str = "PCM_16") -> bytes:
    buf = io.BytesIO()
    sf.write(buf, np.clip(audio, -1.0, 1.0), sr, format="WAV", subtype=subtype)
    return buf.getvalue()


def read_wav_bytes(data: bytes) -> tuple[np.ndarray, int]:
    audio, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio, sr


def encode(
    audio: np.ndarray,
    sr: int,
    fmt: str,
    *,
    bitrate_kbps: int = 192,
    out_sr: int | None = None,
    metadata: dict[str, str] | None = None,
) -> bytes:
    """Encode to wav/mp3 with metadata tags (used to disclose synthetic origin)."""
    meta_args: list[str] = []
    for k, v in (metadata or {}).items():
        meta_args += ["-metadata", f"{k}={v}"]
    rate_args = ["-ar", str(out_sr)] if out_sr and out_sr != sr else []
    src = to_wav_bytes(audio, sr, subtype="FLOAT")
    if fmt == "wav":
        codec = ["-c:a", "pcm_s16le", "-f", "wav"]
    elif fmt == "mp3":
        codec = ["-c:a", "libmp3lame", "-b:a", f"{bitrate_kbps}k", "-id3v2_version", "3", "-f", "mp3"]
    else:
        raise AudioError(f"Unsupported export format: {fmt}")
    return _run_ffmpeg(["-i", "pipe:0", *rate_args, *meta_args, *codec, "pipe:1"], stdin=src)


# ------------------------------------------------------------------ effects
def apply_effects(audio: np.ndarray, sr: int, *, speed: float = 1.0, pitch_semitones: float = 0.0) -> np.ndarray:
    """Pitch-preserving tempo change and tempo-preserving pitch shift via ffmpeg filters."""
    if abs(speed - 1.0) < 1e-3 and abs(pitch_semitones) < 1e-3:
        return audio
    filters: list[str] = []
    tempo = float(speed)
    if abs(pitch_semitones) >= 1e-3:
        ratio = 2 ** (pitch_semitones / 12)
        filters += [f"asetrate={sr * ratio:.3f}", f"aresample={sr}"]
        tempo /= ratio  # asetrate also speeds up; compensate
    while tempo > 2.0:  # atempo accepts 0.5..2.0 per instance
        filters.append("atempo=2.0")
        tempo /= 2.0
    while tempo < 0.5:
        filters.append("atempo=0.5")
        tempo /= 0.5
    if abs(tempo - 1.0) >= 1e-3:
        filters.append(f"atempo={tempo:.5f}")
    raw = _run_ffmpeg(
        ["-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0", "-af", ",".join(filters), "-f", "f32le", "pipe:1"],
        stdin=audio.astype(np.float32).tobytes(),
    )
    return np.frombuffer(raw, dtype=np.float32).copy()


def trim_silence(audio: np.ndarray, sr: int, threshold_db: float = -45.0, pad_ms: int = 40) -> np.ndarray:
    """Remove leading/trailing silence so pauses between segments are controlled precisely."""
    if audio.size == 0:
        return audio
    frame = max(1, int(sr * 0.01))
    n = audio.size // frame
    if n == 0:
        return audio
    rms = np.sqrt(np.mean(audio[: n * frame].reshape(n, frame) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    voiced = np.where(db > threshold_db)[0]
    if voiced.size == 0:
        return audio
    pad = int(sr * pad_ms / 1000)
    start = max(0, voiced[0] * frame - pad)
    end = min(audio.size, (voiced[-1] + 1) * frame + pad)
    return audio[start:end]


def normalize_loudness(audio: np.ndarray, target_dbfs: float = -18.0, peak_ceiling: float = 0.95) -> np.ndarray:
    rms = float(np.sqrt(np.mean(audio**2) + 1e-12))
    if rms < 1e-6:
        return audio
    gain = 10 ** (target_dbfs / 20) / rms
    out = audio * gain
    peak = float(np.max(np.abs(out)))
    if peak > peak_ceiling:
        out *= peak_ceiling / peak
    return out.astype(np.float32)


def fade(audio: np.ndarray, sr: int, ms: int = 8) -> np.ndarray:
    n = min(audio.size // 2, int(sr * ms / 1000))
    if n <= 1:
        return audio
    out = audio.copy()
    ramp = np.linspace(0, 1, n, dtype=np.float32)
    out[:n] *= ramp
    out[-n:] *= ramp[::-1]
    return out


def concat_with_pauses(parts: list[tuple[np.ndarray, int]], sr: int) -> np.ndarray:
    """parts = [(audio, pause_after_ms), ...]. The last pause is dropped."""
    chunks: list[np.ndarray] = []
    for i, (a, pause_ms) in enumerate(parts):
        chunks.append(fade(a, sr))
        if i < len(parts) - 1 and pause_ms > 0:
            chunks.append(np.zeros(int(sr * pause_ms / 1000), dtype=np.float32))
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)


# ------------------------------------------------------------------ analysis
def _frames(audio: np.ndarray, sr: int, frame_ms: float = 30, hop_ms: float = 10) -> np.ndarray:
    f, h = int(sr * frame_ms / 1000), int(sr * hop_ms / 1000)
    if audio.size < f:
        return np.zeros((0, f), dtype=np.float32)
    n = 1 + (audio.size - f) // h
    idx = np.arange(f)[None, :] + h * np.arange(n)[:, None]
    return audio[idx]


def estimate_pitch(audio: np.ndarray, sr: int, fmin: float = 60, fmax: float = 400) -> dict[str, float | None]:
    """Autocorrelation F0 estimate over voiced frames. Returns median/p10/p90 in Hz."""
    frames = _frames(audio, sr, 40, 20)
    if len(frames) == 0:
        return {"median_hz": None, "p10_hz": None, "p90_hz": None}
    energy = np.sqrt(np.mean(frames**2, axis=1))
    thresh = np.percentile(energy, 60)
    lag_min, lag_max = int(sr / fmax), int(sr / fmin)
    f0s: list[float] = []
    win = np.hanning(frames.shape[1]).astype(np.float32)
    for fr, e in zip(frames, energy):
        if e < thresh or e < 1e-3:
            continue
        x = (fr - fr.mean()) * win
        spec = np.fft.rfft(x, n=2 * x.size)
        ac = np.fft.irfft(np.abs(spec) ** 2)[: x.size]
        if ac[0] <= 0:
            continue
        ac /= ac[0]
        seg = ac[lag_min:lag_max]
        if seg.size == 0:
            continue
        lag = int(np.argmax(seg)) + lag_min
        if ac[lag] > 0.35:
            f0s.append(sr / lag)
    if len(f0s) < 5:
        return {"median_hz": None, "p10_hz": None, "p90_hz": None}
    arr = np.array(f0s)
    return {
        "median_hz": round(float(np.median(arr)), 1),
        "p10_hz": round(float(np.percentile(arr, 10)), 1),
        "p90_hz": round(float(np.percentile(arr, 90)), 1),
    }


def analyze_quality(audio: np.ndarray, sr: int) -> dict:
    """Heuristic quality report used to validate samples before cloning."""
    duration = audio.size / sr
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    rms = float(np.sqrt(np.mean(audio**2) + 1e-12)) if audio.size else 0.0
    frames = _frames(audio, sr)
    if len(frames):
        fr_db = 20 * np.log10(np.sqrt(np.mean(frames**2, axis=1)) + 1e-9)
        noise_floor = float(np.percentile(fr_db, 10))
        speech_level = float(np.percentile(fr_db, 90))
        silence_ratio = float(np.mean(fr_db < max(noise_floor + 6, -50)))
        # syllable-rate proxy: peaks in the smoothed energy envelope while speaking
        env = np.convolve(fr_db, np.ones(5) / 5, mode="same")
        speaking = env > (noise_floor + 0.5 * (speech_level - noise_floor))
        peaks = np.sum((env[1:-1] > env[:-2]) & (env[1:-1] >= env[2:]) & speaking[1:-1] & (env[1:-1] > speech_level - 12))
        speech_seconds = float(np.sum(speaking) * 0.01)
        syllables_per_s = float(peaks / speech_seconds) if speech_seconds > 1 else None
    else:
        noise_floor = speech_level = -120.0
        silence_ratio = 1.0
        speech_seconds = 0.0
        syllables_per_s = None
    clipping_ratio = float(np.mean(np.abs(audio) > 0.99)) if audio.size else 0.0
    snr = speech_level - noise_floor

    issues: list[str] = []
    score = 100.0
    if duration < 5:
        issues.append("Sample is shorter than 5 seconds; 10–30 s of clean speech is recommended.")
        score -= 35
    elif duration < 10:
        issues.append("Sample is short; 10–30 s of clean speech gives better similarity.")
        score -= 10
    if peak < 0.05:
        issues.append("Recording level is very low.")
        score -= 25
    if clipping_ratio > 0.001:
        issues.append("Clipping detected; reduce input gain.")
        score -= min(30, clipping_ratio * 3000)
    if snr < 15:
        issues.append("High background noise relative to speech.")
        score -= 30
    elif snr < 25:
        issues.append("Some background noise detected.")
        score -= 10
    if silence_ratio > 0.5:
        issues.append("More than half of the sample is silence; trim it to the spoken part.")
        score -= 15
    score = max(0.0, min(100.0, score))
    return {
        "duration_s": round(duration, 2),
        "speech_seconds": round(speech_seconds, 2),
        "peak_dbfs": round(20 * np.log10(peak + 1e-9), 1),
        "rms_dbfs": round(20 * np.log10(rms + 1e-9), 1),
        "noise_floor_db": round(noise_floor, 1),
        "snr_db": round(snr, 1),
        "silence_ratio": round(silence_ratio, 3),
        "clipping_ratio": round(clipping_ratio, 5),
        "syllables_per_s": round(syllables_per_s, 2) if syllables_per_s else None,
        "score": round(score),
        "grade": "good" if score >= 75 else "fair" if score >= 50 else "poor",
        "issues": issues,
        "usable": duration >= 3 and peak >= 0.02 and snr >= 8,
    }


def analyze_voice(audio: np.ndarray, sr: int) -> dict:
    """Voice characteristics shown on the profile (pitch range, pace, loudness)."""
    q = analyze_quality(audio, sr)
    pitch = estimate_pitch(audio, sr)
    median = pitch["median_hz"]
    register = None
    if median:
        register = "low" if median < 120 else "mid" if median < 190 else "high"
    return {
        "pitch": pitch,
        "register": register,
        "syllables_per_s": q["syllables_per_s"],
        "pace": None
        if not q["syllables_per_s"]
        else "slow" if q["syllables_per_s"] < 3.5 else "moderate" if q["syllables_per_s"] < 5.5 else "fast",
        "rms_dbfs": q["rms_dbfs"],
        "snr_db": q["snr_db"],
        "duration_s": q["duration_s"],
    }
