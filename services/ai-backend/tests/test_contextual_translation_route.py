import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.models.translation import ContextualTranslationRequest
from app.routes.translation import contextual_translation
from app.services.contextual_translation import TranslationProviderError


def request():
    return ContextualTranslationRequest(
        source_language="vi",
        target_language="en",
        segments=[{"id": 0, "text": "Xin chào.", "start": 0, "end": 1}],
    )


class ContextualTranslationRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_service_response_when_llm_is_available(self):
        with (
            patch(
                "app.routes.translation.llm_backend.check_available",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.routes.translation.translation_service.translate",
                new=AsyncMock(),
            ) as translate,
        ):
            translate.return_value = {
                "source_language": "vi",
                "target_language": "en",
                "theme": "Greeting.",
                "terminology": [],
                "segments": [
                    {
                        "id": 0,
                        "source": "Xin chào.",
                        "translation": "Hello.",
                        "start": 0,
                        "end": 1,
                    }
                ],
            }
            result = await contextual_translation(request())

        self.assertEqual(result["segments"][0]["translation"], "Hello.")

    async def test_returns_503_when_no_llm_is_available(self):
        with patch(
            "app.routes.translation.llm_backend.check_available",
            new=AsyncMock(return_value=False),
        ):
            with self.assertRaises(HTTPException) as raised:
                await contextual_translation(request())

        self.assertEqual(raised.exception.status_code, 503)

    async def test_sanitizes_provider_failure_as_502(self):
        with (
            patch(
                "app.routes.translation.llm_backend.check_available",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.routes.translation.translation_service.translate",
                new=AsyncMock(side_effect=TranslationProviderError("private detail")),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await contextual_translation(request())

        self.assertEqual(raised.exception.status_code, 502)
        self.assertNotIn("private detail", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
