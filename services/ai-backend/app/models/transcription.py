"""Models shared by the local transcription service."""

from pydantic import BaseModel, Field


class TranscriptionWord(BaseModel):
    word: str
    start: float
    end: float
    probability: float = Field(default=1.0, ge=0.0, le=1.0)


class TranscriptionSegment(BaseModel):
    id: int
    text: str
    start: float
    end: float
    words: list[TranscriptionWord] = Field(default_factory=list)
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0


class TranscriptionResult(BaseModel):
    text: str = ""
    segments: list[TranscriptionSegment] = Field(default_factory=list)
    language: str = "en"
    duration: float = 0.0
