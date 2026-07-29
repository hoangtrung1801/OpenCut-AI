import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

from app.models.dubbing import (
    AutoVoice,
    DubbingDisplaySegment,
    DubbingJobAccepted,
    DubbingJobCreateRequest,
    DubbingJobSnapshot,
    DubbingJobStatus,
    DubbingParentSegment,
)
from app.routes.dubbing import create_dubbing_job, get_dubbing_job
from app.services.dubbing_service import DubbingJobNotFound


def request() -> DubbingJobCreateRequest:
    return DubbingJobCreateRequest(
        source_language="en",
        target_language="vi",
        audio_segments=[
            DubbingParentSegment(
                id=1,
                source="Hello.",
                translation="Xin chào.",
                start=0,
                end=1,
            )
        ],
        display_segments=[
            DubbingDisplaySegment(
                id=10,
                parent_id=1,
                part_index=0,
                source="Hello.",
                translation="Xin chào.",
                start=0,
                end=1,
            )
        ],
        voice=AutoVoice(mode="auto"),
    )


class DubbingRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_returns_accepted_job(self):
        accepted = DubbingJobAccepted(job_id=uuid4(), status=DubbingJobStatus.QUEUED)
        with patch("app.routes.dubbing.job_manager.create", return_value=accepted) as create:
            result = await create_dubbing_job(request())
        self.assertEqual(result, accepted)
        create.assert_called_once()

    async def test_get_returns_snapshot(self):
        job_id = uuid4()
        snapshot = DubbingJobSnapshot(job_id=job_id, status=DubbingJobStatus.COMPLETED)
        with patch("app.routes.dubbing.job_manager.get", return_value=snapshot):
            result = await get_dubbing_job(job_id)
        self.assertEqual(result, snapshot)

    async def test_get_maps_missing_job_to_404(self):
        job_id = uuid4()
        with patch(
            "app.routes.dubbing.job_manager.get",
            side_effect=DubbingJobNotFound(str(job_id)),
        ):
            with self.assertRaises(HTTPException) as raised:
                await get_dubbing_job(job_id)
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
