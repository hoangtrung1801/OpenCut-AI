import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.routes.transcribe import proxy_artifact, transcribe


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class TranscriptionProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_transcribe_rewrites_both_whisper_artifact_urls(self):
        artifact_id = "7ec1c6ec-6eb9-45f4-846c-f11a345c4bc2"
        downstream = {
            "separated_audio": {
                "vocals_url": f"/artifacts/{artifact_id}/vocals",
                "background_url": f"/artifacts/{artifact_id}/background",
            }
        }
        with patch("app.routes.transcribe._proxy_file_upload", new=AsyncMock(return_value=FakeResponse(downstream))):
            result = await transcribe(SimpleNamespace(filename="sample.wav"))
        self.assertEqual(
            result["separated_audio"]["vocals_url"],
            f"/api/transcribe/artifacts/{artifact_id}/vocals",
        )
        self.assertEqual(
            result["separated_audio"]["background_url"],
            f"/api/transcribe/artifacts/{artifact_id}/background",
        )

    async def test_artifact_proxy_rejects_unknown_stem_before_downstream_call(self):
        with self.assertRaises(HTTPException) as raised:
            await proxy_artifact("7ec1c6ec-6eb9-45f4-846c-f11a345c4bc2", "secret")
        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
