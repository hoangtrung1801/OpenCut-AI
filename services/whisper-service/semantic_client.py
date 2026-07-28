"""Validated AI-backend client for semantic word-boundary refinement."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from models import WordToken
from settings import Settings

logger = logging.getLogger(__name__)


class SemanticSegmentationError(RuntimeError):
    """Raised when required semantic refinement cannot produce valid boundaries."""


class HttpxSemanticTransport:
    def __init__(self, settings: Settings):
        self.settings = settings

    def __call__(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            import httpx

            response = httpx.post(
                f"{self.settings.ai_backend_url}/api/internal/transcription/refine",
                json=dict(payload),
                timeout=self.settings.semantic_timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, Mapping):
                raise ValueError("response is not an object")
            return data
        except Exception as exc:
            raise SemanticSegmentationError(f"Semantic refinement transport failed: {type(exc).__name__}") from exc


class SemanticClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    ):
        self.settings = settings
        self.transport = transport or HttpxSemanticTransport(settings)

    @staticmethod
    def _validate(response: Mapping[str, Any], word_count: int) -> list[int]:
        if not isinstance(response, Mapping):
            raise ValueError("response must be an object")
        indexes = response.get("split_after")
        if not isinstance(indexes, list):
            raise ValueError("split_after must be a list")
        if any(isinstance(index, bool) or not isinstance(index, int) for index in indexes):
            raise ValueError("split_after must contain integers")
        if indexes != sorted(indexes) or len(indexes) != len(set(indexes)):
            raise ValueError("split_after must be strictly increasing")
        if any(index < 0 or index >= word_count - 1 for index in indexes):
            raise ValueError("split_after contains an out-of-range index")

        starts = [0] + [index + 1 for index in indexes]
        ends = indexes + [word_count - 1]
        lengths = [end - start + 1 for start, end in zip(starts, ends)]
        if any(length > 20 for length in lengths):
            raise ValueError("every semantic segment must contain at most 20 words")
        if any(length < 3 for length in lengths[:-1]):
            raise ValueError("non-final semantic segments must contain at least 3 words")
        return indexes

    @staticmethod
    def _partition(words: Sequence[WordToken], candidates: Sequence[int], window: int) -> list[tuple[int, int, list[int]]]:
        partitions: list[tuple[int, int, list[int]]] = []
        offset = 0
        while offset < len(words):
            if len(words) - offset <= window:
                end = len(words)
            else:
                eligible = [candidate for candidate in candidates if offset + 3 <= candidate < offset + window]
                end = (max(eligible) + 1) if eligible else offset + window
            relative_candidates = [candidate - offset for candidate in candidates if offset <= candidate < end - 1]
            partitions.append((offset, end, relative_candidates))
            offset = end
        return partitions

    def _split_window(
        self,
        words: Sequence[WordToken],
        language: str,
        candidates: Sequence[int],
    ) -> list[list[WordToken]]:
        previous_error = ""
        payload_words = [{"index": index, "word": word.word} for index, word in enumerate(words)]
        for _attempt in range(self.settings.semantic_max_retries):
            payload: dict[str, Any] = {
                "language": language,
                "words": payload_words,
                "candidates": list(candidates),
            }
            if previous_error:
                payload["previous_error"] = previous_error
            try:
                response = self.transport(payload)
            except SemanticSegmentationError:
                raise
            except Exception as exc:
                raise SemanticSegmentationError(
                    f"Semantic refinement transport failed: {type(exc).__name__}"
                ) from exc
            try:
                indexes = self._validate(response, len(words))
                starts = [0] + [index + 1 for index in indexes]
                ends = indexes + [len(words) - 1]
                parts = [list(words[start : end + 1]) for start, end in zip(starts, ends)]
                if [word for part in parts for word in part] != list(words):
                    raise ValueError("semantic split is not lossless")
                return parts
            except ValueError as exc:
                previous_error = str(exc)
                logger.info("Retrying invalid semantic refinement response: %s", previous_error)
        raise SemanticSegmentationError("Semantic refinement returned invalid boundaries after retries")

    def split(
        self,
        words: Sequence[WordToken],
        language: str,
        candidates: Sequence[int],
    ) -> list[list[WordToken]]:
        if not words:
            return []
        groups: list[list[WordToken]] = []
        for start, end, relative_candidates in self._partition(
            words, candidates, self.settings.semantic_window_words
        ):
            groups.extend(self._split_window(words[start:end], language, relative_candidates))
        return groups

