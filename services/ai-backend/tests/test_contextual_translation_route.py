import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.models.translation import ContextualTranslationRequest
from app.models.translation import CaptionPostProcessRequest
from app.routes.translation import contextual_translation, post_process_captions
from app.services.caption_postprocessor import CaptionAlignmentError, CaptionPolicyError
from app.services.contextual_translation import TranslationProviderError


def request():
    return ContextualTranslationRequest(
        source_language="vi",
        target_language="en",
        segments=[{"id": 0, "text": "Xin chào.", "start": 0, "end": 1}],
    )


def postprocess_request():
    return CaptionPostProcessRequest(
        source_language="vi",
        target_language="en",
        segments=[
            {
                "id": 0,
                "source": "Xin chào.",
                "translation": "Hello.",
                "start": 0,
                "end": 1,
            }
        ],
    )


class ContextualTranslationRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_process_route_returns_shared_processor_response(self):
        with patch(
            "app.routes.translation.caption_processor.process",
            new=AsyncMock(return_value={"display_segments": [], "audio_segments": []}),
        ) as process:
            result = await post_process_captions(postprocess_request())

        self.assertEqual(result["display_segments"], [])
        process.assert_awaited_once()

    async def test_post_process_route_maps_alignment_exhaustion_to_502(self):
        with patch(
            "app.routes.translation.caption_processor.process",
            new=AsyncMock(side_effect=CaptionAlignmentError("private detail")),
        ):
            with self.assertRaises(HTTPException) as raised:
                await post_process_captions(postprocess_request())

        self.assertEqual(raised.exception.status_code, 502)
        self.assertNotIn("private detail", raised.exception.detail)

    async def test_post_process_route_maps_policy_failure_to_422(self):
        with patch(
            "app.routes.translation.caption_processor.process",
            new=AsyncMock(side_effect=CaptionPolicyError("caption exceeds the configured display length")),
        ):
            with self.assertRaises(HTTPException) as raised:
                await post_process_captions(postprocess_request())

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(
            raised.exception.detail,
            "Caption policy validation failed: the translated caption is still too long after splitting.",
        )

    async def test_post_process_route_keeps_unknown_policy_details_private(self):
        with patch(
            "app.routes.translation.caption_processor.process",
            new=AsyncMock(side_effect=CaptionPolicyError("private detail")),
        ):
            with self.assertRaises(HTTPException) as raised:
                await post_process_captions(postprocess_request())

        self.assertEqual(raised.exception.status_code, 422)
        self.assertNotIn("private detail", raised.exception.detail)

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
