"""WhisperX forced alignment as a replaceable timing layer."""

from __future__ import annotations

import logging
import math
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from models import WordToken
from settings import Settings

logger = logging.getLogger(__name__)


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def canonical_words_from_segments(raw_segments: Iterable[Any]) -> list[WordToken]:
    """Convert faster-whisper segments into immutable, canonical word records."""
    words: list[WordToken] = []
    for segment_id, segment in enumerate(raw_segments):
        segment_words = _get(segment, "words", ()) or ()
        avg_logprob = float(_get(segment, "avg_logprob", 0.0) or 0.0)
        no_speech_prob = float(_get(segment, "no_speech_prob", 0.0) or 0.0)
        for raw_word in segment_words:
            raw_text = str(_get(raw_word, "word", ""))
            if not raw_text.strip():
                continue
            words.append(
                WordToken(
                    raw_text=raw_text,
                    word=raw_text.strip(),
                    start=float(_get(raw_word, "start", 0.0) or 0.0),
                    end=float(_get(raw_word, "end", 0.0) or 0.0),
                    probability=float(_get(raw_word, "probability", 1.0) or 0.0),
                    source_segment_id=segment_id,
                    avg_logprob=avg_logprob,
                    no_speech_prob=no_speech_prob,
                )
            )
    return words


class WhisperAligner:
    """Load WhisperX only when enabled and preserve native words on failure."""

    def __init__(
        self,
        settings: Settings,
        *,
        model_loader: Callable[[str, str], tuple[Any, Any]] | None = None,
        align_fn: Callable[..., Mapping[str, Any]] | None = None,
    ):
        self.settings = settings
        self._model_loader = model_loader or self._load_model
        self._align_fn = align_fn or self._align
        self._cache: dict[tuple[str, str], tuple[Any, Any]] = {}

    def _device(self) -> str:
        configured = self.settings.whisperx_device
        if configured != "auto":
            return configured
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except Exception:
            pass
        return "cpu"

    @staticmethod
    def _load_model(language: str, device: str):  # pragma: no cover - optional dependency
        import whisperx

        return whisperx.load_align_model(language_code=language, device=device)

    @staticmethod
    def _align(*args, **kwargs):  # pragma: no cover - optional dependency
        import whisperx

        return whisperx.align(*args, **kwargs)

    def _cached_model(self, language: str, device: str) -> tuple[Any, Any]:
        key = (language, device)
        if key not in self._cache:
            self._cache[key] = self._model_loader(language, device)
        return self._cache[key]

    @staticmethod
    def _payload(raw_segments: Sequence[Any]) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for segment in raw_segments:
            payload.append(
                {
                    "text": str(_get(segment, "text", "")),
                    "start": float(_get(segment, "start", 0.0) or 0.0),
                    "end": float(_get(segment, "end", 0.0) or 0.0),
                }
            )
        return payload

    @staticmethod
    def _normalise_token(value: str) -> str:
        return "".join(character.lower() for character in value if character.isalnum())

    def align(
        self,
        words: list[WordToken],
        raw_segments: Sequence[Any],
        language: str,
        audio_path: Path,
    ) -> list[WordToken]:
        if not self.settings.whisperx_alignment_enabled or not words:
            return words
        try:
            device = self._device()
            model, metadata = self._cached_model(language, device)
            result = self._align_fn(
                self._payload(raw_segments),
                model,
                metadata,
                str(audio_path),
                return_char_alignments=False,
            )
            aligned_items = result.get("word_segments", []) if isinstance(result, Mapping) else []
            if not isinstance(aligned_items, Sequence):
                return words

            updated = list(words)
            cursor = 0
            for item in aligned_items:
                aligned_text = str(_get(item, "word", "")).strip()
                if not aligned_text or cursor >= len(updated):
                    continue
                target = self._normalise_token(aligned_text)
                match = cursor
                for index in range(cursor, min(cursor + 4, len(updated))):
                    if self._normalise_token(updated[index].word) == target:
                        match = index
                        break
                start = _get(item, "start")
                end = _get(item, "end")
                try:
                    start_value = float(start) if start is not None else None
                    end_value = float(end) if end is not None else None
                except (TypeError, ValueError):
                    start_value = end_value = None
                if (
                    start_value is not None
                    and end_value is not None
                    and math.isfinite(start_value)
                    and math.isfinite(end_value)
                    and end_value >= start_value
                ):
                    updated[match] = replace(updated[match], start=start_value, end=end_value)
                cursor = match + 1
            return updated
        except Exception as exc:
            logger.warning("WhisperX alignment unavailable; using native timestamps: %s", exc)
            return words

