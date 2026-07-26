"""OpenAI-backed text generation for the TurboQuant service."""

from __future__ import annotations

import os
import time
from typing import Any


class OpenAIProviderError(RuntimeError):
    """Raised when an OpenAI request cannot be completed."""


class OpenAIProviderConfigurationError(OpenAIProviderError):
    """Raised when the OpenAI provider is not configured correctly."""


def _get_field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _usage_value(usage: Any, name: str) -> int:
    value = _get_field(usage, name, 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class OpenAIProvider:
    """Thin adapter that normalizes OpenAI Chat Completions responses."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        default_model: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
        self.default_model = (
            default_model
            or os.getenv("OPENAI_MODEL")
            or "gpt-4o-mini"
        )
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise OpenAIProviderConfigurationError(
                "OPENAI_API_KEY is required when AI_PROVIDER=openai"
            )

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise OpenAIProviderConfigurationError(
                "The openai package is not installed"
            ) from exc

        try:
            self._client = OpenAI(api_key=self.api_key)
        except Exception as exc:
            raise OpenAIProviderConfigurationError(
                "Unable to initialize the OpenAI client"
            ) from exc
        return self._client

    def _generate(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None,
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> dict[str, Any]:
        selected_model = model or self.default_model
        start = time.monotonic()
        request: dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
            # `max_tokens` is deprecated and rejected by newer reasoning
            # models such as GPT-5.4/5.5/5.6. This field is supported by
            # both the newer models and current legacy chat models.
            "max_completion_tokens": max_tokens,
            "stream": False,
        }
        # GPT-5 reasoning models only accept their default sampling behavior;
        # sending temperature/top_p values produces a 400 even when the
        # values are otherwise valid for older chat models.
        if not selected_model.lower().startswith("gpt-5"):
            request.update(temperature=temperature, top_p=top_p)

        try:
            response = self._get_client().chat.completions.create(**request)
        except OpenAIProviderError:
            raise
        except Exception as exc:
            # Do not return the SDK exception directly: it may contain request
            # details that are not safe to expose through this service. The
            # SDK's normal error text contains the useful API validation detail
            # without exposing the API key.
            detail = str(exc).strip() or exc.__class__.__name__
            raise OpenAIProviderError(f"OpenAI request failed: {detail}") from exc

        choices = _get_field(response, "choices", []) or []
        if not choices:
            raise OpenAIProviderError("OpenAI returned no completion choices")

        message = _get_field(choices[0], "message", {}) or {}
        content = _get_field(message, "content", "")
        if isinstance(content, list):
            content = "".join(
                str(_get_field(part, "text", ""))
                for part in content
                if _get_field(part, "text", None) is not None
            )
        response_text = str(content or "")

        usage = _get_field(response, "usage")
        prompt_tokens = _usage_value(usage, "prompt_tokens")
        completion_tokens = _usage_value(usage, "completion_tokens")
        total_tokens = _usage_value(usage, "total_tokens")
        if total_tokens == 0:
            total_tokens = prompt_tokens + completion_tokens

        return {
            "response_text": response_text,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "compression_ratio": None,
            "engine_used": False,
            "inference_time_s": time.monotonic() - start,
            "model": _get_field(response, "model", selected_model),
        }

    def generate_chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None,
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> dict[str, Any]:
        return self._generate(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
        )

    def generate_completion(
        self,
        *,
        prompt: str,
        model: str | None,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        return self._generate(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=1.0,
        )
