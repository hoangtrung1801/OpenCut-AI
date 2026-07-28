import unittest
from unittest.mock import AsyncMock

from app.models.translation import (
    CaptionPostProcessRequest,
    ContextualTranslationLimits,
)
from app.services.caption_postprocessor import (
    CaptionAlignmentError,
    CaptionPolicyError,
    CaptionPostProcessor,
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
        "max_caption_chars": 20,
        "target_length_multiplier": 1.0,
        "split_passes": 3,
        "max_split_passes": 8,
        "gap_close_seconds": 1.0,
    }
    values.update(overrides)
    return ContextualTranslationLimits(**values)


def postprocess_request(
    *,
    source: str = "Xin chào.",
    translation: str = "Hello.",
    start: float = 0,
    end: float = 1,
) -> CaptionPostProcessRequest:
    return CaptionPostProcessRequest(
        source_language="vi",
        target_language="en",
        segments=[
            {
                "id": 4,
                "source": source,
                "translation": translation,
                "start": start,
                "end": end,
                "words": [],
            }
        ],
    )


class CaptionPostProcessorTests(unittest.IsolatedAsyncioTestCase):
    async def test_adaptive_passes_handle_high_translation_expansion(self):
        class ExpandingBackend:
            async def generate_json(self, *, prompt, **_kwargs):
                import json

                payload = json.loads(prompt.split("Source parts: ", 1)[1].split("\n", 1)[0])
                return {
                    "alignments": [
                        {"id": item["id"], "translation": "x" * max(1, len(item["source"]) * 3)}
                        for item in payload
                    ]
                }

        processor = CaptionPostProcessor(
            backend=ExpandingBackend(),
            limits=limits(),
        )

        result = await processor.process_pairs(
            postprocess_request(
                source=" ".join(["word"] * 24),
                translation="y" * 350,
                end=12,
            )
        )

        self.assertGreater(len(result.display_segments), 8)
        self.assertLessEqual(
            max(len(part.translation) for part in result.display_segments),
            32,
        )

    async def test_short_pair_keeps_original_display_and_audio_granularity(self):
        backend = AsyncMock()
        processor = CaptionPostProcessor(backend=backend, limits=limits())

        result = await processor.process_pairs(postprocess_request())

        self.assertEqual(len(result.display_segments), 1)
        self.assertEqual(result.display_segments[0].translation, "Hello.")
        self.assertEqual(result.audio_segments[0].translation, "Hello.")
        backend.generate_json.assert_not_awaited()

    async def test_process_adds_all_subtitle_variants(self):
        processor = CaptionPostProcessor(backend=AsyncMock(), limits=limits())

        result = await processor.process(postprocess_request())

        self.assertIn("Hello.", result.subtitles.translation.srt)
        self.assertIn("WEBVTT", result.subtitles.source.vtt)

    async def test_aligns_split_translation_and_preserves_audio_pair(self):
        backend = AsyncMock()
        backend.generate_json.return_value = {
            "alignments": [
                {"id": 0, "translation": "Bonjour le monde,"},
                {"id": 1, "translation": "encore."},
            ]
        }
        processor = CaptionPostProcessor(backend=backend, limits=limits())

        result = await processor.process_pairs(
            postprocess_request(
                source="Bonjour source, encore",
                translation="Bonjour le monde, encore.",
                end=4,
            )
        )

        self.assertEqual(
            [part.translation for part in result.display_segments],
            ["Bonjour le monde,", "encore."],
        )
        self.assertEqual(len(result.audio_segments), 1)
        self.assertEqual(result.audio_segments[0].translation, "Bonjour le monde, encore.")
        self.assertEqual(backend.generate_json.await_count, 1)

    async def test_retries_invalid_alignment_then_succeeds(self):
        backend = AsyncMock()
        backend.generate_json.side_effect = [
            {"alignments": [{"id": 99, "translation": "Wrong."}]},
            {
                "alignments": [
                    {"id": 0, "translation": "Bonjour le monde,"},
                    {"id": 1, "translation": "encore."},
                ]
            },
        ]
        processor = CaptionPostProcessor(backend=backend, limits=limits())

        result = await processor.process_pairs(
            postprocess_request(
                source="Bonjour source, encore",
                translation="Bonjour le monde, encore.",
                end=4,
            )
        )

        self.assertEqual(len(result.display_segments), 2)
        self.assertEqual(backend.generate_json.await_count, 2)
        self.assertIn(
            "Previous validation error",
            backend.generate_json.await_args_list[1].kwargs["prompt"],
        )

    async def test_exhausted_alignment_validation_raises_without_partial_result(self):
        backend = AsyncMock()
        backend.generate_json.return_value = {"alignments": []}
        processor = CaptionPostProcessor(backend=backend, limits=limits())

        with self.assertRaises(CaptionAlignmentError):
            await processor.process_pairs(
                postprocess_request(
                    source="Bonjour source, encore",
                    translation="Bonjour le monde, encore.",
                    end=4,
                )
            )

        self.assertEqual(backend.generate_json.await_count, 3)

    async def test_raises_policy_error_after_split_pass_limit(self):
        backend = AsyncMock()
        backend.generate_json.return_value = {
            "alignments": [
                {"id": 0, "translation": "This remains very long"},
                {"id": 1, "translation": "This remains very long"},
            ]
        }
        processor = CaptionPostProcessor(
            backend=backend,
            limits=limits(split_passes=1, max_split_passes=1, max_caption_chars=8),
        )

        with self.assertRaises(CaptionPolicyError):
            await processor.process_pairs(
                postprocess_request(
                    source="One two three four",
                    translation="This translation is too long",
                    end=4,
                )
            )


if __name__ == "__main__":
    unittest.main()
