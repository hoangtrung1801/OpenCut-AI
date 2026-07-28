import unittest

from app.models.translation import DisplayCaptionSegment
from app.services.subtitle_service import (
    _format_srt_time,
    _format_vtt_time,
    build_subtitle_documents,
)


def segments():
    return [
        DisplayCaptionSegment(
            id=0,
            parent_id=0,
            part_index=0,
            source="Hello",
            translation="Xin chào",
            start=1.2,
            end=2.5,
        ),
        DisplayCaptionSegment(
            id=1,
            parent_id=1,
            part_index=0,
            source="Goodbye",
            translation="Tạm biệt",
            start=3.0,
            end=4.0,
        ),
    ]


class SubtitleTimestampTests(unittest.TestCase):
    def test_srt_rounding_carries_into_next_second(self):
        self.assertEqual(_format_srt_time(1.9996), "00:00:02,000")

    def test_vtt_rounding_carries_into_next_second(self):
        self.assertEqual(_format_vtt_time(59.9996), "00:01:00.000")


class SubtitleDocumentTests(unittest.TestCase):
    def test_builds_monolingual_and_bilingual_documents_without_rewrapping(self):
        documents = build_subtitle_documents(segments())

        self.assertIn("Hello", documents.source.srt)
        self.assertNotIn("Xin chào", documents.source.srt)
        self.assertIn("Xin chào", documents.translation.srt)
        self.assertIn("Hello\nXin chào", documents.source_translation.srt)
        self.assertIn("Xin chào\nHello", documents.translation_source.vtt)
        self.assertEqual(documents.source.srt.count(" --> "), 2)
        self.assertNotIn("Hello\nGoodbye", documents.source.srt)


if __name__ == "__main__":
    unittest.main()
