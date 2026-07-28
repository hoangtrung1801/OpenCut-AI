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


class TranslationSegmentInput(BaseModel):
    id: int = Field(..., ge=0)
    text: str = Field(..., min_length=1, max_length=20_000)
    start: float = Field(..., ge=0, allow_inf_nan=False)
    end: float = Field(..., ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_time_range(self) -> "TranslationSegmentInput":
        if not isfinite(self.start) or not isfinite(self.end):
            raise ValueError("segment timestamps must be finite")
        if self.end < self.start:
            raise ValueError("segment end must be greater than or equal to start")
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


class ContextualTranslationResponse(BaseModel):
    source_language: str
    target_language: str
    theme: str = Field(..., min_length=1, max_length=2_000)
    terminology: list[TranslationTerm] = Field(default_factory=list)
    segments: list[TranslatedSegment] = Field(default_factory=list)


@dataclass(frozen=True)
class ContextualTranslationLimits:
    summary_chars: int
    max_source_chars: int
    max_segments: int
    batch_chars: int
    batch_segments: int
    max_concurrency: int
    correction_retries: int

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
        )
