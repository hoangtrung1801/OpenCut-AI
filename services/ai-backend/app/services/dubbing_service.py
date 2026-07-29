"""Queued orchestration for local timing-fitted dubbing jobs."""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

from app.models.dubbing import (
    DubbingCaptionResult,
    DubbingClipResult,
    DubbingJobAccepted,
    DubbingJobCreateRequest,
    DubbingJobSnapshot,
    DubbingJobStatus,
    DubbingLimits,
    DubbingPublicError,
    DubbingResult,
)
from app.services.dubbing_audio import (
    DubbingAudioProcessor,
    fit_chunk_timing,
)
from app.services.dubbing_planner import (
    DubbingClipTask,
    DubbingPlan,
    build_dubbing_plan,
)
from app.services.dubbing_tts_client import (
    DubbingTTSClient,
    DubbingTTSGenerationError,
    DubbingTTSUnavailable,
)

logger = logging.getLogger(__name__)


class DubbingJobNotFound(KeyError):
    """No in-process job exists for the requested ID."""


@dataclass
class _MutableJob:
    request: DubbingJobCreateRequest
    status: DubbingJobStatus = DubbingJobStatus.QUEUED
    completed_clips: int = 0
    total_clips: int = 0
    result: DubbingResult | None = None
    error: DubbingPublicError | None = None

    def snapshot(self, job_id: UUID) -> DubbingJobSnapshot:
        return DubbingJobSnapshot(
            job_id=job_id,
            status=self.status,
            completed_clips=self.completed_clips,
            total_clips=self.total_clips,
            result=self.result,
            error=self.error,
        )


StatusObserver = Callable[[DubbingJobStatus], None]


class DubbingJobManager:
    def __init__(
        self,
        *,
        generated_root: Path,
        limits: DubbingLimits,
        tts_client: DubbingTTSClient,
        audio_processor: DubbingAudioProcessor | None = None,
        status_observer: StatusObserver | None = None,
    ):
        self.generated_root = Path(generated_root)
        self.limits = limits
        self.tts_client = tts_client
        self.audio_processor = audio_processor or DubbingAudioProcessor()
        self.status_observer = status_observer
        self._jobs: dict[UUID, _MutableJob] = {}
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._job_semaphore = asyncio.Semaphore(limits.max_concurrent_jobs)

    def create(self, request: DubbingJobCreateRequest) -> DubbingJobAccepted:
        job_id = uuid4()
        job = _MutableJob(
            request=request,
            total_clips=len(request.display_segments),
        )
        self._jobs[job_id] = job
        self._tasks[job_id] = asyncio.create_task(self.run(job_id))
        return DubbingJobAccepted(
            job_id=job_id,
            status=DubbingJobStatus.QUEUED,
        )

    def get(self, job_id: UUID) -> DubbingJobSnapshot:
        try:
            return self._jobs[job_id].snapshot(job_id)
        except KeyError as exc:
            raise DubbingJobNotFound(str(job_id)) from exc

    async def wait(self, job_id: UUID) -> None:
        try:
            task = self._tasks[job_id]
        except KeyError as exc:
            raise DubbingJobNotFound(str(job_id)) from exc
        await task

    def _set_status(self, job_id: UUID, status: DubbingJobStatus) -> None:
        job = self._jobs[job_id]
        job.status = status
        if self.status_observer is not None:
            self.status_observer(status)

    async def run(self, job_id: UUID) -> None:
        async with self._job_semaphore:
            job = self._jobs[job_id]
            try:
                self._set_status(job_id, DubbingJobStatus.PREPARING)
                plan = build_dubbing_plan(job.request, self.limits)
                job_dir = self.generated_root / str(job_id)
                raw_paths = await self._generate_raw_clips(job_id, job, plan, job_dir)
                self._set_status(job_id, DubbingJobStatus.FITTING)
                job.result = await self._fit_and_publish(
                    job_id=job_id,
                    job=job,
                    plan=plan,
                    raw_paths=raw_paths,
                    job_dir=job_dir,
                )
                self._set_status(job_id, DubbingJobStatus.COMPLETED)
            except Exception as exc:
                logger.warning(
                    "Dubbing job %s failed: %s",
                    job_id,
                    type(exc).__name__,
                )
                job.error = self._public_error(exc)
                self._set_status(job_id, DubbingJobStatus.FAILED)

    async def _generate_raw_clips(
        self,
        job_id: UUID,
        job: _MutableJob,
        plan: DubbingPlan,
        job_dir: Path,
    ) -> dict[int, Path]:
        await self.tts_client.check_ready()
        self._set_status(job_id, DubbingJobStatus.GENERATING)
        raw_dir = job_dir / "raw"
        semaphore = asyncio.Semaphore(self.limits.max_tts_concurrency)
        raw_paths: dict[int, Path] = {}
        progress_lock = asyncio.Lock()

        async def generate(clip: DubbingClipTask) -> None:
            destination = raw_dir / f"{clip.id}.wav"
            async with semaphore:
                if clip.tts_text:
                    await self.tts_client.generate_to_file(
                        text=clip.tts_text,
                        language=job.request.target_language,
                        voice=job.request.voice,
                        pace=job.request.pace,
                        destination=destination,
                    )
                else:
                    self.audio_processor.write_silence(destination, duration=0.1)
            if not destination.is_file() or destination.stat().st_size == 0:
                raise ValueError("TTS produced an empty audio file")
            raw_paths[clip.id] = destination
            async with progress_lock:
                job.completed_clips += 1

        await asyncio.gather(*(generate(clip) for clip in plan.clips))
        return raw_paths

    async def _fit_and_publish(
        self,
        *,
        job_id: UUID,
        job: _MutableJob,
        plan: DubbingPlan,
        raw_paths: dict[int, Path],
        job_dir: Path,
    ) -> DubbingResult:
        final_dir = job_dir / "clips"
        clip_tasks = {clip.id: clip for clip in plan.clips}
        results: dict[int, DubbingClipResult] = {}

        for chunk in plan.chunks:
            windows = [
                (clip.id, clip.original_start, clip.original_end)
                for clip in chunk.clips
            ]
            raw_durations = {
                clip_id: self.audio_processor.probe_duration(raw_paths[clip_id])
                for clip_id, _, _ in windows
            }
            fit = fit_chunk_timing(
                clip_windows=windows,
                raw_durations=raw_durations,
                allowed_end=chunk.allowed_end,
                accept_speed=self.limits.accept_speed,
                max_speed=self.limits.max_speed,
            )
            for placement in fit.clips:
                task = clip_tasks[placement.id]
                destination = final_dir / f"{task.id}.wav"
                self.audio_processor.adjust_speed(
                    raw_paths[task.id],
                    destination,
                    fit.speed,
                )
                duration = self.audio_processor.probe_duration(destination)
                end = placement.start + duration
                warning = placement.timing_warning
                if end > chunk.allowed_end:
                    warning = "overflow"
                results[task.id] = DubbingClipResult(
                    id=task.id,
                    parent_id=task.parent_id,
                    part_index=task.part_index,
                    text=task.caption_text,
                    start=placement.start,
                    end=end,
                    duration=duration,
                    audio_url=(
                        f"/generated/dubbing/{job_id}/clips/{task.id}.wav"
                    ),
                    timing_warning=warning,
                )

        ordered_clips = [results[clip.id] for clip in plan.clips]
        captions = [
            DubbingCaptionResult(
                id=clip.id,
                parent_id=clip.parent_id,
                part_index=clip.part_index,
                text=clip.text,
                start=clip.start,
                end=clip.end,
            )
            for clip in ordered_clips
        ]
        return DubbingResult(
            clips=ordered_clips,
            captions=captions,
            srt=_build_srt(captions),
        )

    @staticmethod
    def _public_error(exc: Exception) -> DubbingPublicError:
        if isinstance(exc, DubbingTTSUnavailable):
            return DubbingPublicError(
                code="tts_unavailable",
                message="The local TTS service is not ready.",
            )
        if isinstance(exc, DubbingTTSGenerationError):
            return DubbingPublicError(
                code="tts_generation_failed",
                message="Speech generation failed after retries.",
            )
        if isinstance(exc, (FileNotFoundError, ValueError)):
            return DubbingPublicError(
                code="invalid_audio",
                message="The generated audio was invalid or incomplete.",
            )
        if isinstance(exc, (OSError, RuntimeError)):
            return DubbingPublicError(
                code="audio_tool_failed",
                message="The local audio processing tool failed.",
            )
        return DubbingPublicError(
            code="dubbing_failed",
            message="Dubbing could not be completed.",
        )


def _timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    whole_seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


def _build_srt(captions: list[DubbingCaptionResult]) -> str:
    blocks = []
    for index, caption in enumerate(captions, start=1):
        blocks.append(
            "\n".join((
                str(index),
                f"{_timestamp(caption.start)} --> {_timestamp(caption.end)}",
                caption.text,
            ))
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")
