"""Schemas for local, timing-fitted dubbing jobs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DubbingParentSegment(BaseModel):
    id: int = Field(..., ge=0)
    source: str = Field(..., min_length=1, max_length=20_000)
    translation: str = Field(..., min_length=1, max_length=20_000)
    start: float = Field(..., ge=0, allow_inf_nan=False)
    end: float = Field(..., ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_time_range(self) -> "DubbingParentSegment":
        if not isfinite(self.start) or not isfinite(self.end):
            raise ValueError("dubbing parent timestamps must be finite")
        if self.end <= self.start:
            raise ValueError("dubbing parent end must be greater than start")
        return self


class DubbingDisplaySegment(BaseModel):
    id: int = Field(..., ge=0)
    parent_id: int = Field(..., ge=0)
    part_index: int = Field(..., ge=0)
    source: str = Field(..., min_length=1, max_length=20_000)
    translation: str = Field(..., min_length=1, max_length=20_000)
    start: float = Field(..., ge=0, allow_inf_nan=False)
    end: float = Field(..., ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_time_range(self) -> "DubbingDisplaySegment":
        if not isfinite(self.start) or not isfinite(self.end):
            raise ValueError("dubbing display timestamps must be finite")
        if self.end <= self.start:
            raise ValueError("dubbing display end must be greater than start")
        return self


class CloneVoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["clone"]
    speaker_wav: str = Field(..., min_length=1, max_length=500)

    @field_validator("speaker_wav")
    @classmethod
    def validate_clone_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or ".." in path.parts
            or path.parts[:2] != ("generated", "voices")
            or path.suffix.lower() not in {".wav", ".mp3", ".flac", ".ogg"}
        ):
            raise ValueError("clone path must be a saved local voice")
        return path.as_posix()


class DesignVoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["design"]
    speaker: str = Field(..., min_length=1, max_length=500)


class AutoVoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["auto"]


DubbingVoice = Annotated[
    CloneVoice | DesignVoice | AutoVoice,
    Field(discriminator="mode"),
]


class DubbingJobCreateRequest(BaseModel):
    source_language: str = Field(..., min_length=2, max_length=16)
    target_language: str = Field(..., min_length=2, max_length=16)
    audio_segments: list[DubbingParentSegment] = Field(..., min_length=1)
    display_segments: list[DubbingDisplaySegment] = Field(..., min_length=1)
    voice: DubbingVoice
    pace: float = Field(default=1.0, ge=0.5, le=2.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_request(self) -> "DubbingJobCreateRequest":
        if self.source_language.casefold() == self.target_language.casefold():
            raise ValueError("source and target languages must differ")

        parent_ids = [segment.id for segment in self.audio_segments]
        if len(parent_ids) != len(set(parent_ids)):
            raise ValueError("dubbing parent IDs must be unique")
        display_ids = [segment.id for segment in self.display_segments]
        if len(display_ids) != len(set(display_ids)):
            raise ValueError("dubbing display IDs must be unique")

        previous_end = -1.0
        for segment in self.audio_segments:
            if segment.start < previous_end:
                raise ValueError("dubbing parent segments must be ordered")
            previous_end = segment.end

        parents = {segment.id: segment for segment in self.audio_segments}
        by_parent: dict[int, list[DubbingDisplaySegment]] = {}
        for display in self.display_segments:
            parent = parents.get(display.parent_id)
            if parent is None:
                raise ValueError("dubbing display parent does not exist")
            if display.start < parent.start or display.end > parent.end:
                raise ValueError("dubbing display timestamps must stay in parent")
            by_parent.setdefault(display.parent_id, []).append(display)

        for parent_id, displays in by_parent.items():
            indices = sorted(display.part_index for display in displays)
            if indices != list(range(len(indices))):
                raise ValueError(f"dubbing display parts for {parent_id} must be contiguous")
            previous_display_end = parents[parent_id].start
            for display in sorted(displays, key=lambda item: item.part_index):
                if display.start < previous_display_end:
                    raise ValueError("dubbing display parts must be ordered")
                previous_display_end = display.end
        return self


@dataclass(frozen=True)
class DubbingLimits:
    max_concurrent_jobs: int
    max_tts_concurrency: int
    max_chunk_segments: int
    accept_speed: float
    max_speed: float
    gap_tolerance_seconds: float
    tts_retries: int

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if name == "tts_retries":
                if value < 0:
                    raise ValueError("tts_retries cannot be negative")
                continue
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.accept_speed > self.max_speed:
            raise ValueError("accept_speed cannot exceed max_speed")

    @classmethod
    def from_settings(cls, value: Any) -> "DubbingLimits":
        return cls(
            max_concurrent_jobs=value.DUBBING_MAX_CONCURRENT_JOBS,
            max_tts_concurrency=value.DUBBING_MAX_TTS_CONCURRENCY,
            max_chunk_segments=value.DUBBING_MAX_CHUNK_SEGMENTS,
            accept_speed=value.DUBBING_ACCEPT_SPEED,
            max_speed=value.DUBBING_MAX_SPEED,
            gap_tolerance_seconds=value.DUBBING_GAP_TOLERANCE_SECONDS,
            tts_retries=value.DUBBING_TTS_RETRIES,
        )


class DubbingJobStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    GENERATING = "generating"
    FITTING = "fitting"
    COMPLETED = "completed"
    FAILED = "failed"


class DubbingPublicError(BaseModel):
    code: str
    message: str


class DubbingClipResult(BaseModel):
    id: int
    parent_id: int
    part_index: int
    text: str = Field(..., min_length=1)
    start: float = Field(..., ge=0, allow_inf_nan=False)
    end: float = Field(..., ge=0, allow_inf_nan=False)
    duration: float = Field(..., gt=0, allow_inf_nan=False)
    audio_url: str
    timing_warning: Literal["overflow"] | None = None


class DubbingCaptionResult(BaseModel):
    id: int
    parent_id: int
    part_index: int
    text: str = Field(..., min_length=1)
    start: float = Field(..., ge=0, allow_inf_nan=False)
    end: float = Field(..., gt=0, allow_inf_nan=False)


class DubbingResult(BaseModel):
    clips: list[DubbingClipResult] = Field(default_factory=list)
    captions: list[DubbingCaptionResult] = Field(default_factory=list)
    srt: str


class DubbingJobAccepted(BaseModel):
    job_id: UUID
    status: DubbingJobStatus


class DubbingJobSnapshot(BaseModel):
    job_id: UUID
    status: DubbingJobStatus
    completed_clips: int = Field(default=0, ge=0)
    total_clips: int = Field(default=0, ge=0)
    result: DubbingResult | None = None
    error: DubbingPublicError | None = None
