import json
import re
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
from app.services.caption_splitter import weighted_length


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
        "min_caption_duration": 0.8,
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
    async def test_supplied_chinese_vietnamese_payload_preserves_exact_parent_text(self):
        translations = {
            "Mọi người ơi, làm nhân sự ở thiên đình là trải nghiệm như thế nào?": [
                "Mọi người ơi, làm nhân sự ở thiên",
                "đình là trải nghiệm như thế nào?",
            ],
            "Hôm nay tôi đến rồi, người đông thật đấy, tôi phải mau đi nhận việc thôi, nếu muộn": [
                "Hôm nay tôi đến rồi, người đông thật đấy,",
                "tôi phải mau đi nhận việc thôi, nếu muộn",
            ],
            "thì sắp không có cơm ăn mất rồi. Tôi được phân vào Khoa Khảo Công.": [
                "thì sắp không có cơm ăn mất rồi.",
                "Tôi được phân vào Khoa Khảo Công.",
            ],
        }

        class ExactSliceBackend:
            async def generate_json(self, *, prompt, **_kwargs):
                original = re.search(r"^Original translation: (.*)$", prompt, re.MULTILINE).group(1)
                source_parts = json.loads(
                    prompt.split("Source parts: ", 1)[1].split("\n", 1)[0]
                )
                chunks = translations[original]
                if len(chunks) != len(source_parts):
                    raise AssertionError("test backend received an unexpected split")
                return {
                    "alignments": [
                        {"id": item["id"], "translation": chunks[index]}
                        for index, item in enumerate(source_parts)
                    ]
                }

        request = CaptionPostProcessRequest(
            source_language="zh",
            target_language="vi",
            segments=[
                {
                    "id": 0,
                    "source": "家人们,在天庭做人士是一种什么体验?",
                    "translation": next(iter(translations)),
                    "start": 0.38,
                    "end": 3.72,
                    "words": [],
                },
                {
                    "id": 1,
                    "source": "今天我来了,这人真多,我得赶紧去入职了,晚",
                    "translation": list(translations)[1],
                    "start": 3.8,
                    "end": 9.74,
                    "words": [],
                },
                {
                    "id": 2,
                    "source": "了吃不上饭了,我被分到了考工科。",
                    "translation": list(translations)[2],
                    "start": 10.9,
                    "end": 13.85,
                    "words": [],
                },
            ],
        )
        result = await CaptionPostProcessor(
            backend=ExactSliceBackend(),
            limits=limits(max_caption_chars=32),
        ).process(request)

        self.assertEqual(
            [segment.translation for segment in result.audio_segments],
            list(translations),
        )
        for parent_id, original_source in enumerate(segment.source for segment in request.segments):
            display = [part for part in result.display_segments if part.parent_id == parent_id]
            self.assertEqual("".join(part.source.replace("\n", "") for part in display), original_source)
            self.assertTrue(all(len(part.translation.splitlines()) <= 2 for part in display))
            self.assertTrue(
                all(
                    weighted_length(line) <= 32
                    for part in display
                    for line in part.translation.splitlines()
                )
            )
        self.assertNotIn("nào?\nnào", result.subtitles.translation.srt)

    async def test_unsplittable_source_fails_without_duplicating_source(self):
        backend = AsyncMock()
        processor = CaptionPostProcessor(
            backend=backend,
            limits=limits(split_passes=1, max_split_passes=1),
        )

        with self.assertRaises(CaptionPolicyError):
            await processor.process_pairs(
                postprocess_request(
                    source="I",
                    translation="First sentence. Second one. Third sentence.",
                    end=6,
                )
            )
        backend.generate_json.assert_not_awaited()

    async def test_rejects_alignment_that_repeats_target_words(self):
        with self.assertRaises(CaptionAlignmentError):
            CaptionPostProcessor._validate_alignment(
                {
                    "alignments": [
                        {"id": 0, "translation": "Mọi người ơi,"},
                        {"id": 1, "translation": "Mọi người ơi, làm việc."},
                    ]
                },
                [0, 1],
                "Mọi người ơi, làm việc.",
            )

    async def test_terminal_translation_overflow_requires_exact_alignment(self):
        backend = AsyncMock()
        backend.generate_json.return_value = {
            "alignments": [
                {"id": 0, "translation": "Original translation is"},
                {"id": 1, "translation": " intentionally long."},
            ]
        }
        processor = CaptionPostProcessor(
            backend=backend,
            limits=limits(split_passes=1, max_split_passes=1),
        )

        result = await processor.process_pairs(
            postprocess_request(
                source="One two three four",
                translation="Original translation is intentionally long.",
                end=4,
            )
        )

        self.assertEqual(
            " ".join(part.translation.replace("\n", " ") for part in result.display_segments),
            "Original translation is intentionally long.",
        )
        self.assertEqual(len(result.audio_segments), 1)

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

        with self.assertRaises(CaptionAlignmentError):
            await processor.process_pairs(
                postprocess_request(
                    source=" ".join(["word"] * 24),
                    translation="y" * 350,
                    end=12,
                )
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

    async def test_two_line_policy_preserves_parent_granularity(self):
        backend = AsyncMock()
        processor = CaptionPostProcessor(backend=backend, limits=limits())

        result = await processor.process_pairs(
            postprocess_request(
                source="Bonjour source, encore",
                translation="Bonjour le monde, encore.",
                end=4,
            )
        )

        self.assertEqual(len(result.display_segments), 1)
        self.assertEqual(result.display_segments[0].translation, "Bonjour le monde,\nencore.")
        self.assertEqual(len(result.audio_segments), 1)
        self.assertEqual(result.audio_segments[0].translation, "Bonjour le monde, encore.")
        backend.generate_json.assert_not_awaited()

    async def test_retries_invalid_alignment_then_succeeds(self):
        backend = AsyncMock()
        backend.generate_json.side_effect = [
            {"alignments": [{"id": 99, "translation": "Wrong."}]},
            {
                "alignments": [
                    {"id": 0, "translation": "Bonjour le monde, encore une fois,"},
                    {"id": 1, "translation": " merci beaucoup."},
                ]
            },
        ]
        processor = CaptionPostProcessor(backend=backend, limits=limits())

        result = await processor.process_pairs(
            postprocess_request(
                source="Bonjour source, encore une fois, merci beaucoup",
                translation="Bonjour le monde, encore une fois, merci beaucoup.",
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
                    source="one two three four five six seven eight nine ten",
                    translation="This translation is intentionally long enough to split.",
                    end=4,
                )
            )

        self.assertEqual(backend.generate_json.await_count, 3)

    async def test_raises_policy_error_after_split_pass_limit(self):
        backend = AsyncMock()
        backend.generate_json.return_value = {"alignments": []}
        processor = CaptionPostProcessor(
            backend=backend,
            limits=limits(split_passes=1, max_split_passes=1, max_caption_chars=8),
        )

        with self.assertRaises(CaptionAlignmentError):
            await processor.process_pairs(
                postprocess_request(
                    source="One two three four",
                    translation="This translation is too long",
                    end=4,
                )
            )


if __name__ == "__main__":
    unittest.main()
