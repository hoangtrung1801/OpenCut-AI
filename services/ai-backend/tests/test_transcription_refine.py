import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.routes.transcription_refine import RefineRequest, refine_transcription


class TranscriptionRefineTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_only_valid_boundary_indexes(self):
        request = RefineRequest(
            language="en",
            words=[{"index": 0, "word": "Hello"}, {"index": 1, "word": "world"}],
            candidates=[0],
        )
        with patch("app.routes.transcription_refine.llm_backend.generate_json", new_callable=AsyncMock) as generate:
            generate.return_value = {"split_after": [0]}
            result = await refine_transcription(request)

        self.assertEqual(result, {"split_after": [0]})
        prompt = generate.await_args.kwargs["prompt"]
        self.assertIn("Hello", prompt)
        self.assertIn("split_after", prompt)

    async def test_backend_failure_is_sanitized(self):
        request = RefineRequest(
            language="vi",
            words=[{"index": 0, "word": "Xin"}, {"index": 1, "word": "chào"}],
            candidates=[],
        )
        with patch("app.routes.transcription_refine.llm_backend.generate_json", new_callable=AsyncMock) as generate:
            generate.side_effect = RuntimeError("backend unavailable")
            with self.assertRaises(HTTPException) as raised:
                await refine_transcription(request)

        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(raised.exception.detail, "Semantic refinement unavailable.")

    async def test_malformed_model_output_is_rejected(self):
        request = RefineRequest(
            language="en",
            words=[{"index": 0, "word": "one"}, {"index": 1, "word": "two"}],
            candidates=[],
        )
        with patch("app.routes.transcription_refine.llm_backend.generate_json", new_callable=AsyncMock) as generate:
            generate.return_value = {"split_after": [True]}
            with self.assertRaises(HTTPException) as raised:
                await refine_transcription(request)

        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
