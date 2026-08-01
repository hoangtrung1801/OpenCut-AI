import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from models import PreparedMedia, WordToken
from pipeline import TranscriptionPipeline
from semantic_client import SemanticValidationError
from settings import Settings


def make_words(count):
    return [
        WordToken(f" w{i}", f"w{i}", float(i), float(i + 0.5), 0.9, 0, -0.1, 0.01)
        for i in range(count)
    ]


class FakeMedia:
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.cleaned = False

    def prepare(self, source_path, artifact_id):
        self.calls.append("media")
        artifact = self.root / artifact_id
        artifact.mkdir(parents=True)
        paths = [artifact / name for name in ("original-asr.wav", "vocal-align.wav", "vocals.mp3", "background.mp3")]
        for path in paths:
            path.write_bytes(b"audio")
        return PreparedMedia(artifact_id, paths[0], paths[1], paths[2], paths[3])


class FakeAsr:
    def __init__(self, words):
        self.words = words
        self.calls = []

    def transcribe_raw(self, path, language):
        self.calls.append("asr")
        return [], SimpleNamespace(language=language or "en", duration=12.5), self.words


class FakeAligner:
    def __init__(self):
        self.calls = []

    def align(self, words, raw_segments, language, path):
        self.calls.append("align")
        return words


class FakeSegmenter:
    def __init__(self, words):
        self.words = words
        self.calls = []

    def preliminary_groups(self, words, language):
        self.calls.append("spacy")
        return [self.words]


class FakeSemantic:
    def __init__(self):
        self.calls = []

    def split(self, words, language, candidates):
        self.calls.append("semantic")
        return [list(words[:10]), list(words[10:])]


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        source = root / "source.mp4"
        source.write_bytes(b"source")
        self.source = source
        self.artifact_id = "123e4567-e89b-12d3-a456-426614174000"
        self.settings = Settings.from_env({"ARTIFACT_DIR": str(root / "artifacts")})

    def tearDown(self):
        self.temp_dir.cleanup()

    def _pipeline(self, count):
        words = make_words(count)
        media = FakeMedia(self.settings.artifact_dir)
        asr = FakeAsr(words)
        aligner = FakeAligner()
        segmenter = FakeSegmenter(words)
        semantic = FakeSemantic()
        pipeline = TranscriptionPipeline(
            self.settings,
            media=media,
            asr=asr,
            aligner=aligner,
            segmenter=segmenter,
            semantic=semantic,
        )
        return pipeline, media, asr, aligner, segmenter, semantic

    def test_call_order_and_artifact_urls_for_long_group(self):
        pipeline, media, asr, aligner, segmenter, semantic = self._pipeline(21)
        result = pipeline.run(self.source, "en", self.artifact_id)
        self.assertEqual(media.calls + asr.calls + aligner.calls + segmenter.calls + semantic.calls,
                         ["media", "asr", "align", "spacy", "semantic"])
        self.assertEqual(len(result.segments), 2)
        self.assertEqual(result.separated_audio.vocals_url, f"/artifacts/{self.artifact_id}/vocals")
        self.assertEqual(result.separated_audio.background_url, f"/artifacts/{self.artifact_id}/background")

    def test_short_group_skips_semantic_refinement(self):
        pipeline, _media, _asr, _aligner, _segmenter, semantic = self._pipeline(10)
        result = pipeline.run(self.source, "en", self.artifact_id)
        self.assertEqual(len(result.segments), 1)
        self.assertEqual(semantic.calls, [])

    def test_rejected_semantic_boundaries_use_lossless_bounded_fallback(self):
        pipeline, _media, _asr, _aligner, _segmenter, _semantic = self._pipeline(21)

        class RejectedSemantic:
            def split(self, words, language, candidates):
                raise SemanticValidationError("rejected")

        pipeline.semantic = RejectedSemantic()
        result = pipeline.run(self.source, "en", self.artifact_id)

        self.assertEqual(len(result.segments), 2)
        self.assertEqual(
            [word for segment in result.segments for word in segment.text.split()],
            [f"w{index}" for index in range(21)],
        )


if __name__ == "__main__":
    unittest.main()
