import os
import unittest
from pathlib import Path

from models import SeparatedAudio, TranscriptionResult
from settings import Settings, SettingsError


class SettingsModelTests(unittest.TestCase):
    def test_environment_values_are_normalized_into_runtime_settings(self):
        settings = Settings.from_env(
            {
                "AI_BACKEND_URL": "http://ai:8420/",
                "ARTIFACT_DIR": "/srv/artifacts",
                "DEMUCS_DEVICE": "CUDA",
                "WHISPERX_ALIGNMENT_ENABLED": "no",
                "SEMANTIC_MAX_WORDS": "18",
                "SEMANTIC_MIN_WORDS": "4",
                "SEMANTIC_WINDOW_WORDS": "48",
            }
        )

        self.assertEqual(settings.ai_backend_url, "http://ai:8420")
        self.assertEqual(settings.artifact_dir, Path("/srv/artifacts"))
        self.assertEqual(settings.demucs_device, "cuda")
        self.assertFalse(settings.whisperx_alignment_enabled)
        self.assertEqual(settings.semantic_max_words, 18)

    def test_invalid_semantic_limits_are_rejected(self):
        with self.assertRaises(SettingsError):
            Settings.from_env(
                {
                    "SEMANTIC_MAX_WORDS": "3",
                    "SEMANTIC_MIN_WORDS": "3",
                    "SEMANTIC_WINDOW_WORDS": "2",
                }
            )

    def test_defaults_keep_artifacts_and_semantic_segmentation_enabled(self):
        settings = Settings.from_env({})

        self.assertEqual(settings.artifact_dir, Path("artifacts"))
        self.assertEqual(settings.demucs_model, "htdemucs")
        self.assertTrue(settings.semantic_split_enabled)
        self.assertEqual(settings.semantic_max_words, 20)
        self.assertEqual(settings.semantic_max_retries, 3)

    def test_result_serializes_additive_artifact_urls(self):
        result = TranscriptionResult(
            text="hello",
            segments=[],
            language="en",
            duration=1.0,
            separated_audio=SeparatedAudio(
                vocals_url="/artifacts/abc/vocals",
                background_url="/artifacts/abc/background",
            ),
        )

        self.assertEqual(
            result.model_dump()["separated_audio"]["vocals_url"],
            "/artifacts/abc/vocals",
        )


if __name__ == "__main__":
    unittest.main()
