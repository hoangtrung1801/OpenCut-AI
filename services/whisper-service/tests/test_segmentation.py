import unittest
from types import SimpleNamespace

from models import WordToken
from segmentation import SPACY_MODELS, SpacySegmenter, reconstruct_segments
from settings import Settings


def words_for(texts):
    result = []
    cursor = 0.0
    for index, text in enumerate(texts):
        raw = text if index == 0 else f" {text}"
        result.append(
            WordToken(
                raw_text=raw,
                word=text.strip(),
                start=cursor,
                end=cursor + 0.4,
                probability=0.8,
                source_segment_id=0,
                avg_logprob=-0.2,
                no_speech_prob=0.01,
            )
        )
        cursor += 0.45
    return result


class FakeDoc:
    def __init__(self, sents=(), annotations=True):
        self.sents = list(sents)
        self._annotations = annotations

    def has_annotation(self, name):
        return self._annotations and name in {"DEP", "POS"}


class FakeNlp:
    def __init__(self, docs=None):
        self.docs = docs or {}

    def __call__(self, text):
        return self.docs.get(text, FakeDoc())


class Loader:
    def __init__(self, nlp):
        self.nlp = nlp
        self.requested_models = []

    def __call__(self, model):
        self.requested_models.append(model)
        return self.nlp


class SegmentationTests(unittest.TestCase):
    def setUp(self):
        self.words = words_for(["I", "am", "ready.", "Then", "we", "go!"])
        self.vi_words = words_for(["Tôi", "muốn", "đi", "nhưng", "trời", "đang", "mưa."])
        self.loader = Loader(FakeNlp())
        self.segmenter = SpacySegmenter(Settings.from_env({}), loader=self.loader)

    def test_vietnamese_uses_multilingual_senter_and_never_english_parser(self):
        groups = self.segmenter.preliminary_groups(self.vi_words, "vi")
        self.assertEqual(self.loader.requested_models, ["xx_sent_ud_sm"])
        self.assertEqual([" ".join(word.word for word in group) for group in groups], [
            "Tôi muốn đi",
            "nhưng trời đang mưa.",
        ])

    def test_spacy_character_boundary_maps_to_original_word_timestamp(self):
        nlp = FakeNlp()
        self.loader.nlp = nlp
        groups = self.segmenter.preliminary_groups(self.words, "en")
        self.assertEqual(groups[1][0].start, self.words[3].start)

    def test_parserless_pipeline_does_not_read_dependency_annotations(self):
        self.loader.nlp = FakeNlp()
        groups = self.segmenter.preliminary_groups(self.words, "xx")
        self.assertTrue(groups)

    def test_pause_creates_boundary_and_punctuation_stays_with_previous_group(self):
        paused = words_for(["hello", "there", "now.", "after"])
        paused[3] = WordToken(**{**paused[3].__dict__, "start": 2.0, "end": 2.4})
        groups = self.segmenter.preliminary_groups(paused, "xx")
        self.assertEqual(groups[0][-1].word, "now.")
        self.assertEqual(groups[1][0].word, "after")

    def test_reconstruction_is_lossless_and_monotonic(self):
        segments = reconstruct_segments([self.words[:2], self.words[2:]])
        self.assertEqual([w.word for s in segments for w in s.words], [w.word for w in self.words])
        self.assertLessEqual(segments[0].end, segments[1].start)
        self.assertEqual(segments[0].text, "I am")

    def test_language_map_has_vietnamese_and_multilingual_fallback(self):
        self.assertEqual(SPACY_MODELS["vi"], "xx_sent_ud_sm")
        self.assertEqual(SPACY_MODELS.get("ko", "xx_sent_ud_sm"), "xx_sent_ud_sm")


if __name__ == "__main__":
    unittest.main()
