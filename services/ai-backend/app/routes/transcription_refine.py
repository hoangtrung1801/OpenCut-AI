"""Internal LLM boundary refinement for the Whisper service."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.model_backend import llm_backend

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/internal/transcription", tags=["internal-transcription"])


class IndexedWord(BaseModel):
    index: int = Field(..., ge=0)
    word: str = Field(..., min_length=1)


class RefineRequest(BaseModel):
    language: str = Field(..., min_length=2, max_length=16)
    words: list[IndexedWord] = Field(..., min_length=1, max_length=60)
    candidates: list[int] = Field(default_factory=list)
    previous_error: str | None = Field(default=None, max_length=500)


def _validate_indexes(value: Any, word_count: int) -> list[int]:
    if not isinstance(value, list):
        raise ValueError("split_after must be a list")
    if any(isinstance(index, bool) or not isinstance(index, int) for index in value):
        raise ValueError("split_after must contain integers")
    if value != sorted(value) or len(value) != len(set(value)):
        raise ValueError("split_after must be strictly increasing")
    if any(index < 0 or index >= word_count - 1 for index in value):
        raise ValueError("split_after contains an out-of-range index")
    return value


@router.post("/refine")
async def refine_transcription(request: RefineRequest) -> dict[str, list[int]]:
    indexed_words = [{"index": item.index, "word": item.word} for item in request.words]
    prompt = (
        "You refine transcript sentence boundaries. Return ONLY a JSON object with the key "
        '"split_after" whose value is a sorted list of inclusive word indexes. '
        "Do not rewrite, translate, or omit words. Keep every part at most 20 words and "
        "prefer the supplied deterministic candidates.\n"
        f"Language: {request.language}\n"
        f"Indexed words: {indexed_words}\n"
        f"Deterministic candidates: {request.candidates}\n"
    )
    if request.previous_error:
        prompt += f"Previous validation error to correct: {request.previous_error}\n"

    try:
        response = await llm_backend.generate_json(
            prompt=prompt,
            system="You output strict JSON only.",
        )
    except Exception as exc:
        logger.warning("Semantic refinement backend failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Semantic refinement unavailable.") from exc

    try:
        if not isinstance(response, dict):
            raise ValueError("response must be an object")
        indexes = _validate_indexes(response.get("split_after"), len(request.words))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"split_after": indexes}

