"""Runtime configuration for the Whisper enrichment pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class SettingsError(ValueError):
    """Raised when an environment value cannot produce a safe configuration."""


def _value(source: Mapping[str, str], name: str, default: str) -> str:
    return source.get(name, default).strip()


def _bool(source: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _value(source, name, "true" if default else "false").lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise SettingsError(f"{name} must be one of true/false, got {raw!r}")


def _int(source: Mapping[str, str], name: str, default: int) -> int:
    raw = _value(source, name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise SettingsError(f"{name} must be positive, got {value}")
    return value


def _float(source: Mapping[str, str], name: str, default: float) -> float:
    raw = _value(source, name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be a number, got {raw!r}") from exc
    if value <= 0:
        raise SettingsError(f"{name} must be positive, got {value}")
    return value


@dataclass(frozen=True)
class Settings:
    ai_backend_url: str
    artifact_dir: Path
    upload_dir: Path
    whisper_model_size: str
    whisper_device: str
    whisper_compute_type: str
    demucs_model: str
    demucs_device: str
    demucs_mp3_bitrate: str
    whisperx_alignment_enabled: bool
    whisperx_device: str
    spacy_enabled: bool
    spacy_fallback_model: str
    semantic_split_enabled: bool
    semantic_max_words: int
    semantic_min_words: int
    semantic_window_words: int
    semantic_max_retries: int
    semantic_timeout_seconds: float

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if environ is None else environ
        ai_backend_url = _value(source, "AI_BACKEND_URL", "http://localhost:8420").rstrip("/")
        if not ai_backend_url:
            raise SettingsError("AI_BACKEND_URL cannot be empty")

        demucs_device = _value(source, "DEMUCS_DEVICE", "auto").lower()
        whisperx_device = _value(source, "WHISPERX_DEVICE", "auto").lower()
        valid_devices = {"auto", "cpu", "cuda", "mps"}
        if demucs_device not in valid_devices:
            raise SettingsError(f"DEMUCS_DEVICE must be one of {sorted(valid_devices)}")
        if whisperx_device not in valid_devices:
            raise SettingsError(f"WHISPERX_DEVICE must be one of {sorted(valid_devices)}")

        max_words = _int(source, "SEMANTIC_MAX_WORDS", 20)
        min_words = _int(source, "SEMANTIC_MIN_WORDS", 3)
        window_words = _int(source, "SEMANTIC_WINDOW_WORDS", 60)
        if not min_words < max_words <= window_words:
            raise SettingsError(
                "SEMANTIC_MIN_WORDS < SEMANTIC_MAX_WORDS <= SEMANTIC_WINDOW_WORDS is required"
            )

        return cls(
            ai_backend_url=ai_backend_url,
            artifact_dir=Path(_value(source, "ARTIFACT_DIR", "artifacts")),
            upload_dir=Path(_value(source, "UPLOAD_DIR", "uploads")),
            whisper_model_size=_value(source, "WHISPER_MODEL_SIZE", "large-v3"),
            whisper_device=_value(source, "WHISPER_DEVICE", "cpu").lower(),
            whisper_compute_type=_value(source, "WHISPER_COMPUTE_TYPE", "int8"),
            demucs_model=_value(source, "DEMUCS_MODEL", "htdemucs"),
            demucs_device=demucs_device,
            demucs_mp3_bitrate=_value(source, "DEMUCS_MP3_BITRATE", "192k"),
            whisperx_alignment_enabled=_bool(source, "WHISPERX_ALIGNMENT_ENABLED", True),
            whisperx_device=whisperx_device,
            spacy_enabled=_bool(source, "SPACY_ENABLED", True),
            spacy_fallback_model=_value(source, "SPACY_FALLBACK_MODEL", "xx_sent_ud_sm"),
            semantic_split_enabled=_bool(source, "SEMANTIC_SPLIT_ENABLED", True),
            semantic_max_words=max_words,
            semantic_min_words=min_words,
            semantic_window_words=window_words,
            semantic_max_retries=_int(source, "SEMANTIC_MAX_RETRIES", 3),
            semantic_timeout_seconds=_float(source, "SEMANTIC_TIMEOUT_SECONDS", 300.0),
        )
