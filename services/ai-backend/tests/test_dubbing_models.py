import unittest

from pydantic import ValidationError

from app.config import settings
from app.models.dubbing import DubbingJobCreateRequest, DubbingLimits


def request_payload(voice: dict) -> dict:
    return {
        "source_language": "en",
        "target_language": "vi",
        "audio_segments": [{
            "id": 10,
            "source": "Hello.",
            "translation": "Xin chào.",
            "start": 2.0,
            "end": 3.2,
        }],
        "display_segments": [{
            "id": 20,
            "parent_id": 10,
            "part_index": 0,
            "source": "Hello.",
            "translation": "Xin chào.",
            "start": 2.0,
            "end": 3.2,
        }],
        "voice": voice,
        "pace": 1.0,
    }


class DubbingModelsTest(unittest.TestCase):
    def test_accepts_explicit_clone_design_and_auto_modes(self):
        for voice in (
            {
                "mode": "clone",
                "speaker_wav": "generated/voices/alice.wav",
                "reference_text": "Hello from Alice.",
            },
            {"mode": "design", "speaker": "warm female narrator"},
            {"mode": "auto"},
        ):
            self.assertEqual(
                DubbingJobCreateRequest.model_validate(request_payload(voice)).voice.mode,
                voice["mode"],
            )

    def test_rejects_mixed_voice_fields_and_clone_path_traversal(self):
        invalid = (
            {
                "mode": "clone",
                "speaker_wav": "../../secret.wav",
                "reference_text": "Hello.",
            },
            {
                "mode": "design",
                "speaker": "warm",
                "speaker_wav": "generated/voices/a.wav",
            },
            {"mode": "auto", "speaker": "warm"},
        )
        for voice in invalid:
            with self.assertRaises(ValidationError):
                DubbingJobCreateRequest.model_validate(request_payload(voice))

    def test_rejects_display_rows_without_a_parent(self):
        payload = request_payload({"mode": "auto"})
        payload["display_segments"][0]["parent_id"] = 999
        with self.assertRaises(ValidationError):
            DubbingJobCreateRequest.model_validate(payload)

    def test_loads_positive_ordered_limits(self):
        limits = DubbingLimits.from_settings(settings)
        self.assertLessEqual(limits.accept_speed, limits.max_speed)
        self.assertEqual(limits.max_chunk_segments, 5)


if __name__ == "__main__":
    unittest.main()
