"""Shared public and internal data models for the Whisper service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class WordToken:
    raw_text: str
    word: str
    start: float
    end: float
    probability: float
    source_segment_id: int
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0


@dataclass(frozen=True)
class PreparedMedia:
    artifact_id: str
    asr_path: Path
    alignment_path: Path
    vocals_path: Path
    background_path: Path
    temporary_paths: tuple[Path, ...] = ()


class SeparatedAudio(BaseModel):
    vocals_url: str
    background_url: str


class TranscriptionWord(BaseModel):
    word: str
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    probability: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Confidence score"
    )


class TranscriptionSegment(BaseModel):
    id: int
    text: str
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    words: list[TranscriptionWord] = Field(default_factory=list)
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0


class TranscriptionResult(BaseModel):
    text: str = Field(..., description="Full transcribed text")
    segments: list[TranscriptionSegment] = Field(default_factory=list)
    language: str = Field(default="en", description="Detected or specified language")
    duration: float = Field(default=0.0, description="Audio duration in seconds")
    separated_audio: SeparatedAudio | None = None
