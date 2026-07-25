"""Image and infographic generation API models."""

from typing import Any

from pydantic import BaseModel, Field, ConfigDict


class ImageGenParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    prompt: str = Field(..., min_length=1)
    negative_prompt: str = Field(default="", alias="negativePrompt")
    width: int = Field(default=512, ge=64, le=2048)
    height: int = Field(default=512, ge=64, le=2048)
    steps: int = Field(default=20, ge=1, le=100)
    guidance_scale: float = Field(default=7.5, ge=1.0, le=30.0, alias="guidanceScale")
    seed: int | None = None


class EnhancePromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    style: str = "photorealistic"


class InfographicRequest(BaseModel):
    topic: str = Field(..., min_length=1)
    data_points: list[dict[str, Any]] = Field(default_factory=list)
    style: str = "modern"
    width: int = Field(default=1080, ge=64, le=4096)
    height: int = Field(default=1080, ge=64, le=4096)
    background_color: str = "#00000000"
