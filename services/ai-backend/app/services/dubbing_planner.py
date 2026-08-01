"""Deterministic task and timing-chunk construction for dubbing."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.dubbing import (
    DubbingJobCreateRequest,
    DubbingLimits,
    DubbingParentSegment,
)


@dataclass(frozen=True)
class DubbingClipTask:
    id: int
    parent_id: int
    part_index: int
    caption_text: str
    tts_text: str
    original_start: float
    original_end: float


@dataclass(frozen=True)
class DubbingParentTask:
    id: int
    start: float
    end: float
    following_gap: float
    clips: tuple[DubbingClipTask, ...]


@dataclass(frozen=True)
class DubbingChunk:
    parents: tuple[DubbingParentTask, ...]
    clips: tuple[DubbingClipTask, ...]
    start: float
    allowed_end: float


@dataclass(frozen=True)
class DubbingPlan:
    parents: tuple[DubbingParentTask, ...]
    clips: tuple[DubbingClipTask, ...]
    chunks: tuple[DubbingChunk, ...]


def _clean_tts_text(text: str) -> str:
    cleaned = re.sub(r"\([^)]*\)|（[^）]*）", "", text)
    cleaned = "".join(
        character
        for character in cleaned
        if character.isprintable() or character in "\n\t"
    )
    return cleaned.replace("-", "").strip()


def _clip_task(parent: DubbingParentSegment) -> DubbingClipTask:
    return DubbingClipTask(
        id=parent.id,
        parent_id=parent.id,
        part_index=0,
        caption_text=parent.translation,
        tts_text=_clean_tts_text(parent.translation),
        original_start=parent.start,
        original_end=parent.end,
    )


def build_dubbing_plan(
    request: DubbingJobCreateRequest,
    limits: DubbingLimits,
) -> DubbingPlan:
    parents: list[DubbingParentTask] = []
    all_clips: list[DubbingClipTask] = []
    for index, segment in enumerate(request.audio_segments):
        following_gap = (
            request.audio_segments[index + 1].start - segment.end
            if index + 1 < len(request.audio_segments)
            else 0.0
        )
        clips = (_clip_task(segment),)
        parent = DubbingParentTask(
            id=segment.id,
            start=segment.start,
            end=segment.end,
            following_gap=max(0.0, following_gap),
            clips=clips,
        )
        parents.append(parent)
        all_clips.extend(clips)

    chunks: list[DubbingChunk] = []
    pending: list[DubbingParentTask] = []
    for index, parent in enumerate(parents):
        pending.append(parent)
        boundary = (
            parent.following_gap >= limits.gap_tolerance_seconds
            or len(pending) >= limits.max_chunk_segments
            or index == len(parents) - 1
        )
        if not boundary:
            continue
        tail = min(
            pending[-1].following_gap,
            limits.gap_tolerance_seconds,
        )
        chunks.append(
            DubbingChunk(
                parents=tuple(pending),
                clips=tuple(
                    clip
                    for pending_parent in pending
                    for clip in pending_parent.clips
                ),
                start=pending[0].start,
                allowed_end=pending[-1].end + tail,
            )
        )
        pending = []

    return DubbingPlan(
        parents=tuple(parents),
        clips=tuple(all_clips),
        chunks=tuple(chunks),
    )
