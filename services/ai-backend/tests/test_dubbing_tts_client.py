import io
import json
import tempfile
import unittest
import wave
from pathlib import Path

import httpx

from app.models.dubbing import AutoVoice, CloneVoice, DesignVoice
from app.services.dubbing_tts_client import (
    DubbingTTSClient,
    DubbingTTSUnavailable,
)


def valid_wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\x00\x00" * 160)
    return output.getvalue()


def make_client(handler, retries: int = 2) -> DubbingTTSClient:
    transport = httpx.MockTransport(handler)
    return DubbingTTSClient(
        base_url="http://tts",
        retries=retries,
        client_factory=lambda: httpx.AsyncClient(
            transport=transport,
            base_url="http://tts",
        ),
    )


class DubbingTTSClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_maps_each_explicit_voice_mode_to_existing_tts_json(self):
        seen: list[dict] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(
                    200,
                    json={"model": {"installed": True, "loaded": True}},
                )
            seen.append(json.loads(request.content))
            return httpx.Response(
                200,
                content=valid_wav_bytes(),
                headers={"content-type": "audio/wav"},
            )

        client = make_client(handler)
        with tempfile.TemporaryDirectory() as directory:
            for index, voice in enumerate((
                CloneVoice(
                    mode="clone",
                    speaker_wav="generated/voices/alice.wav",
                    reference_text="Hello from Alice.",
                ),
                DesignVoice(mode="design", speaker="warm narrator"),
                AutoVoice(mode="auto"),
            )):
                await client.generate_to_file(
                    text="Hello",
                    language="en",
                    voice=voice,
                    pace=1.0,
                    destination=Path(directory) / f"{index}.wav",
                )

        self.assertEqual(seen[0]["speaker_wav"], "generated/voices/alice.wav")
        self.assertEqual(seen[0]["reference_text"], "Hello from Alice.")
        self.assertEqual(seen[1]["speaker"], "warm narrator")
        self.assertNotIn("speaker_wav", seen[2])
        self.assertNotIn("speaker", seen[2])

    async def test_retries_transient_failures_but_not_readiness_failures(self):
        attempts = 0

        async def transient_handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            if request.url.path == "/health":
                return httpx.Response(
                    200,
                    json={"model": {"installed": True, "loaded": True}},
                )
            attempts += 1
            if attempts == 1:
                return httpx.Response(503, text="temporary")
            return httpx.Response(
                200,
                content=valid_wav_bytes(),
                headers={"content-type": "audio/wav"},
            )

        with tempfile.TemporaryDirectory() as directory:
            await make_client(transient_handler, retries=1).generate_to_file(
                text="Hello",
                language="en",
                voice=AutoVoice(mode="auto"),
                pace=1.0,
                destination=Path(directory) / "retry.wav",
            )
        self.assertEqual(attempts, 2)

        async def unavailable_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"model": {"installed": True, "loaded": False}},
            )

        with self.assertRaises(DubbingTTSUnavailable):
            await make_client(unavailable_handler).check_ready()


if __name__ == "__main__":
    unittest.main()
