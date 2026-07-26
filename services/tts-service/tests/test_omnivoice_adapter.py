import unittest
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from app import SUPPORTED_LANGUAGES, TTSService


class OmniVoiceAdapterTest(unittest.TestCase):
    def test_supported_languages_include_vietnamese(self):
        self.assertIn("vi", SUPPORTED_LANGUAGES)

    def setUp(self):
        self.service = TTSService()

    def test_reference_audio_uses_voice_cloning(self):
        kwargs = self.service._build_generation_kwargs(
            text="Hello",
            language="en",
            speaker_wav="voices/alice.wav",
            speaker=None,
            speed=1.2,
        )

        self.assertEqual(kwargs["ref_audio"], "voices/alice.wav")
        self.assertNotIn("instruct", kwargs)
        self.assertEqual(kwargs["language"], "en")
        self.assertEqual(kwargs["speed"], 1.2)

    def test_speaker_uses_voice_design_without_reference_audio(self):
        kwargs = self.service._build_generation_kwargs(
            text="Hello",
            language="de",
            speaker_wav=None,
            speaker="female",
            speed=1.0,
        )

        self.assertEqual(kwargs["instruct"], "female")
        self.assertNotIn("ref_audio", kwargs)
        self.assertEqual(kwargs["language"], "de")

    def test_no_voice_input_uses_auto_voice(self):
        kwargs = self.service._build_generation_kwargs(
            text="Hello",
            language="en",
            speaker_wav=None,
            speaker=None,
            speed=1.0,
        )

        self.assertNotIn("ref_audio", kwargs)
        self.assertNotIn("instruct", kwargs)

    def test_generated_audio_is_saved_at_model_sample_rate(self):
        self.service._model = type("Model", (), {"sampling_rate": 24000})()
        audio = np.zeros(240, dtype=np.float32)

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output.wav"
            self.service._write_audio(audio, str(output_path))
            _, sample_rate = sf.read(output_path)

        self.assertEqual(sample_rate, 24000)


if __name__ == "__main__":
    unittest.main()
