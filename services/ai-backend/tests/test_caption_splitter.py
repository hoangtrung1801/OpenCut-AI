import unittest

from app.models.translation import DisplayCaptionSegment, TranslationWordInput
from app.services.caption_splitter import (
    caption_fits,
    close_short_gaps,
    normalize_caption_text,
    requires_split,
    split_timed_source,
    wrap_caption_text,
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
                "1234567890123456789012345678901234567890",
                max_chars=32,
                target_multiplier=2.0,
            )
        )

    def test_two_line_capacity_and_inline_normalization(self):
        text = "  Một dòng\n tự nhiên.  "
        self.assertEqual(normalize_caption_text(text), "Một dòng tự nhiên.")
        self.assertTrue(caption_fits("Một câu ngắn.", max_chars=32))
        self.assertFalse(
            caption_fits("Một câu có rất nhiều từ cần được xuống dòng để đọc dễ hơn.", max_chars=12)
        )

    def test_vietnamese_wraps_to_two_balanced_lines_at_word_boundaries(self):
        text = "Mọi người ơi, làm nhân sự ở thiên đình là trải nghiệm thế nào?"

        wrapped = wrap_caption_text(text, max_chars=32)

        lines = wrapped.splitlines()
        self.assertLessEqual(len(lines), 2)
        self.assertTrue(all(weighted_length(line) <= 32 for line in lines))
        self.assertEqual(wrapped.replace("\n", ""), text)
        self.assertNotIn("\n ", wrapped)


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

    def test_chinese_uses_whisper_word_boundaries_without_isolating_punctuation(self):
        words = [
            TranslationWordInput(word="家", start=0.38, end=0.46),
            TranslationWordInput(word="人", start=0.46, end=0.54),
            TranslationWordInput(word="们,", start=0.54, end=0.72),
            TranslationWordInput(word="在", start=0.76, end=1.18),
            TranslationWordInput(word="天", start=1.18, end=1.52),
            TranslationWordInput(word="庭", start=1.52, end=1.80),
            TranslationWordInput(word="做", start=1.80, end=1.98),
            TranslationWordInput(word="人", start=1.98, end=2.18),
            TranslationWordInput(word="士", start=2.18, end=2.46),
            TranslationWordInput(word="是", start=2.46, end=2.64),
            TranslationWordInput(word="一", start=2.64, end=2.74),
            TranslationWordInput(word="种", start=2.74, end=2.94),
            TranslationWordInput(word="什么", start=2.94, end=3.14),
            TranslationWordInput(word="体", start=3.14, end=3.38),
            TranslationWordInput(word="验?", start=3.38, end=3.72),
        ]

        left, right = split_timed_source(
            source="家人们,在天庭做人士是一种什么体验?",
            start=0.38,
            end=3.72,
            words=words,
            max_chars=32,
            min_duration=0.8,
        )

        self.assertEqual(left.text + right.text, "家人们,在天庭做人士是一种什么体验?")
        self.assertNotIn(left.text, {"?", "。", "!", "！", "？"})
        self.assertNotIn(right.text, {"?", "。", "!", "！", "？"})
        self.assertEqual(left.start, 0.38)
        self.assertEqual(right.end, 3.72)
        self.assertLessEqual(left.end, right.start)
        self.assertGreaterEqual(left.end - left.start, 0.8)
        self.assertGreaterEqual(right.end - right.start, 0.8)

    def test_chinese_character_fallback_keeps_terminal_punctuation_attached(self):
        left, right = split_timed_source(
            source="了吃不上饭了,我被分到了考工科。",
            start=10.9,
            end=13.85,
            words=[],
            max_chars=32,
        )

        self.assertEqual(left.text + right.text, "了吃不上饭了,我被分到了考工科。")
        self.assertNotEqual(right.text, "。")

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
