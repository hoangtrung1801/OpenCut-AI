"""Contextual transcript translation routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.models.translation import (
    ContextualTranslationLimits,
    ContextualTranslationRequest,
    ContextualTranslationResponse,
)
from app.services.contextual_translation import (
    ContextualTranslationError,
    ContextualTranslationService,
)
from app.services.model_backend import llm_backend

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/translations", tags=["translations"])
translation_service = ContextualTranslationService(
    backend=llm_backend,
    limits=ContextualTranslationLimits.from_settings(settings),
)


@router.post("/contextual", response_model=ContextualTranslationResponse)
async def contextual_translation(
    request: ContextualTranslationRequest,
) -> ContextualTranslationResponse:
    if not await llm_backend.check_available():
        raise HTTPException(status_code=503, detail="No LLM backend available.")
    try:
        return await translation_service.translate(request)
    except ContextualTranslationError as exc:
        logger.warning(
            "Contextual translation failed: %s",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail="Contextual translation failed.",
        ) from exc
