"""Local, in-process dubbing job API."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.config import settings
from app.models.dubbing import (
    DubbingJobAccepted,
    DubbingJobCreateRequest,
    DubbingJobSnapshot,
    DubbingLimits,
)
from app.services.dubbing_service import DubbingJobManager, DubbingJobNotFound
from app.services.dubbing_tts_client import DubbingTTSClient

router = APIRouter(prefix="/api/dubbing", tags=["dubbing"])

job_manager = DubbingJobManager(
    generated_root=settings.GENERATED_DIR,
    limits=DubbingLimits.from_settings(settings),
    tts_client=DubbingTTSClient(
        base_url=settings.TTS_SERVICE_URL,
        retries=settings.DUBBING_TTS_RETRIES,
    ),
)


@router.post(
    "/jobs",
    response_model=DubbingJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_dubbing_job(request: DubbingJobCreateRequest) -> DubbingJobAccepted:
    """Queue a dubbing job and return immediately with its ID."""
    return job_manager.create(request)


@router.get("/jobs/{job_id}", response_model=DubbingJobSnapshot)
async def get_dubbing_job(job_id: UUID) -> DubbingJobSnapshot:
    try:
        return job_manager.get(job_id)
    except DubbingJobNotFound as exc:
        raise HTTPException(status_code=404, detail="Dubbing job not found.") from exc
