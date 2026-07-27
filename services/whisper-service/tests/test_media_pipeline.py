import tempfile
import unittest
from pathlib import Path

from media_pipeline import MediaPipeline, MediaProcessingError
from settings import Settings


class FakeSeparator:
    def __init__(self):
        self.background_sources = []

    def separate(self, source_path: Path, output_dir: Path):
        self.background_sources = ["drums", "bass", "other"]
        vocals = output_dir / "vocals-lossless.wav"
        background = output_dir / "background-lossless.wav"
        vocals.write_bytes(b"vocal wav")
        background.write_bytes(b"background wav")
        return vocals, background


class FakeCommandRunner:
    def __init__(self):
        self.commands = []
        self.fail_on = None

    def __call__(self, args):
        self.commands.append(list(args))
        output = Path(args[-1])
        if self.fail_on and self.fail_on in output.name:
            raise RuntimeError(f"ffmpeg failed for {output.name}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"encoded audio")


class MediaPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "input.mp4"
        self.source.write_bytes(b"source")
        self.runner = FakeCommandRunner()
        self.separator = FakeSeparator()
        self.settings = Settings.from_env(
            {
                "ARTIFACT_DIR": str(self.root / "artifacts"),
                "DEMUCS_MP3_BITRATE": "192k",
            }
        )
        self.pipeline = MediaPipeline(
            self.settings,
            separator=self.separator,
            command_runner=self.runner,
        )
        self.artifact_id = "123e4567-e89b-12d3-a456-426614174000"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_prepare_sums_non_vocal_sources_and_uses_original_mix_for_asr(self):
        prepared = self.pipeline.prepare(self.source, self.artifact_id)

        self.assertEqual(self.separator.background_sources, ["drums", "bass", "other"])
        self.assertIn("original-asr.wav", str(prepared.asr_path))
        self.assertIn("vocal-align.wav", str(prepared.alignment_path))
        self.assertEqual(prepared.vocals_path.name, "vocals.mp3")
        self.assertEqual(prepared.background_path.name, "background.mp3")
        self.assertTrue(prepared.vocals_path.stat().st_size > 0)
        self.assertTrue(prepared.background_path.stat().st_size > 0)
        self.assertTrue(any("192k" in command for command in self.runner.commands))

    def test_failed_prepare_removes_partial_artifact_directory(self):
        self.runner.fail_on = "background.mp3"

        with self.assertRaises(MediaProcessingError):
            self.pipeline.prepare(self.source, self.artifact_id)

        self.assertFalse((self.settings.artifact_dir / self.artifact_id).exists())
        self.assertFalse((self.settings.artifact_dir / f"{self.artifact_id}.partial").exists())

    def test_completed_artifacts_are_not_removed_by_temporary_cleanup(self):
        prepared = self.pipeline.prepare(self.source, self.artifact_id)
        prepared.cleanup_temporary()

        self.assertTrue(prepared.vocals_path.exists())
        self.assertTrue(prepared.background_path.exists())
        self.assertFalse(prepared.asr_path.exists())
        self.assertFalse(prepared.alignment_path.exists())

    def test_artifact_path_rejects_traversal_and_unknown_stems(self):
        with self.assertRaises(ValueError):
            self.pipeline.artifact_path("../../escape", "vocals")
        with self.assertRaises(ValueError):
            self.pipeline.artifact_path(self.artifact_id, "drums")


if __name__ == "__main__":
    unittest.main()
