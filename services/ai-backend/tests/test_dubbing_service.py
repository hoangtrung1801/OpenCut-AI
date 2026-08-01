import asyncio
import tempfile
import unittest
import wave
from pathlib import Path

from app.config import settings
from app.models.dubbing import (
    AutoVoice,
    DubbingDisplaySegment,
    DubbingJobCreateRequest,
    DubbingJobStatus,
    DubbingLimits,
    DubbingParentSegment,
)
from app.services.dubbing_service import DubbingJobManager
from app.services.dubbing_tts_client import DubbingTTSGenerationError


def write_wav(path: Path, duration: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\x00\x00" * max(1, round(16_000 * duration)))


def request_with_displays(displays: list[tuple[int, int, int, str, float, float]]):
    parents = []
    for parent_id in sorted({item[1] for item in displays}):
        parent_displays = [item for item in displays if item[1] == parent_id]
        parents.append(
            DubbingParentSegment(
                id=parent_id,
                source=f"Source {parent_id}.",
                translation=f"Translation {parent_id}.",
                start=parent_displays[0][4],
                end=parent_displays[-1][5],
            )
        )
    return DubbingJobCreateRequest(
        source_language="en",
        target_language="vi",
        audio_segments=parents,
        display_segments=[
            DubbingDisplaySegment(
                id=identifier,
                parent_id=parent_id,
                part_index=part_index,
                source=text,
                translation=text,
                start=start,
                end=end,
            )
            for identifier, parent_id, part_index, text, start, end in displays
        ],
        voice=AutoVoice(mode="auto"),
    )


def two_clip_request() -> DubbingJobCreateRequest:
    return request_with_displays([
        (10, 1, 0, "First.", 0.0, 1.0),
        (11, 1, 1, "Second.", 1.0, 2.0),
    ])


def one_clip_request() -> DubbingJobCreateRequest:
    return request_with_displays([(10, 1, 0, "First.", 0.0, 1.0)])


def annotation_only_request() -> DubbingJobCreateRequest:
    return DubbingJobCreateRequest(
        source_language="en",
        target_language="vi",
        audio_segments=[DubbingParentSegment(
            id=1,
            source="(laughs)",
            translation="(laughs)",
            start=0.0,
            end=1.0,
        )],
        display_segments=[DubbingDisplaySegment(
            id=10,
            parent_id=1,
            part_index=0,
            source="(laughs)",
            translation="(laughs)",
            start=0.0,
            end=1.0,
        )],
        voice=AutoVoice(mode="auto"),
    )


def limits() -> DubbingLimits:
    return DubbingLimits(
        max_concurrent_jobs=1,
        max_tts_concurrency=2,
        max_chunk_segments=5,
        accept_speed=1.2,
        max_speed=1.4,
        gap_tolerance_seconds=1.5,
        tts_retries=0,
    )


class FakeTTS:
    def __init__(self, durations: dict[int, float]):
        self.durations = durations
        self.calls: list[str] = []

    async def check_ready(self) -> None:
        return None

    async def generate_to_file(
        self,
        *,
        text,
        language,
        voice,
        pace,
        destination,
    ) -> None:
        self.calls.append(text)
        clip_number = 10 if text == "First." else 11
        write_wav(destination, self.durations.get(clip_number, 0.5))


class FailingTTS(FakeTTS):
    def __init__(self, error: Exception):
        super().__init__({})
        self.error = error

    async def generate_to_file(self, **kwargs) -> None:
        raise self.error


class ConcurrencyTrackingTTS(FakeTTS):
    def __init__(self):
        super().__init__({10: 0.5, 11: 0.5})
        self.active_calls = 0
        self.max_active_calls = 0

    async def generate_to_file(self, **kwargs) -> None:
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            await asyncio.sleep(0.01)
            await super().generate_to_file(**kwargs)
        finally:
            self.active_calls -= 1


class FakeAudioProcessor:
    @staticmethod
    def write_silence(path: Path, duration: float = 0.1) -> None:
        write_wav(path, duration)

    @staticmethod
    def probe_duration(path: Path) -> float:
        with wave.open(str(path), "rb") as audio:
            return audio.getnframes() / audio.getframerate()

    @staticmethod
    def adjust_speed(source: Path, destination: Path, speed: float) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())


def make_manager(
    *,
    root: Path,
    tts,
    audio=None,
    status_observer=None,
) -> DubbingJobManager:
    return DubbingJobManager(
        generated_root=root,
        limits=limits(),
        tts_client=tts,
        audio_processor=audio or FakeAudioProcessor(),
        status_observer=status_observer,
    )


class DubbingJobManagerTest(unittest.IsolatedAsyncioTestCase):
    async def test_default_configuration_serializes_tts_generation(self):
        tts = ConcurrencyTrackingTTS()
        with tempfile.TemporaryDirectory() as directory:
            manager = DubbingJobManager(
                generated_root=Path(directory),
                limits=DubbingLimits.from_settings(settings),
                tts_client=tts,
                audio_processor=FakeAudioProcessor(),
            )
            accepted = manager.create(two_clip_request())
            await manager.wait(accepted.job_id)

        self.assertEqual(tts.max_active_calls, 1)

    async def test_completes_job_with_one_wav_per_sentence_and_captions_per_display_row(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = make_manager(
                root=Path(directory),
                tts=FakeTTS({10: 0.8, 11: 1.0}),
            )
            accepted = manager.create(two_clip_request())
            await manager.wait(accepted.job_id)
            snapshot = manager.get(accepted.job_id)

        self.assertEqual(snapshot.status, DubbingJobStatus.COMPLETED)
        self.assertEqual([clip.id for clip in snapshot.result.clips], [1])
        self.assertEqual(len(snapshot.result.captions), 2)
        self.assertIn("00:00:", snapshot.result.srt)
        self.assertEqual(
            snapshot.result.clips[0].audio_url,
            f"/generated/{accepted.job_id}/clips/1.wav",
        )
        self.assertTrue(snapshot.result.clips[0].audio_url.endswith("/clips/1.wav"))

    async def test_empty_cleaned_caption_creates_silence_without_tts(self):
        tts = FakeTTS({})
        with tempfile.TemporaryDirectory() as directory:
            manager = make_manager(root=Path(directory), tts=tts)
            accepted = manager.create(annotation_only_request())
            await manager.wait(accepted.job_id)
            snapshot = manager.get(accepted.job_id)
        self.assertEqual(tts.calls, [])
        self.assertEqual(snapshot.status, DubbingJobStatus.COMPLETED)
        self.assertGreater(snapshot.result.clips[0].duration, 0)

    async def test_failure_exposes_public_code_without_provider_body(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = make_manager(
                root=Path(directory),
                tts=FailingTTS(DubbingTTSGenerationError("SECRET provider body")),
            )
            accepted = manager.create(one_clip_request())
            await manager.wait(accepted.job_id)
            snapshot = manager.get(accepted.job_id)
        self.assertEqual(snapshot.status, DubbingJobStatus.FAILED)
        self.assertEqual(snapshot.error.code, "tts_generation_failed")
        self.assertNotIn("SECRET", snapshot.error.message)

    async def test_progress_moves_preparing_generating_fitting_completed(self):
        statuses: list[DubbingJobStatus] = []
        with tempfile.TemporaryDirectory() as directory:
            manager = make_manager(
                root=Path(directory),
                tts=FakeTTS({10: 0.5}),
                status_observer=lambda status: statuses.append(status),
            )
            accepted = manager.create(one_clip_request())
            await manager.wait(accepted.job_id)
        self.assertEqual(statuses, [
            DubbingJobStatus.PREPARING,
            DubbingJobStatus.GENERATING,
            DubbingJobStatus.FITTING,
            DubbingJobStatus.COMPLETED,
        ])


if __name__ == "__main__":
    unittest.main()
