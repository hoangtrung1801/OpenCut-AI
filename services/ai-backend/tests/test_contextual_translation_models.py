import unittest

from pydantic import ValidationError

from app.models.translation import ContextualTranslationRequest
from app.models.translation import CaptionPostProcessRequest, ContextualTranslationLimits


class ContextualTranslationModelTests(unittest.TestCase):
    def test_accepts_optional_words_inside_parent_segment(self):
        request = ContextualTranslationRequest(
            source_language="vi",
            target_language="en",
            segments=[
                {
                    "id": 7,
                    "text": "Xin chào.",
                    "start": 1.0,
                    "end": 2.0,
                    "words": [{"word": "Xin", "start": 1.0, "end": 1.4}],
                }
            ],
        )
        self.assertEqual(request.segments[0].words[0].word, "Xin")

    def test_rejects_word_outside_parent_segment(self):
        with self.assertRaises(ValidationError):
            ContextualTranslationRequest(
                source_language="vi",
                target_language="en",
                segments=[
                    {
                        "id": 0,
                        "text": "Xin chào.",
                        "start": 1.0,
                        "end": 2.0,
                        "words": [{"word": "Xin", "start": 0.5, "end": 1.4}],
                    }
                ],
            )

    def test_caption_post_process_request_preserves_original_pair(self):
        request = CaptionPostProcessRequest(
            source_language="vi",
            target_language="en",
            segments=[
                {
                    "id": 4,
                    "source": "Xin chào.",
                    "translation": "Hello.",
                    "start": 0,
                    "end": 1,
                    "words": [],
                }
            ],
        )
        self.assertEqual(request.segments[0].translation, "Hello.")

    def test_caption_limits_read_the_configured_defaults(self):
        class FakeSettings:
            CONTEXT_TRANSLATION_SUMMARY_CHARS = 100
            CONTEXT_TRANSLATION_MAX_SOURCE_CHARS = 1_000
            CONTEXT_TRANSLATION_MAX_SEGMENTS = 100
            CONTEXT_TRANSLATION_BATCH_CHARS = 50
            CONTEXT_TRANSLATION_BATCH_SEGMENTS = 2
            CONTEXT_TRANSLATION_MAX_CONCURRENCY = 2
            CONTEXT_TRANSLATION_CORRECTION_RETRIES = 2
            CONTEXT_TRANSLATION_MAX_CAPTION_CHARS = 32
            CONTEXT_TRANSLATION_TARGET_LENGTH_MULTIPLIER = 1.0
            CONTEXT_TRANSLATION_SPLIT_PASSES = 3
            CONTEXT_TRANSLATION_MAX_SPLIT_PASSES = 8
            CONTEXT_TRANSLATION_GAP_CLOSE_SECONDS = 1.0

        limits = ContextualTranslationLimits.from_settings(FakeSettings)

        self.assertEqual(limits.max_caption_chars, 32)
        self.assertEqual(limits.target_length_multiplier, 1.0)
        self.assertEqual(limits.split_passes, 3)
        self.assertEqual(limits.max_split_passes, 8)
        self.assertEqual(limits.gap_close_seconds, 1.0)

    def test_accepts_ordered_timestamped_segments(self):
        request = ContextualTranslationRequest(
            source_language="vi",
            target_language="en",
            segments=[
                {"id": 7, "text": "Xin chào.", "start": 1.25, "end": 2.5},
                {"id": 9, "text": "Hẹn gặp lại.", "start": 2.5, "end": 4.0},
            ],
        )
        self.assertEqual([segment.id for segment in request.segments], [7, 9])

    def test_rejects_same_source_and_target_language(self):
        with self.assertRaises(ValidationError):
            ContextualTranslationRequest(
                source_language="vi",
                target_language="VI",
                segments=[{"id": 0, "text": "Xin chào.", "start": 0, "end": 1}],
            )

    def test_rejects_duplicate_ids(self):
        with self.assertRaises(ValidationError):
            ContextualTranslationRequest(
                source_language="vi",
                target_language="en",
                segments=[
                    {"id": 1, "text": "Một.", "start": 0, "end": 1},
                    {"id": 1, "text": "Hai.", "start": 1, "end": 2},
                ],
            )

    def test_rejects_reversed_or_non_finite_timestamps(self):
        invalid_segments = [
            {"id": 0, "text": "Bad.", "start": 2, "end": 1},
            {"id": 0, "text": "Bad.", "start": float("inf"), "end": 2},
        ]
        for segment in invalid_segments:
            with self.subTest(segment=segment):
                with self.assertRaises(ValidationError):
                    ContextualTranslationRequest(
                        source_language="en",
                        target_language="es",
                        segments=[segment],
                    )


if __name__ == "__main__":
    unittest.main()
