import json
import tempfile
import unittest
import wave
from pathlib import Path

from app.services.dubbing_audio import DubbingAudioProcessor, fit_chunk_timing


class DubbingAudioFitTest(unittest.TestCase):
    def test_preserves_original_gap_when_fit_is_below_accepted_speed(self):
        fit = fit_chunk_timing(
            clip_windows=[(10, 0.0, 1.0), (11, 1.5, 2.5)],
            raw_durations={10: 0.8, 11: 0.8},
            allowed_end=3.0,
            accept_speed=1.2,
            max_speed=1.4,
        )
        self.assertTrue(fit.keep_gaps)
        self.assertEqual(fit.speed, 1.0)
        self.assertAlmostEqual(fit.clips[1].start, 1.5)

    def test_removes_gaps_before_exceeding_accepted_speed(self):
        fit = fit_chunk_timing(
            clip_windows=[(10, 0.0, 1.0), (11, 1.5, 2.5)],
            raw_durations={10: 1.4, 11: 1.4},
            allowed_end=2.5,
            accept_speed=1.2,
            max_speed=1.4,
        )
        self.assertFalse(fit.keep_gaps)
        self.assertLessEqual(fit.speed, 1.2)

    def test_caps_speed_and_ripples_overflow_without_truncation(self):
        fit = fit_chunk_timing(
            clip_windows=[(10, 0.0, 1.0), (11, 1.0, 2.0)],
            raw_durations={10: 2.0, 11: 2.0},
            allowed_end=2.0,
            accept_speed=1.2,
            max_speed=1.4,
        )
        self.assertEqual(fit.speed, 1.4)
        self.assertGreater(fit.clips[-1].end, 2.0)
        self.assertEqual(
            [clip.timing_warning for clip in fit.clips],
            [None, "overflow"],
        )
        self.assertGreaterEqual(fit.clips[1].start, fit.clips[0].end)


class DubbingAudioProcessorTest(unittest.TestCase):
    def test_adjust_speed_builds_ffmpeg_command(self):
        commands: list[tuple[str, ...]] = []
        processor = DubbingAudioProcessor(command_runner=commands.append)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "raw.wav"
            destination = Path(directory) / "adjusted.wav"
            source.write_bytes(b"wav")
            processor.adjust_speed(source, destination, 1.2)

        self.assertEqual(commands[0][0], "ffmpeg")
        self.assertIn("atempo=1.200000", commands[0])
        self.assertEqual(commands[0][-1], str(destination))

    def test_probe_duration_uses_injected_ffprobe_output(self):
        processor = DubbingAudioProcessor(
            probe_runner=lambda _args: json.dumps({"format": {"duration": "1.25"}}),
        )
        self.assertEqual(processor.probe_duration(Path("clip.wav")), 1.25)

    def test_write_silence_creates_a_valid_short_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "silence.wav"
            DubbingAudioProcessor.write_silence(path, duration=0.1)
            with wave.open(str(path), "rb") as audio:
                self.assertEqual(audio.getframerate(), 16_000)
                self.assertEqual(audio.getnchannels(), 1)
                self.assertGreater(audio.getnframes(), 0)


if __name__ == "__main__":
    unittest.main()
