import asyncio
import unittest
from unittest.mock import AsyncMock

from app.models.translation import (
    ContextualTranslationLimits,
    ContextualTranslationRequest,
)
from app.services.contextual_translation import (
    ContextualTranslationService,
    TranslationValidationError,
)


def limits(**overrides):
    values = {
        "summary_chars": 100,
        "max_source_chars": 1_000,
        "max_segments": 100,
        "batch_chars": 50,
        "batch_segments": 2,
        "max_concurrency": 2,
        "correction_retries": 2,
        "max_caption_chars": 32,
        "target_length_multiplier": 1.0,
        "split_passes": 3,
        "gap_close_seconds": 1.0,
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


class ContextualTranslationTests(unittest.IsolatedAsyncioTestCase):
    async def test_translates_batches_with_neighbors_and_matching_terms(self):
        backend = AsyncMock()
        backend.generate_json.side_effect = [
            {
                "theme": "OpenCut tutorial.",
                "terms": [
                    {"source": "OpenCut", "target": "OpenCut", "note": "Product."},
                    {"source": "khác", "target": "other", "note": "Must not leak."},
                ],
            },
            {"translations": [{"id": 0, "translation": "OpenCut is private."}]},
            {"translations": [{"id": 1, "translation": "It runs locally."}]},
        ]
        service = ContextualTranslationService(
            backend=backend,
            limits=limits(batch_chars=1_000, batch_segments=1, max_concurrency=1),
        )

        result = await service.translate(request())

        self.assertEqual([segment.id for segment in result.segments], [0, 1])
        self.assertEqual(result.segments[0].start, 0)
        self.assertEqual(result.segments[1].end, 4)
        self.assertEqual(result.audio_segments[0].translation, "OpenCut is private.")
        self.assertEqual(result.display_segments[0].parent_id, 0)
        self.assertIn("WEBVTT", result.subtitles.translation.vtt)
        first_batch_prompt = backend.generate_json.await_args_list[1].kwargs["prompt"]
        self.assertIn("OpenCut", first_batch_prompt)
        self.assertNotIn('"source": "khác"', first_batch_prompt)
        self.assertIn("Following source context", first_batch_prompt)

    async def test_retries_when_response_ids_do_not_exactly_match(self):
        backend = AsyncMock()
        backend.generate_json.side_effect = [
            {"theme": "Theme.", "terms": []},
            {"translations": [{"id": 99, "translation": "Wrong."}]},
            {
                "translations": [
                    {"id": 0, "translation": "One."},
                    {"id": 1, "translation": "Two."},
                ]
            },
        ]
        service = ContextualTranslationService(
            backend=backend,
            limits=limits(batch_chars=1_000, batch_segments=10),
        )

        result = await service.translate(request())

        self.assertEqual(
            [segment.translation for segment in result.segments], ["One.", "Two."]
        )

    async def test_exhausted_validation_failure_returns_no_partial_result(self):
        backend = AsyncMock()
        backend.generate_json.side_effect = [
            {"theme": "Theme.", "terms": []},
            {"translations": []},
            {"translations": []},
            {"translations": []},
        ]
        service = ContextualTranslationService(backend=backend, limits=limits())

        with self.assertRaises(TranslationValidationError):
            await service.translate(request())

    async def test_concurrent_batches_are_reassembled_in_source_order(self):
        second_finished = asyncio.Event()
        context_returned = False

        async def generate_json(*, prompt, **_kwargs):
            nonlocal context_returned
            if not context_returned:
                context_returned = True
                return {"theme": "Theme.", "terms": []}
            if '"id": 0' in prompt:
                await second_finished.wait()
                return {"translations": [{"id": 0, "translation": "One."}]}
            second_finished.set()
            return {"translations": [{"id": 1, "translation": "Two."}]}

        backend = AsyncMock()
        backend.generate_json.side_effect = generate_json
        service = ContextualTranslationService(
            backend=backend,
            limits=limits(batch_chars=1_000, batch_segments=1, max_concurrency=2),
        )

        result = await service.translate(request())

        self.assertEqual([segment.id for segment in result.segments], [0, 1])


if __name__ == "__main__":
    unittest.main()
