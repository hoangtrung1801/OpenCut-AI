"""Deterministic multilingual caption length, splitting, and timing helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.translation import DisplayCaptionSegment, TranslationWordInput


@dataclass(frozen=True)
class TimedSourcePart:
    text: str
    start: float
    end: float
    words: tuple[TranslationWordInput, ...]


def _char_weight(char: str) -> float:
    code = ord(char)
    if 0x4E00 <= code <= 0x9FFF or 0x3040 <= code <= 0x30FF:
        return 1.75
    if 0xAC00 <= code <= 0xD7A3 or 0x1100 <= code <= 0x11FF:
        return 1.5
    if 0x0E00 <= code <= 0x0E7F:
        return 1.0
    if 0xFF01 <= code <= 0xFF5E:
        return 1.75
    return 1.0


def weighted_length(text: str) -> float:
    return sum(_char_weight(char) for char in str(text))


def requires_split(
    source: str,
    translation: str,
    *,
    max_chars: int,
    target_multiplier: float,
) -> bool:
    return len(source) > max_chars or weighted_length(translation) * target_multiplier > max_chars


_PUNCTUATION = frozenset(",;:!?。！？、")


def _boundary_candidates(source: str) -> list[tuple[int, int]]:
    """Return (priority, index) boundaries after words and punctuation."""
    candidates: list[tuple[int, int]] = []
    for match in re.finditer(r"\S+", source):
        end = match.end()
        token = match.group(0)
        priority = 1 if token[-1] in _PUNCTUATION else 2
        candidates.append((priority, end))
    if not candidates:
        return []
    return candidates


def _choose_split_index(source: str, max_chars: int) -> int:
    midpoint = len(source) / 2
    candidates = [
        (priority, index)
        for priority, index in _boundary_candidates(source)
        if source[:index].strip() and source[index:].strip()
    ]
    if candidates:
        best_priority = min(priority for priority, _ in candidates)
        preferred = [index for priority, index in candidates if priority == best_priority]
        return min(preferred, key=lambda index: abs(index - midpoint))

    if not source:
        raise ValueError("cannot split empty source")
    return max(1, min(len(source) - 1, max_chars))


def _word_spans(source: str, words: list[TranslationWordInput]) -> list[tuple[int, int, TranslationWordInput]] | None:
    spans: list[tuple[int, int, TranslationWordInput]] = []
    cursor = 0
    for word in words:
        index = source.find(word.word, cursor)
        if index < 0:
            return None
        spans.append((index, index + len(word.word), word))
        cursor = index + len(word.word)
    if not spans:
        return None
    return spans


def _part_words(
    spans: list[tuple[int, int, TranslationWordInput]] | None,
    start: int,
    end: int,
) -> tuple[TranslationWordInput, ...] | None:
    if spans is None:
        return None
    selected: list[TranslationWordInput] = []
    for word_start, word_end, word in spans:
        if word_end <= start or word_start >= end:
            continue
        if word_start < start or word_end > end:
            return None
        selected.append(word)
    return tuple(selected) if selected else None


def _proportional_range(
    start: float,
    end: float,
    left_text: str,
    right_text: str,
) -> tuple[tuple[float, float], tuple[float, float]]:
    total = max(1, len(left_text) + len(right_text))
    split_time = start + (end - start) * len(left_text) / total
    return (start, split_time), (split_time, end)


def split_timed_source(
    *,
    source: str,
    start: float,
    end: float,
    words: list[TranslationWordInput],
    max_chars: int,
) -> tuple[TimedSourcePart, TimedSourcePart]:
    source = source.strip()
    if len(source) < 2:
        raise ValueError("source is too short to split")
    if end <= start:
        raise ValueError("source duration must be positive")

    split_index = _choose_split_index(source, max_chars)
    left_text = source[:split_index].strip()
    right_text = source[split_index:].strip()
    if not left_text or not right_text:
        raise ValueError("source split produced an empty part")

    left_offset = source.find(left_text)
    right_offset = source.find(right_text, left_offset + len(left_text))
    spans = _word_spans(source, words)
    left_words = _part_words(spans, left_offset, right_offset)
    right_words = _part_words(spans, right_offset, len(source))

    if left_words is not None and right_words is not None:
        left_range = (left_words[0].start, left_words[-1].end)
        right_range = (right_words[0].start, right_words[-1].end)
    else:
        left_range, right_range = _proportional_range(start, end, left_text, right_text)
        left_words = tuple()
        right_words = tuple()

    return (
        TimedSourcePart(left_text, left_range[0], left_range[1], left_words),
        TimedSourcePart(right_text, right_range[0], right_range[1], right_words),
    )


def close_short_gaps(
    parts: list[DisplayCaptionSegment],
    *,
    threshold: float,
) -> list[DisplayCaptionSegment]:
    result = [part.model_copy(deep=True) for part in parts]
    for index in range(len(result) - 1):
        current = result[index]
        following = result[index + 1]
        gap = following.start - current.end
        if current.parent_id == following.parent_id and 0 < gap < threshold:
            result[index] = current.model_copy(update={"end": following.start})
    return result
