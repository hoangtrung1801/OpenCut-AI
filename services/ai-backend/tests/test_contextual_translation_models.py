import unittest

from pydantic import ValidationError

from app.models.translation import ContextualTranslationRequest


class ContextualTranslationModelTests(unittest.TestCase):
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
