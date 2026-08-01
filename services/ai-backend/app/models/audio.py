"""Audio-related API models."""

from pydantic import BaseModel, Field


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    language: str = "en"
    speaker_wav: str | None = None
    reference_text: str | None = None
    speaker: str | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
