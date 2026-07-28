"""VideoLingo-inspired contextual transcript translation."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from pydantic import ValidationError

from app.models.translation import (
    ContextualTranslationLimits,
    ContextualTranslationResponse,
    ContextualTranslationRequest,
    TranslatedSegment,
    TranslationSegmentInput,
    TranslationTerm,
)


class ContextualTranslationError(Exception):
    """Base class for expected contextual translation failures."""


class TranslationProviderError(ContextualTranslationError):
    """The configured LLM provider could not produce a response."""


class TranslationValidationError(ContextualTranslationError):
    """The LLM response did not match the required structured contract."""


@dataclass(frozen=True)
class TranslationContext:
    theme: str
    terms: list[TranslationTerm]


def merge_terms(
    inferred: list[TranslationTerm],
    custom: list[TranslationTerm],
) -> list[TranslationTerm]:
    """Merge custom terms in inferred order, then append new custom terms."""
    custom_by_source = {term.source.casefold(): term for term in custom}
    merged: list[TranslationTerm] = []
    used_sources: set[str] = set()

    for term in inferred:
        key = term.source.casefold()
        replacement = custom_by_source.get(key, term)
        merged.append(replacement)
        used_sources.add(key)

    for term in custom:
        key = term.source.casefold()
        if key not in used_sources:
            merged.append(term)
            used_sources.add(key)

    return merged


def build_batches(
    segments: list[TranslationSegmentInput],
    max_chars: int,
    max_segments: int,
) -> list[list[TranslationSegmentInput]]:
    batches: list[list[TranslationSegmentInput]] = []
    current: list[TranslationSegmentInput] = []
    current_chars = 0

    for segment in segments:
        segment_chars = len(segment.text)
        would_exceed_chars = current and current_chars + segment_chars > max_chars
        would_exceed_count = current and len(current) >= max_segments
        if would_exceed_chars or would_exceed_count:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(segment)
        current_chars += segment_chars

    if current:
        batches.append(current)
    return batches


def matching_terms(text: str, terms: list[TranslationTerm]) -> list[TranslationTerm]:
    folded = text.casefold()
    return [term for term in terms if term.source.casefold() in folded]


T = TypeVar("T")


class ContextualTranslationService:
    def __init__(self, *, backend: Any, limits: ContextualTranslationLimits):
        self.backend = backend
        self.limits = limits

    def _validate_request_limits(self, request: ContextualTranslationRequest) -> None:
        if len(request.segments) > self.limits.max_segments:
            raise TranslationValidationError(
                f"transcript exceeds the {self.limits.max_segments} segment limit"
            )
        source_chars = sum(len(segment.text) for segment in request.segments)
        if source_chars > self.limits.max_source_chars:
            raise TranslationValidationError(
                "transcript exceeds the contextual translation size limit"
            )

    @staticmethod
    def _source_text(request: ContextualTranslationRequest) -> str:
        return "\n".join(
            f"{segment.id}. {segment.text.strip()}" for segment in request.segments
        )

    def _context_prompt(
        self,
        request: ContextualTranslationRequest,
        previous_error: str | None = None,
    ) -> str:
        source_sample = self._source_text(request)[: self.limits.summary_chars]
        custom_terms = [term.model_dump() for term in request.custom_terms]
        prompt = (
            "Analyze this transcript for contextual translation. Return ONLY a JSON "
            'object with keys "theme" and "terms". Every term must contain non-empty '
            '"source", "target", and "note" strings. Do not translate the transcript.\n'
            f"Source language: {request.source_language}\n"
            f"Target language: {request.target_language}\n"
            f"Custom terms: {json.dumps(custom_terms, ensure_ascii=False)}\n"
            f"Transcript sample:\n{source_sample}\n"
        )
        if previous_error:
            prompt += f"Previous validation error to correct: {previous_error}\n"
        return prompt

    def _batch_prompt(
        self,
        request: ContextualTranslationRequest,
        context: TranslationContext,
        batches: list[list[TranslationSegmentInput]],
        batch_index: int,
        previous_error: str | None = None,
    ) -> str:
        batch = batches[batch_index]
        batch_text = "\n".join(segment.text for segment in batch)
        terms = [
            term.model_dump()
            for term in matching_terms(batch_text, context.terms)
        ]
        previous = batches[batch_index - 1][-3:] if batch_index > 0 else []
        following = (
            batches[batch_index + 1][:2]
            if batch_index < len(batches) - 1
            else []
        )
        current = [
            {"id": segment.id, "source": segment.text}
            for segment in batch
        ]
        prompt = (
            "Translate every numbered source segment naturally and faithfully. "
            "Return ONLY a JSON object with a translations array. Each array item "
            "must contain the original integer id and one non-empty translation. "
            "Do not merge, split, omit, reorder, or rewrite the IDs.\n"
            f"Source language: {request.source_language}\n"
            f"Target language: {request.target_language}\n"
            f"Theme: {context.theme}\n"
            f"Terminology for this batch: {json.dumps(terms, ensure_ascii=False)}\n"
            f"Previous source context: {json.dumps([item.text for item in previous], ensure_ascii=False)}\n"
            f"Following source context: {json.dumps([item.text for item in following], ensure_ascii=False)}\n"
            f"Current segments: {json.dumps(current, ensure_ascii=False)}\n"
        )
        if previous_error:
            prompt += f"Previous validation error to correct: {previous_error}\n"
        return prompt

    @staticmethod
    def _validate_context_payload(payload: Any) -> TranslationContext:
        if not isinstance(payload, dict):
            raise TranslationValidationError("context response must be an object")
        theme = payload.get("theme")
        raw_terms = payload.get("terms")
        if not isinstance(theme, str) or not theme.strip():
            raise TranslationValidationError("context theme must be a non-empty string")
        if len(theme) > 2_000:
            raise TranslationValidationError("context theme is too long")
        if not isinstance(raw_terms, list):
            raise TranslationValidationError("context terms must be a list")
        terms: list[TranslationTerm] = []
        try:
            for raw_term in raw_terms:
                terms.append(TranslationTerm.model_validate(raw_term))
        except (ValidationError, TypeError) as exc:
            raise TranslationValidationError("context term has an invalid shape") from exc
        return TranslationContext(theme=theme.strip(), terms=terms)

    async def _request_validated(
        self,
        prompt_builder: Callable[[str | None], str],
        validator: Callable[[Any], T],
    ) -> T:
        previous_error: str | None = None
        for attempt in range(self.limits.correction_retries + 1):
            try:
                payload = await self.backend.generate_json(
                    prompt=prompt_builder(previous_error),
                    system="Return strict JSON only.",
                    _retries=0,
                )
                return validator(payload)
            except TranslationValidationError as exc:
                previous_error = str(exc)
                if attempt == self.limits.correction_retries:
                    raise
            except (ValidationError, ValueError, TypeError) as exc:
                previous_error = str(exc)
                if attempt == self.limits.correction_retries:
                    raise TranslationValidationError(
                        "translation provider returned invalid JSON"
                    ) from exc
            except Exception as exc:
                raise TranslationProviderError("translation provider failed") from exc
        raise TranslationValidationError("translation response validation failed")

    async def extract_context(
        self,
        request: ContextualTranslationRequest,
    ) -> TranslationContext:
        self._validate_request_limits(request)
        context = await self._request_validated(
            lambda previous_error: self._context_prompt(request, previous_error),
            self._validate_context_payload,
        )
        return TranslationContext(
            theme=context.theme,
            terms=merge_terms(context.terms, request.custom_terms),
        )

    @staticmethod
    def _translation_validator(
        expected_ids: list[int],
    ) -> Callable[[Any], list[tuple[int, str]]]:
        def validate(payload: Any) -> list[tuple[int, str]]:
            if not isinstance(payload, dict):
                raise TranslationValidationError(
                    "translation response must be an object"
                )
            raw_translations = payload.get("translations")
            if not isinstance(raw_translations, list):
                raise TranslationValidationError(
                    "translation response must contain a translations list"
                )
            values: list[tuple[int, str]] = []
            for item in raw_translations:
                if not isinstance(item, dict):
                    raise TranslationValidationError(
                        "translation items must be objects"
                    )
                identifier = item.get("id")
                translation = item.get("translation")
                if (
                    isinstance(identifier, bool)
                    or not isinstance(identifier, int)
                    or not isinstance(translation, str)
                    or not translation.strip()
                ):
                    raise TranslationValidationError(
                        "translation item has an invalid shape"
                    )
                values.append((identifier, translation.strip()))
            actual_ids = [identifier for identifier, _ in values]
            if actual_ids != expected_ids:
                raise TranslationValidationError(
                    f"translation IDs must exactly match {expected_ids}"
                )
            return values

        return validate

    async def _translate_batch(
        self,
        request: ContextualTranslationRequest,
        context: TranslationContext,
        batches: list[list[TranslationSegmentInput]],
        batch_index: int,
    ) -> list[tuple[int, str]]:
        batch = batches[batch_index]
        expected_ids = [segment.id for segment in batch]
        return await self._request_validated(
            lambda previous_error: self._batch_prompt(
                request,
                context,
                batches,
                batch_index,
                previous_error,
            ),
            self._translation_validator(expected_ids),
        )

    async def translate(
        self,
        request: ContextualTranslationRequest,
    ) -> ContextualTranslationResponse:
        self._validate_request_limits(request)
        context = await self.extract_context(request)
        batches = build_batches(
            request.segments,
            max_chars=self.limits.batch_chars,
            max_segments=self.limits.batch_segments,
        )
        semaphore = asyncio.Semaphore(self.limits.max_concurrency)

        async def guarded(index: int) -> list[tuple[int, str]]:
            async with semaphore:
                return await self._translate_batch(
                    request,
                    context,
                    batches,
                    index,
                )

        translated_batches = await asyncio.gather(
            *(guarded(index) for index in range(len(batches)))
        )
        translated_by_id = {
            identifier: translation
            for batch in translated_batches
            for identifier, translation in batch
        }
        translated_segments = [
            TranslatedSegment(
                id=segment.id,
                source=segment.text,
                translation=translated_by_id[segment.id],
                start=segment.start,
                end=segment.end,
            )
            for segment in request.segments
        ]
        return ContextualTranslationResponse(
            source_language=request.source_language,
            target_language=request.target_language,
            theme=context.theme,
            terminology=context.terms,
            segments=translated_segments,
        )
