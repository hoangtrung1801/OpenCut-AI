"""VideoLingo-style alignment and display post-processing for captions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.models.translation import (
    CaptionPostProcessResponse,
    CaptionPostProcessRequest,
    DisplayCaptionSegment,
    TranslatedSegment,
    TranslationWordInput,
    ContextualTranslationLimits,
)
from app.services.caption_splitter import (
    TimedSourcePart,
    close_short_gaps,
    normalize_caption_text,
    requires_split,
    split_timed_source,
    wrap_caption_text,
)
from app.services.subtitle_service import build_subtitle_documents


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
            "the source parts. Each translation must be the exact contiguous slice "
            "of the original translation for that source part: do not rewrite, "
            "repeat, omit, or invent words. Do not include newline characters.\n"
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
    def _validate_alignment(
        payload: Any,
        expected_ids: list[int],
        original_translation: str,
    ) -> list[str]:
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
            translations.append(normalize_caption_text(translation))
        if actual_ids != expected_ids:
            raise CaptionAlignmentError(
                f"alignment IDs must exactly match {expected_ids}"
            )
        expected = normalize_caption_text(original_translation)
        joined_with_spaces = normalize_caption_text(" ".join(translations))
        joined_without_spaces = normalize_caption_text("".join(translations))
        if expected != joined_with_spaces and expected != joined_without_spaces:
            raise CaptionAlignmentError(
                "alignment translations must reconstruct the original translation"
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
                return self._validate_alignment(
                    payload,
                    expected_ids,
                    original_translation,
                )
            except CaptionAlignmentError as exc:
                previous_error = str(exc)
                if attempt == self.limits.correction_retries:
                    raise
            except Exception as exc:
                raise CaptionProviderError("caption alignment provider failed") from exc
        raise CaptionAlignmentError("caption alignment validation failed")

    @staticmethod
    def _merge_parts(
        left: _WorkPart,
        right: _WorkPart,
        *,
        source_language: str,
    ) -> _WorkPart:
        language = source_language.casefold().split("-", 1)[0]
        source_parts = [normalize_caption_text(left.source), normalize_caption_text(right.source)]
        source = "".join(source_parts) if language in {"zh", "ja"} else " ".join(source_parts)
        return _WorkPart(
            parent_id=left.parent_id,
            source=source,
            translation=" ".join(
                part for part in (normalize_caption_text(left.translation), normalize_caption_text(right.translation))
                if part
            ),
            start=left.start,
            end=right.end,
            words=left.words + right.words,
        )

    def _merge_short_parts(
        self,
        parts: list[_WorkPart],
        *,
        source_language: str,
    ) -> list[_WorkPart]:
        """Merge split pieces that would flash faster than the display minimum."""
        merged: list[_WorkPart] = []
        pending: _WorkPart | None = None

        for part in parts:
            if pending is None:
                pending = part
                continue

            if pending.parent_id == part.parent_id and pending.end - pending.start < self.limits.min_caption_duration:
                candidate = self._merge_parts(
                    pending,
                    part,
                    source_language=source_language,
                )
                if not requires_split(
                    candidate.source,
                    candidate.translation,
                    max_chars=self.limits.max_caption_chars,
                    target_multiplier=self.limits.target_length_multiplier,
                    max_lines=2,
                ):
                    pending = candidate
                    continue

            merged.append(pending)
            pending = part

        if pending is not None:
            if (
                merged
                and merged[-1].parent_id == pending.parent_id
                and pending.end - pending.start < self.limits.min_caption_duration
            ):
                candidate = self._merge_parts(
                    merged[-1],
                    pending,
                    source_language=source_language,
                )
                if not requires_split(
                    candidate.source,
                    candidate.translation,
                    max_chars=self.limits.max_caption_chars,
                    target_multiplier=self.limits.target_length_multiplier,
                    max_lines=2,
                ):
                    merged[-1] = candidate
                else:
                    merged.append(pending)
            else:
                merged.append(pending)

        return merged

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

        for _ in range(max(self.limits.split_passes, self.limits.max_split_passes)):
            changed = False
            next_parts: list[_WorkPart] = []
            for part in parts:
                if not requires_split(
                    part.source,
                    part.translation,
                    max_chars=self.limits.max_caption_chars,
                    target_multiplier=self.limits.target_length_multiplier,
                    max_lines=2,
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
                        min_duration=self.limits.min_caption_duration,
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
                max_lines=2,
            )
            for part in parts
        ):
            raise CaptionPolicyError("caption exceeds the configured display length")

        parts = self._merge_short_parts(parts, source_language=request.source_language)

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
                    source=wrap_caption_text(
                        part.source,
                        max_chars=self.limits.max_caption_chars,
                        max_lines=2,
                    ),
                    translation=wrap_caption_text(
                        part.translation,
                        max_chars=self.limits.max_caption_chars,
                        max_lines=2,
                    ),
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

    async def process(
        self,
        request: CaptionPostProcessRequest,
    ) -> CaptionPostProcessResponse:
        processed = await self.process_pairs(request)
        return CaptionPostProcessResponse(
            source_language=request.source_language,
            target_language=request.target_language,
            display_segments=processed.display_segments,
            audio_segments=processed.audio_segments,
            subtitles=build_subtitle_documents(processed.display_segments),
        )
