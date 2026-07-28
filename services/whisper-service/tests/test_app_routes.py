import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as app_module
from media_pipeline import MediaPipeline
from models import SeparatedAudio, TranscriptionResult
from semantic_client import SemanticSegmentationError
from settings import Settings


class FakePipeline:
    def __init__(self):
        self.error = None

    def run(self, source_path, language, artifact_id):
        if self.error:
            raise self.error
        return TranscriptionResult(
            text="hello",
            segments=[],
            language=language or "en",
            duration=1.0,
            separated_audio=SeparatedAudio(
                vocals_url=f"/artifacts/{artifact_id}/vocals",
                background_url=f"/artifacts/{artifact_id}/background",
            ),
        )


class AppRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.upload_dir = root / "uploads"
        artifact_dir = root / "artifacts"
        self.upload_dir.mkdir()
        settings = Settings.from_env({"UPLOAD_DIR": str(self.upload_dir), "ARTIFACT_DIR": str(artifact_dir)})
        self.artifact_id = "123e4567-e89b-12d3-a456-426614174000"
        artifact = artifact_dir / self.artifact_id
        artifact.mkdir(parents=True)
        (artifact / "vocals.mp3").write_bytes(b"vocal")
        (artifact / "background.mp3").write_bytes(b"background")
        self.fake_pipeline = FakePipeline()
        self.settings_patch = patch.multiple(
            app_module,
            settings=settings,
            UPLOAD_DIR=str(self.upload_dir),
            media_pipeline=MediaPipeline(settings, separator=object(), command_runner=lambda _args: None),
            transcription_pipeline=self.fake_pipeline,
        )
        self.settings_patch.start()
        self.client = TestClient(app_module.app)

    def tearDown(self):
        self.settings_patch.stop()
        self.temp_dir.cleanup()

    def test_transcribe_returns_refined_result_and_artifact_paths(self):
        response = self.client.post(
            "/transcribe",
            files={"file": ("sample.wav", b"RIFF...", "audio/wav")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("separated_audio", response.json())

    def test_artifact_route_serves_only_allowed_stems(self):
        ok = self.client.get(f"/artifacts/{self.artifact_id}/vocals")
        bad = self.client.get(f"/artifacts/{self.artifact_id}/drums")
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.headers["content-type"].startswith("audio/mpeg"))
        self.assertIn(bad.status_code, {400, 404, 422})

    def test_semantic_failure_returns_stage_specific_error_and_cleans_upload(self):
        self.fake_pipeline.error = SemanticSegmentationError("timeout")
        response = self.client.post(
            "/transcribe",
            files={"file": ("sample.wav", b"RIFF...", "audio/wav")},
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(list(self.upload_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
