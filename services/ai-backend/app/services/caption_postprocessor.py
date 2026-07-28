"""VideoLingo-style alignment and display post-processing for captions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.models.translation import (
    CaptionPostProcessRequest,
    DisplayCaptionSegment,
    TranslatedSegment,
    TranslationWordInput,
    ContextualTranslationLimits,
)
from app.services.caption_splitter import (
    TimedSourcePart,
    close_short_gaps,
    requires_split,
    split_timed_source,
)


class CaptionPostProcessingError(Exception):
    """Base class for caption post-processing failures."""


class CaptionPolicyError(CaptionPostProcessingError):
    """Caption text cannot satisfy the configured display policy."""


class CaptionAlignmentError(CaptionPostProcessingError):
    """The LLM did not align translated parts to the requested source parts."""


class CaptionProviderError(CaptionPostProcessingError):
    """The configured LLM provider failed while aligning caption parts."""


@dataclass(frozen=True)
class CaptionProcessingResult:
    display_segments: list[DisplayCaptionSegment]
    audio_segments: list[TranslatedSegment]


@dataclass(frozen=True)
class _WorkPart:
    parent_id: int
    source: str
    translation: str
    start: float
    end: float
    words: tuple[TranslationWordInput, ...]


class CaptionPostProcessor:
    def __init__(self, *, backend: Any, limits: ContextualTranslationLimits):
        self.backend = backend
        self.limits = limits

    @staticmethod
    def _alignment_prompt(
        request: CaptionPostProcessRequest,
        original_source: str,
        original_translation: str,
        parts: list[TimedSourcePart],
        previous_error: str | None,
    ) -> str:
        payload = [
            {"id": index, "source": part.text}
            for index, part in enumerate(parts)
        ]
        prompt = (
            "Align the original translation to the exact source parts. Return ONLY "
            "a JSON object with an alignments array. Include every integer id exactly "
            "once, in the same order. Do not merge, split, omit, reorder, or rewrite "
            "the source parts. Each alignment must contain a non-empty translation.\n"
            f"Source language: {request.source_language}\n"
            f"Target language: {request.target_language}\n"
            f"Original source: {original_source}\n"
            f"Original translation: {original_translation}\n"
            f"Source parts: {json.dumps(payload, ensure_ascii=False)}\n"
        )
        if previous_error:
            prompt += f"Previous validation error to correct: {previous_error}\n"
        return prompt

    @staticmethod
    def _validate_alignment(payload: Any, expected_ids: list[int]) -> list[str]:
        if not isinstance(payload, dict):
            raise CaptionAlignmentError("alignment response must be an object")
        raw_alignments = payload.get("alignments")
        if not isinstance(raw_alignments, list):
            raise CaptionAlignmentError("alignment response must contain alignments")

        actual_ids: list[int] = []
        translations: list[str] = []
        for item in raw_alignments:
            if not isinstance(item, dict):
                raise CaptionAlignmentError("alignment items must be objects")
            identifier = item.get("id")
            translation = item.get("translation")
            if (
                isinstance(identifier, bool)
                or not isinstance(identifier, int)
                or not isinstance(translation, str)
                or not translation.strip()
            ):
                raise CaptionAlignmentError("alignment item has an invalid shape")
            actual_ids.append(identifier)
            translations.append(translation.strip())
        if actual_ids != expected_ids:
            raise CaptionAlignmentError(
                f"alignment IDs must exactly match {expected_ids}"
            )
        return translations

    async def _align_parts(
        self,
        request: CaptionPostProcessRequest,
        original_source: str,
        original_translation: str,
        parts: list[TimedSourcePart],
    ) -> list[str]:
        expected_ids = list(range(len(parts)))
        previous_error: str | None = None
        for attempt in range(self.limits.correction_retries + 1):
            try:
                payload = await self.backend.generate_json(
                    prompt=self._alignment_prompt(
                        request,
                        original_source,
                        original_translation,
                        parts,
                        previous_error,
                    ),
                    system="Return strict JSON only.",
                    _retries=0,
                )
                return self._validate_alignment(payload, expected_ids)
            except CaptionAlignmentError as exc:
                previous_error = str(exc)
                if attempt == self.limits.correction_retries:
                    raise
            except Exception as exc:
                raise CaptionProviderError("caption alignment provider failed") from exc
        raise CaptionAlignmentError("caption alignment validation failed")

    async def process_pairs(
        self,
        request: CaptionPostProcessRequest,
    ) -> CaptionProcessingResult:
        audio_segments = [
            TranslatedSegment(
                id=segment.id,
                source=segment.source,
                translation=segment.translation,
                start=segment.start,
                end=segment.end,
            )
            for segment in request.segments
        ]
        parts = [
            _WorkPart(
                parent_id=segment.id,
                source=segment.source,
                translation=segment.translation,
                start=segment.start,
                end=segment.end,
                words=tuple(segment.words),
            )
            for segment in request.segments
        ]

        for _ in range(self.limits.split_passes):
            changed = False
            next_parts: list[_WorkPart] = []
            for part in parts:
                if not requires_split(
                    part.source,
                    part.translation,
                    max_chars=self.limits.max_caption_chars,
                    target_multiplier=self.limits.target_length_multiplier,
                ):
                    next_parts.append(part)
                    continue

                changed = True
                try:
                    source_parts = split_timed_source(
                        source=part.source,
                        start=part.start,
                        end=part.end,
                        words=list(part.words),
                        max_chars=self.limits.max_caption_chars,
                    )
                except ValueError as exc:
                    raise CaptionPolicyError("caption source cannot be split") from exc
                aligned = await self._align_parts(
                    request,
                    part.source,
                    part.translation,
                    list(source_parts),
                )
                for source_part, translation in zip(source_parts, aligned):
                    next_parts.append(
                        _WorkPart(
                            parent_id=part.parent_id,
                            source=source_part.text,
                            translation=translation,
                            start=source_part.start,
                            end=source_part.end,
                            words=source_part.words,
                        )
                    )
            parts = next_parts
            if not changed:
                break

        if any(
            requires_split(
                part.source,
                part.translation,
                max_chars=self.limits.max_caption_chars,
                target_multiplier=self.limits.target_length_multiplier,
            )
            for part in parts
        ):
            raise CaptionPolicyError("caption exceeds the configured display length")

        display_segments: list[DisplayCaptionSegment] = []
        parent_part_indices: dict[int, int] = {}
        for display_id, part in enumerate(parts):
            part_index = parent_part_indices.get(part.parent_id, 0)
            parent_part_indices[part.parent_id] = part_index + 1
            display_segments.append(
                DisplayCaptionSegment(
                    id=display_id,
                    parent_id=part.parent_id,
                    part_index=part_index,
                    source=part.source,
                    translation=part.translation,
                    start=part.start,
                    end=part.end,
                )
            )

        return CaptionProcessingResult(
            display_segments=close_short_gaps(
                display_segments,
                threshold=self.limits.gap_close_seconds,
            ),
            audio_segments=audio_segments,
        )
