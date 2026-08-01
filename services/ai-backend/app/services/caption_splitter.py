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


def normalize_caption_text(text: str) -> str:
    return " ".join(str(text).split())


def _text_boundary_candidates(text: str) -> list[tuple[int, int]]:
    candidates: list[tuple[int, int]] = []
    for match in re.finditer(r"\S+", text):
        index = match.end()
        if index < len(text):
            token = match.group(0)
            priority = 1 if token[-1] in _SENTENCE_PUNCTUATION else 3
            if token[-1] in _PHRASE_PUNCTUATION:
                priority = 2
            candidates.append((priority, index))
    if candidates:
        return candidates
    return [
        (
            1
            if text[index - 1] in _SENTENCE_PUNCTUATION
            else 2
            if text[index - 1] in _PHRASE_PUNCTUATION
            else 3,
            index,
        )
        for index in range(1, len(text))
    ]


def wrap_caption_text(
    text: str,
    *,
    max_chars: int,
    max_lines: int = 2,
) -> str:
    normalized = normalize_caption_text(text)
    if not normalized:
        raise ValueError("caption text cannot be empty")
    if max_chars <= 0 or max_lines <= 0:
        raise ValueError("caption limits must be positive")
    if weighted_length(normalized) <= max_chars:
        return normalized
    if max_lines == 1 or weighted_length(normalized) > max_chars * max_lines:
        raise ValueError("caption exceeds the configured display length")

    candidates = []
    for priority, index in _text_boundary_candidates(normalized):
        left = normalized[:index].strip()
        right = normalized[index:].strip()
        if not left or not right or right[0] in _PUNCTUATION:
            continue
        if weighted_length(left) <= max_chars and weighted_length(right) <= max_chars:
            candidates.append(
                (priority, abs(weighted_length(left) - weighted_length(right)), left, right)
            )
    if not candidates:
        for index in range(1, len(normalized)):
            left = normalized[:index].strip()
            right = normalized[index:].strip()
            if (
                left
                and right
                and not _punctuation_only(left)
                and right[0] not in _PUNCTUATION
                and weighted_length(left) <= max_chars
                and weighted_length(right) <= max_chars
            ):
                candidates.append(
                    (4, abs(weighted_length(left) - weighted_length(right)), left, right)
                )
    if not candidates:
        raise ValueError("caption cannot be wrapped at a readable boundary")
    _, _, left, right = min(candidates, key=lambda item: (item[0], item[1]))
    return f"{left}\n{right}"


def caption_fits(
    text: str,
    *,
    max_chars: int,
    max_lines: int = 2,
) -> bool:
    try:
        wrap_caption_text(text, max_chars=max_chars, max_lines=max_lines)
    except ValueError:
        return False
    return True


def requires_split(
    source: str,
    translation: str,
    *,
    max_chars: int,
    target_multiplier: float,
    max_lines: int = 2,
) -> bool:
    return (
        not caption_fits(source, max_chars=max_chars, max_lines=max_lines)
        or not caption_fits(translation, max_chars=max_chars, max_lines=max_lines)
        or weighted_length(normalize_caption_text(translation)) * target_multiplier
        > max_chars * max_lines
    )


_PUNCTUATION = frozenset(",;:!?。！？、")
_SENTENCE_PUNCTUATION = frozenset(".!?。！？")
_PHRASE_PUNCTUATION = frozenset(",;:、，；：")


def _boundary_candidates(
    source: str,
    spans: list[tuple[int, int, TranslationWordInput]] | None = None,
) -> list[tuple[int, int]]:
    """Return readable boundaries, including Whisper spans for no-space scripts."""
    if spans:
        return [
            (
                1
                if source[word_start:word_end][-1] in _SENTENCE_PUNCTUATION
                else 2
                if source[word_start:word_end][-1] in _PHRASE_PUNCTUATION
                else 3,
                word_end,
            )
            for word_start, word_end, _ in spans
            if word_end < len(source)
        ]
    token_candidates = _text_boundary_candidates(source)
    if token_candidates:
        return token_candidates
    return []


def _punctuation_only(text: str) -> bool:
    return bool(text) and all(char in _PUNCTUATION for char in text)


def _choose_split_index(
    source: str,
    max_chars: int,
    *,
    candidates: list[tuple[int, int]] | None = None,
) -> int:
    midpoint = len(source) / 2
    candidates = [
        (priority, index)
        for priority, index in (candidates or _boundary_candidates(source))
        if source[:index].strip()
        and source[index:].strip()
        and not _punctuation_only(source[:index].strip())
        and not _punctuation_only(source[index:].strip())
    ]
    if candidates:
        best_priority = min(priority for priority, _ in candidates)
        preferred = [index for priority, index in candidates if priority == best_priority]
        return min(preferred, key=lambda index: abs(index - midpoint))

    if not source:
        raise ValueError("cannot split empty source")
    fallback = max(1, min(len(source) - 1, max_chars))
    if _punctuation_only(source[fallback:].strip()):
        for index in range(fallback - 1, 0, -1):
            if not _punctuation_only(source[index:].strip()):
                return index
    return fallback


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
    min_duration: float = 0,
) -> tuple[TimedSourcePart, TimedSourcePart]:
    source = source.strip()
    if len(source) < 2:
        raise ValueError("source is too short to split")
    if end <= start:
        raise ValueError("source duration must be positive")
    if min_duration < 0:
        raise ValueError("minimum duration cannot be negative")

    spans = _word_spans(source, words)
    candidate_boundaries = _boundary_candidates(source, spans)
    valid_boundaries: list[tuple[int, int]] = []
    for priority, index in candidate_boundaries:
        left_text = source[:index].strip()
        right_text = source[index:].strip()
        if (
            not left_text
            or not right_text
            or _punctuation_only(left_text)
            or _punctuation_only(right_text)
        ):
            continue
        left_offset = source.find(left_text)
        right_offset = source.find(right_text, left_offset + len(left_text))
        left_words = _part_words(spans, left_offset, right_offset)
        right_words = _part_words(spans, right_offset, len(source))
        if left_words and right_words:
            left_start, left_end = left_words[0].start, left_words[-1].end
            right_start, right_end = right_words[0].start, right_words[-1].end
        else:
            (left_start, left_end), (right_start, right_end) = _proportional_range(
                start, end, left_text, right_text
            )
        if (
            left_end - left_start >= min_duration
            and right_end - right_start >= min_duration
        ):
            valid_boundaries.append((priority, index))
    split_index = _choose_split_index(
        source,
        max_chars,
        candidates=valid_boundaries or candidate_boundaries,
    )
    left_text = source[:split_index].strip()
    right_text = source[split_index:].strip()
    if not left_text or not right_text:
        raise ValueError("source split produced an empty part")

    left_offset = source.find(left_text)
    right_offset = source.find(right_text, left_offset + len(left_text))
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
