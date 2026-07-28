"""VideoLingo-inspired contextual transcript translation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar

from pydantic import ValidationError

from app.models.translation import (
    ContextualTranslationLimits,
    ContextualTranslationRequest,
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
