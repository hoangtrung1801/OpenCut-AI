"""Contextual transcript translation routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.models.translation import (
    CaptionPostProcessRequest,
    CaptionPostProcessResponse,
    ContextualTranslationLimits,
    ContextualTranslationRequest,
    ContextualTranslationResponse,
)
from app.services.caption_postprocessor import (
    CaptionAlignmentError,
    CaptionPolicyError,
    CaptionPostProcessingError,
    CaptionProviderError,
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
caption_processor = translation_service.caption_processor


@router.post("/contextual", response_model=ContextualTranslationResponse)
async def contextual_translation(
    request: ContextualTranslationRequest,
) -> ContextualTranslationResponse:
    if not await llm_backend.check_available():
        raise HTTPException(status_code=503, detail="No LLM backend available.")
    try:
        return await translation_service.translate(request)
    except CaptionPolicyError as exc:
        logger.warning("Contextual caption policy failed: %s", type(exc).__name__)
        raise HTTPException(status_code=422, detail="Caption policy validation failed.") from exc
    except CaptionProviderError as exc:
        logger.warning("Contextual caption provider failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Caption alignment provider unavailable.") from exc
    except CaptionAlignmentError as exc:
        logger.warning("Contextual caption alignment failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Caption alignment failed.") from exc
    except ContextualTranslationError as exc:
        logger.warning(
            "Contextual translation failed: %s",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail="Contextual translation failed.",
        ) from exc


@router.post(
    "/captions/post-process",
    response_model=CaptionPostProcessResponse,
)
async def post_process_captions(
    request: CaptionPostProcessRequest,
) -> CaptionPostProcessResponse:
    try:
        return await caption_processor.process(request)
    except CaptionPolicyError as exc:
        logger.warning("Caption policy failed: %s", type(exc).__name__)
        raise HTTPException(status_code=422, detail="Caption policy validation failed.") from exc
    except CaptionProviderError as exc:
        logger.warning("Caption provider failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Caption alignment provider unavailable.") from exc
    except CaptionAlignmentError as exc:
        logger.warning("Caption alignment failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Caption alignment failed.") from exc
    except CaptionPostProcessingError as exc:
        logger.warning("Caption post-processing failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Caption post-processing failed.") from exc
