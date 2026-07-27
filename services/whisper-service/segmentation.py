"""Language-aware deterministic transcript segmentation."""

from __future__ import annotations

import importlib.util
import logging
import math
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from models import TranscriptionSegment, TranscriptionWord, WordToken
from settings import Settings

logger = logging.getLogger(__name__)

SPACY_MODELS = {
    "en": "en_core_web_sm",
    "ru": "ru_core_news_sm",
    "fr": "fr_core_news_sm",
    "ja": "ja_core_news_sm",
    "es": "es_core_news_sm",
    "de": "de_core_news_sm",
    "it": "it_core_news_sm",
    "zh": "zh_core_web_sm",
    "vi": "xx_sent_ud_sm",
}

_END_MARKS = frozenset(".!?。！？")
_CONNECTORS = {
    "en": ("but", "and", "or", "because", "so", "however", "although"),
    "vi": ("nhưng", "và", "hoặc", "bởi vì", "nên", "tuy nhiên", "mặc dù"),
    "fr": ("mais", "et", "ou", "parce que", "donc"),
    "de": ("aber", "und", "oder", "weil", "deshalb"),
    "es": ("pero", "y", "o", "porque", "entonces"),
}


def validate_spacy_packages() -> None:
    """Fail fast at service startup when a configured spaCy package is absent."""
    missing = sorted({model for model in SPACY_MODELS.values() if importlib.util.find_spec(model) is None})
    if missing:
        raise RuntimeError("Missing pinned spaCy pipelines: " + ", ".join(missing))


def _value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _repair_words(words: Sequence[WordToken]) -> list[WordToken]:
    repaired: list[WordToken] = []
    previous_end = 0.0
    for word in words:
        start = float(word.start) if math.isfinite(float(word.start)) else previous_end
        end = float(word.end) if math.isfinite(float(word.end)) else start
        start = max(0.0, start)
        end = max(start, end)
        if end < start:
            end = start
        repaired_word = replace(word, start=start, end=end)
        repaired.append(repaired_word)
        previous_end = max(previous_end, end)
    return repaired


def _render_with_spans(words: Sequence[WordToken]) -> tuple[str, list[tuple[int, int]]]:
    text_parts: list[str] = []
    spans: list[tuple[int, int]] = []
    cursor = 0
    for index, word in enumerate(words):
        raw = word.raw_text or word.word
        if index and not raw[:1].isspace() and text_parts and not text_parts[-1].endswith(" "):
            raw = " " + raw
        start = cursor
        text_parts.append(raw)
        cursor += len(raw)
        spans.append((start, cursor))
    return "".join(text_parts), spans


class SpacySegmenter:
    """Apply parser sentence boundaries plus conservative transcript rules."""

    def __init__(
        self,
        settings: Settings,
        *,
        loader: Callable[[str], Any] | None = None,
    ):
        self.settings = settings
        self._loader = loader or self._load_pipeline
        self._cache: dict[str, Any] = {}

    @staticmethod
    def _load_pipeline(model_name: str):  # pragma: no cover - optional dependency
        import spacy

        return spacy.load(model_name)

    def _pipeline(self, language: str):
        if not self.settings.spacy_enabled:
            return None
        model_name = SPACY_MODELS.get(language.lower(), self.settings.spacy_fallback_model)
        if model_name not in self._cache:
            self._cache[model_name] = self._loader(model_name)
        return self._cache[model_name]

    @staticmethod
    def _doc_boundaries(doc: Any, spans: Sequence[tuple[int, int]]) -> set[int]:
        boundaries: set[int] = set()
        if doc is None:
            return boundaries
        try:
            has_parser = bool(doc.has_annotation("DEP") and doc.has_annotation("POS"))
        except Exception:
            has_parser = False
        if not has_parser:
            return boundaries
        try:
            sentences = list(doc.sents)
        except Exception:
            return boundaries
        for sentence in sentences[:-1]:
            end_char = int(getattr(sentence, "end_char", -1))
            if end_char < 0:
                continue
            for index, (_start, end) in enumerate(spans):
                if end >= end_char:
                    boundaries.add(index + 1)
                    break
        return boundaries

    @staticmethod
    def _connector_boundaries(words: Sequence[WordToken], language: str) -> set[int]:
        phrases = _CONNECTORS.get(language.lower(), ())
        if not phrases:
            return set()
        minimum_context = 3 if language.lower() == "vi" else 5
        normalised = [word.word.strip(" ,;:!?\"'()[]{}\n\t").lower() for word in words]
        boundaries: set[int] = set()
        for index, token in enumerate(normalised):
            phrase = None
            for candidate in phrases:
                candidate_parts = candidate.split()
                if normalised[index : index + len(candidate_parts)] == candidate_parts:
                    phrase = candidate_parts
                    break
            if phrase is None:
                continue
            right_start = index + len(phrase)
            if index >= minimum_context and len(words) - right_start >= minimum_context:
                boundaries.add(index)
        return boundaries

    def preliminary_groups(self, words: list[WordToken], language: str) -> list[list[WordToken]]:
        repaired = _repair_words(words)
        if not repaired:
            return []
        text, spans = _render_with_spans(repaired)
        doc = None
        try:
            pipeline = self._pipeline(language)
            doc = pipeline(text) if pipeline is not None else None
        except Exception as exc:
            logger.warning("spaCy pipeline unavailable for %s; using deterministic rules: %s", language, exc)

        boundaries = self._doc_boundaries(doc, spans)
        boundaries.update(self._connector_boundaries(repaired, language))
        for index, word in enumerate(repaired):
            stripped = word.word.rstrip()
            if stripped and stripped[-1] in _END_MARKS and index < len(repaired) - 1:
                boundaries.add(index + 1)
            if index and word.start - repaired[index - 1].end >= 0.8:
                boundaries.add(index)

        groups: list[list[WordToken]] = []
        start = 0
        for boundary in sorted(boundary for boundary in boundaries if 0 < boundary < len(repaired)):
            if boundary > start:
                groups.append(repaired[start:boundary])
                start = boundary
        if start < len(repaired):
            groups.append(repaired[start:])
        return groups


def reconstruct_segments(groups: Iterable[Sequence[WordToken]]) -> list[TranscriptionSegment]:
    segments: list[TranscriptionSegment] = []
    for segment_id, group in enumerate(groups):
        words = list(group)
        if not words:
            continue
        public_words = [
            TranscriptionWord(
                word=word.word,
                start=round(word.start, 3),
                end=round(word.end, 3),
                probability=max(0.0, min(1.0, round(word.probability, 4))),
            )
            for word in words
        ]
        count = len(words)
        avg_logprob = sum(word.avg_logprob for word in words) / count
        no_speech_prob = sum(word.no_speech_prob for word in words) / count
        text = "".join(word.raw_text or word.word for word in words).strip()
        segments.append(
            TranscriptionSegment(
                id=segment_id,
                text=text,
                start=round(words[0].start, 3),
                end=round(words[-1].end, 3),
                words=public_words,
                avg_logprob=round(avg_logprob, 4),
                no_speech_prob=round(no_speech_prob, 4),
            )
        )
    return segments

