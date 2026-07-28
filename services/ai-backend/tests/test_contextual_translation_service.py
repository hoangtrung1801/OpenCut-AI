import unittest
from unittest.mock import AsyncMock

from app.models.translation import (
    ContextualTranslationLimits,
    ContextualTranslationRequest,
)
from app.services.contextual_translation import ContextualTranslationService


def limits(**overrides):
    values = {
        "summary_chars": 100,
        "max_source_chars": 1_000,
        "max_segments": 100,
        "batch_chars": 50,
        "batch_segments": 2,
        "max_concurrency": 2,
        "correction_retries": 2,
    }
    values.update(overrides)
    return ContextualTranslationLimits(**values)


def request():
    return ContextualTranslationRequest(
        source_language="vi",
        target_language="en",
        segments=[
            {"id": 0, "text": "OpenCut là trình biên tập.", "start": 0, "end": 2},
            {"id": 1, "text": "Nó bảo vệ riêng tư.", "start": 2, "end": 4},
        ],
        custom_terms=[
            {"source": "OpenCut", "target": "OpenCut", "note": "Keep product name."}
        ],
    )


class ContextExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_extracts_theme_and_custom_terms_override_inferred_terms(self):
        backend = AsyncMock()
        backend.generate_json.return_value = {
            "theme": "A private video editor.",
            "terms": [
                {"source": "OpenCut", "target": "Cắt Mở", "note": "Inferred."},
                {"source": "riêng tư", "target": "privacy", "note": "Concept."},
            ],
        }
        service = ContextualTranslationService(backend=backend, limits=limits())

        context = await service.extract_context(request())

        self.assertEqual(context.theme, "A private video editor.")
        self.assertEqual(
            [(term.source, term.target) for term in context.terms],
            [("OpenCut", "OpenCut"), ("riêng tư", "privacy")],
        )
        self.assertIn("vi", backend.generate_json.await_args.kwargs["prompt"])
        self.assertIn("en", backend.generate_json.await_args.kwargs["prompt"])

    async def test_retries_invalid_context_with_validation_error(self):
        backend = AsyncMock()
        backend.generate_json.side_effect = [
            {"theme": "", "terms": []},
            {"theme": "Valid theme.", "terms": []},
        ]
        service = ContextualTranslationService(backend=backend, limits=limits())

        context = await service.extract_context(request())

        self.assertEqual(context.theme, "Valid theme.")
        self.assertEqual(backend.generate_json.await_count, 2)
        self.assertIn(
            "Previous validation error",
            backend.generate_json.await_args.kwargs["prompt"],
        )


if __name__ == "__main__":
    unittest.main()
