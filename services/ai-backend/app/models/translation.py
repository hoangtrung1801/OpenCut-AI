"""Schemas and runtime limits for contextual transcript translation."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

from pydantic import BaseModel, Field, model_validator


class TranslationTerm(BaseModel):
    source: str = Field(..., min_length=1, max_length=200)
    target: str = Field(..., min_length=1, max_length=200)
    note: str = Field(..., min_length=1, max_length=200)


class TranslationWordInput(BaseModel):
    word: str = Field(..., min_length=1, max_length=1_000)
    start: float = Field(..., ge=0, allow_inf_nan=False)
    end: float = Field(..., ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_time_range(self) -> "TranslationWordInput":
        if not isfinite(self.start) or not isfinite(self.end):
            raise ValueError("word timestamps must be finite")
        if self.end <= self.start:
            raise ValueError("word end must be greater than word start")
        return self


def _drop_invalid_word_timings(value: Any) -> Any:
    """Keep segment text usable when an upstream editor sends stale word spans."""
    if not isinstance(value, dict) or not value.get("words"):
        return value
    try:
        segment_start = float(value["start"])
        segment_end = float(value["end"])
        previous_end = segment_start
        for raw_word in value["words"]:
            word_start = float(raw_word["start"])
            word_end = float(raw_word["end"])
            if (
                not isfinite(word_start)
                or not isfinite(word_end)
                or word_end <= word_start
                or word_start < segment_start
                or word_end > segment_end
                or word_start < previous_end
            ):
                return {**value, "words": []}
            previous_end = word_end
    except (KeyError, TypeError, ValueError):
        return value
    return value


class TranslationSegmentInput(BaseModel):
    id: int = Field(..., ge=0)
    text: str = Field(..., min_length=1, max_length=20_000)
    start: float = Field(..., ge=0, allow_inf_nan=False)
    end: float = Field(..., ge=0, allow_inf_nan=False)
    words: list[TranslationWordInput] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def discard_invalid_word_timings(cls, value: Any) -> Any:
        return _drop_invalid_word_timings(value)

    @model_validator(mode="after")
    def validate_time_range(self) -> "TranslationSegmentInput":
        if not isfinite(self.start) or not isfinite(self.end):
            raise ValueError("segment timestamps must be finite")
        if self.end <= self.start:
            raise ValueError("segment end must be greater than segment start")
        previous_end = self.start
        for word in self.words:
            if word.start < self.start or word.end > self.end:
                raise ValueError("word timestamps must stay within the segment")
            if word.start < previous_end:
                raise ValueError("word timestamps must be ordered and non-overlapping")
            previous_end = word.end
        return self


class ContextualTranslationRequest(BaseModel):
    source_language: str = Field(..., min_length=2, max_length=16)
    target_language: str = Field(..., min_length=2, max_length=16)
    segments: list[TranslationSegmentInput] = Field(..., min_length=1)
    custom_terms: list[TranslationTerm] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_request(self) -> "ContextualTranslationRequest":
        if self.source_language.casefold() == self.target_language.casefold():
            raise ValueError("source and target languages must differ")
        ids = [segment.id for segment in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError("segment IDs must be unique")
        return self


class TranslatedSegment(BaseModel):
    id: int = Field(..., ge=0)
    source: str = Field(..., min_length=1, max_length=20_000)
    translation: str = Field(..., min_length=1, max_length=20_000)
    start: float = Field(..., ge=0, allow_inf_nan=False)
    end: float = Field(..., ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_time_range(self) -> "TranslatedSegment":
        if not isfinite(self.start) or not isfinite(self.end):
            raise ValueError("translated timestamps must be finite")
        if self.end <= self.start:
            raise ValueError("translated segment end must be greater than start")
        return self


class CaptionTranslationInput(BaseModel):
    id: int = Field(..., ge=0)
    source: str = Field(..., min_length=1, max_length=20_000)
    translation: str = Field(..., min_length=1, max_length=20_000)
    start: float = Field(..., ge=0, allow_inf_nan=False)
    end: float = Field(..., ge=0, allow_inf_nan=False)
    words: list[TranslationWordInput] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def discard_invalid_word_timings(cls, value: Any) -> Any:
        return _drop_invalid_word_timings(value)

    @model_validator(mode="after")
    def validate_time_range(self) -> "CaptionTranslationInput":
        if not isfinite(self.start) or not isfinite(self.end):
            raise ValueError("caption timestamps must be finite")
        if self.end <= self.start:
            raise ValueError("caption end must be greater than start")
        previous_end = self.start
        for word in self.words:
            if word.start < self.start or word.end > self.end:
                raise ValueError("word timestamps must stay within the caption")
            if word.start < previous_end:
                raise ValueError("word timestamps must be ordered and non-overlapping")
            previous_end = word.end
        return self


class CaptionPostProcessRequest(BaseModel):
    source_language: str = Field(..., min_length=2, max_length=16)
    target_language: str = Field(..., min_length=2, max_length=16)
    segments: list[CaptionTranslationInput] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_request(self) -> "CaptionPostProcessRequest":
        if self.source_language.casefold() == self.target_language.casefold():
            raise ValueError("source and target languages must differ")
        ids = [segment.id for segment in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError("segment IDs must be unique")
        return self


class DisplayCaptionSegment(BaseModel):
    id: int = Field(..., ge=0)
    parent_id: int = Field(..., ge=0)
    part_index: int = Field(..., ge=0)
    source: str = Field(..., min_length=1, max_length=20_000)
    translation: str = Field(..., min_length=1, max_length=20_000)
    start: float = Field(..., ge=0, allow_inf_nan=False)
    end: float = Field(..., ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_time_range(self) -> "DisplayCaptionSegment":
        if not isfinite(self.start) or not isfinite(self.end):
            raise ValueError("display timestamps must be finite")
        if self.end <= self.start:
            raise ValueError("display end must be greater than start")
        return self


class SubtitleVariants(BaseModel):
    srt: str
    vtt: str


class SubtitleDocumentSet(BaseModel):
    source: SubtitleVariants
    translation: SubtitleVariants
    source_translation: SubtitleVariants
    translation_source: SubtitleVariants


class ContextualTranslationResponse(BaseModel):
    source_language: str
    target_language: str
    theme: str = Field(..., min_length=1, max_length=2_000)
    terminology: list[TranslationTerm] = Field(default_factory=list)
    segments: list[TranslatedSegment] = Field(default_factory=list)
    display_segments: list[DisplayCaptionSegment] = Field(default_factory=list)
    audio_segments: list[TranslatedSegment] = Field(default_factory=list)
    subtitles: SubtitleDocumentSet


class CaptionPostProcessResponse(BaseModel):
    source_language: str
    target_language: str
    display_segments: list[DisplayCaptionSegment] = Field(default_factory=list)
    audio_segments: list[TranslatedSegment] = Field(default_factory=list)
    subtitles: SubtitleDocumentSet


@dataclass(frozen=True)
class ContextualTranslationLimits:
    summary_chars: int
    max_source_chars: int
    max_segments: int
    batch_chars: int
    batch_segments: int
    max_concurrency: int
    correction_retries: int
    max_caption_chars: int
    target_length_multiplier: float
    split_passes: int
    max_split_passes: int
    min_caption_duration: float
    gap_close_seconds: float

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if name == "correction_retries":
                if value < 0:
                    raise ValueError("correction_retries cannot be negative")
                continue
            if value <= 0:
                raise ValueError(f"{name} must be positive")

    @classmethod
    def from_settings(cls, value: Any) -> "ContextualTranslationLimits":
        return cls(
            summary_chars=value.CONTEXT_TRANSLATION_SUMMARY_CHARS,
            max_source_chars=value.CONTEXT_TRANSLATION_MAX_SOURCE_CHARS,
            max_segments=value.CONTEXT_TRANSLATION_MAX_SEGMENTS,
            batch_chars=value.CONTEXT_TRANSLATION_BATCH_CHARS,
            batch_segments=value.CONTEXT_TRANSLATION_BATCH_SEGMENTS,
            max_concurrency=value.CONTEXT_TRANSLATION_MAX_CONCURRENCY,
            correction_retries=value.CONTEXT_TRANSLATION_CORRECTION_RETRIES,
            max_caption_chars=value.CONTEXT_TRANSLATION_MAX_CAPTION_CHARS,
            target_length_multiplier=value.CONTEXT_TRANSLATION_TARGET_LENGTH_MULTIPLIER,
            split_passes=value.CONTEXT_TRANSLATION_SPLIT_PASSES,
            max_split_passes=value.CONTEXT_TRANSLATION_MAX_SPLIT_PASSES,
            min_caption_duration=value.CONTEXT_TRANSLATION_MIN_CAPTION_DURATION,
            gap_close_seconds=value.CONTEXT_TRANSLATION_GAP_CLOSE_SECONDS,
        )
