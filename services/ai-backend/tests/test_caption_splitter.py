import unittest

from app.models.translation import DisplayCaptionSegment, TranslationWordInput
from app.services.caption_splitter import (
    close_short_gaps,
    requires_split,
    split_timed_source,
    weighted_length,
)


class WeightedLengthTests(unittest.TestCase):
    def test_applies_videolingo_script_weights(self):
        self.assertEqual(weighted_length("abc"), 3)
        self.assertEqual(weighted_length("漢"), 1.75)
        self.assertEqual(weighted_length("あ"), 1.75)
        self.assertEqual(weighted_length("한"), 1.5)
        self.assertEqual(weighted_length("ก"), 1.0)
        self.assertEqual(weighted_length("Ａ"), 1.75)
        self.assertEqual(weighted_length("Tiếng Việt"), 10)

    def test_target_multiplier_can_trigger_split(self):
        self.assertTrue(
            requires_split(
                "short",
                "12345678901234567",
                max_chars=32,
                target_multiplier=2.0,
            )
        )


class TimedSourceSplitTests(unittest.TestCase):
    def test_vietnamese_prefers_punctuation_then_word_boundaries(self):
        left, right = split_timed_source(
            source="Đây là phần đầu, và đây là phần tiếp theo",
            start=0,
            end=4,
            words=[],
            max_chars=24,
        )

        self.assertEqual(
            f"{left.text} {right.text}",
            "Đây là phần đầu, và đây là phần tiếp theo",
        )
        self.assertTrue(left.text.endswith(","))

    def test_uses_word_timestamps_when_words_reconstruct_source(self):
        left, right = split_timed_source(
            source="one two three four",
            start=1,
            end=5,
            words=[
                TranslationWordInput(word="one", start=1, end=2),
                TranslationWordInput(word="two", start=2, end=3),
                TranslationWordInput(word="three", start=3, end=4),
                TranslationWordInput(word="four", start=4, end=5),
            ],
            max_chars=10,
        )

        self.assertEqual((left.start, left.end), (1, 3))
        self.assertEqual((right.start, right.end), (3, 5))

    def test_missing_word_coverage_uses_proportional_parent_timing(self):
        left, right = split_timed_source(
            source="one two three four",
            start=10,
            end=14,
            words=[],
            max_chars=10,
        )

        self.assertEqual(left.start, 10)
        self.assertEqual(right.end, 14)
        self.assertEqual(left.end, right.start)

    def test_long_single_token_is_sliced_by_characters(self):
        left, right = split_timed_source(
            source="a" * 40,
            start=0,
            end=4,
            words=[],
            max_chars=20,
        )

        self.assertEqual((len(left.text), len(right.text)), (20, 20))
        self.assertEqual((left.start, left.end), (0, 2))
        self.assertEqual((right.start, right.end), (2, 4))


class GapClosingTests(unittest.TestCase):
    @staticmethod
    def display(*, id: int, parent_id: int, start: float, end: float):
        return DisplayCaptionSegment(
            id=id,
            parent_id=parent_id,
            part_index=0,
            source=f"source-{id}",
            translation=f"translation-{id}",
            start=start,
            end=end,
        )

    def test_closes_only_positive_gaps_below_threshold_within_parent(self):
        result = close_short_gaps(
            [
                self.display(id=0, parent_id=0, start=0, end=1),
                self.display(id=1, parent_id=0, start=1.5, end=2),
                self.display(id=2, parent_id=1, start=3.5, end=4),
            ],
            threshold=1.0,
        )

        self.assertEqual(result[0].end, 1.5)
        self.assertEqual(result[1].end, 2)
        self.assertEqual(result[2].start, 3.5)


if __name__ == "__main__":
    unittest.main()
