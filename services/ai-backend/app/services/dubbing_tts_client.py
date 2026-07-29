"""HTTP adapter for the existing local TTS microservice."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

import httpx

from app.models.dubbing import DubbingVoice


class DubbingTTSUnavailable(RuntimeError):
    """The local TTS service or its model is not ready."""


class DubbingTTSGenerationError(RuntimeError):
    """The local TTS service did not produce usable audio."""


class DubbingTTSClient:
    def __init__(
        self,
        *,
        base_url: str,
        retries: int,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.retries = retries
        self.client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=300)
        )

    async def check_ready(self) -> None:
        try:
            async with self.client_factory() as client:
                response = await client.get(f"{self.base_url}/health")
                response.raise_for_status()
                model = response.json().get("model", {})
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            raise DubbingTTSUnavailable("TTS service is unavailable.") from exc
        if not model.get("installed") or not model.get("loaded"):
            raise DubbingTTSUnavailable(
                "TTS model is not ready. Start local services and load the model."
            )

    async def generate_to_file(
        self,
        *,
        text: str,
        language: str,
        voice: DubbingVoice,
        pace: float,
        destination: Path,
    ) -> None:
        payload: dict[str, object] = {
            "text": text,
            "language": language,
            "speed": pace,
        }
        if voice.mode == "clone":
            payload["speaker_wav"] = voice.speaker_wav
        elif voice.mode == "design":
            payload["speaker"] = voice.speaker

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                async with self.client_factory() as client:
                    response = await client.post(
                        f"{self.base_url}/generate",
                        json=payload,
                    )
                if response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        "transient TTS failure",
                        request=response.request,
                        response=response,
                    )
                if response.status_code >= 400:
                    raise DubbingTTSGenerationError(
                        "TTS service rejected the generation request."
                    )
                if "audio" not in response.headers.get("content-type", ""):
                    raise DubbingTTSGenerationError(
                        "TTS service returned a non-audio response."
                    )
                if not response.content:
                    raise DubbingTTSGenerationError(
                        "TTS service returned empty audio."
                    )
                destination.parent.mkdir(parents=True, exist_ok=True)
                partial = destination.with_suffix(".partial")
                partial.write_bytes(response.content)
                partial.replace(destination)
                return
            except DubbingTTSGenerationError:
                raise
            except (httpx.ConnectError, httpx.ReadError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt == self.retries:
                    break
                await asyncio.sleep(0.25 * (attempt + 1))
        raise DubbingTTSGenerationError(
            "TTS generation failed after retries."
        ) from last_error
