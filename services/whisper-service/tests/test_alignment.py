import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from alignment import WhisperAligner, canonical_words_from_segments
from models import WordToken
from settings import Settings


class AlignmentTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vocals = Path(self.temp_dir.name) / "vocal-align.wav"
        self.vocals.write_bytes(b"audio")
        self.raw_segments = [
            SimpleNamespace(
                text=" Hello world",
                start=0.5,
                end=1.4,
                words=[
                    SimpleNamespace(word=" Hello", start=0.5, end=0.9, probability=0.8),
                    SimpleNamespace(word=" world", start=1.0, end=1.4, probability=0.9),
                ],
                avg_logprob=-0.2,
                no_speech_prob=0.01,
            )
        ]
        self.native_words = canonical_words_from_segments(self.raw_segments)
        self.loaded_model = object()
        self.align_calls = []

        def loader(language, device):
            return self.loaded_model, {"language": language}

        def align_fn(segments, model, metadata, audio_path, **kwargs):
            self.align_calls.append((segments, model, metadata, audio_path))
            return {"word_segments": [
                {"word": "Hello", "start": 0.12, "end": 0.44},
                {"word": "world", "start": 0.51, "end": 0.91},
            ]}

        self.loader = loader
        self.align_fn = align_fn
        self.aligner = WhisperAligner(
            Settings.from_env({"WHISPERX_DEVICE": "cpu"}),
            model_loader=self.loader,
            align_fn=self.align_fn,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_aligned_timestamps_replace_native_times_without_rewriting_words(self):
        aligned = self.aligner.align(self.native_words, self.raw_segments, "en", self.vocals)
        self.assertEqual([word.word for word in aligned], ["Hello", "world"])
        self.assertEqual([(word.start, word.end) for word in aligned], [(0.12, 0.44), (0.51, 0.91)])
        self.assertEqual(aligned[0].probability, self.native_words[0].probability)

    def test_unsupported_language_returns_native_word_objects(self):
        def failing_loader(language, device):
            raise ValueError("unsupported language")

        aligner = WhisperAligner(Settings.from_env({}), model_loader=failing_loader, align_fn=self.align_fn)
        aligned = aligner.align(self.native_words, self.raw_segments, "vi", self.vocals)
        self.assertEqual(aligned, self.native_words)

    def test_unalignable_token_keeps_native_timestamp(self):
        def missing_timestamp_align(*args, **kwargs):
            return {"word_segments": [{"word": "Hello", "start": None, "end": None}]}

        aligner = WhisperAligner(
            Settings.from_env({}), model_loader=self.loader, align_fn=missing_timestamp_align
        )
        aligned = aligner.align(self.native_words, self.raw_segments, "en", self.vocals)
        self.assertEqual((aligned[0].start, aligned[0].end), (0.5, 0.9))

    def test_alignment_exception_returns_same_native_list(self):
        def failing_align(*args, **kwargs):
            raise RuntimeError("model failed")

        aligner = WhisperAligner(Settings.from_env({}), model_loader=self.loader, align_fn=failing_align)
        self.assertIs(aligner.align(self.native_words, self.raw_segments, "en", self.vocals), self.native_words)


if __name__ == "__main__":
    unittest.main()
