import unittest

from app.models.dubbing import (
    AutoVoice,
    DubbingDisplaySegment,
    DubbingJobCreateRequest,
    DubbingLimits,
    DubbingParentSegment,
)
from app.services.dubbing_planner import build_dubbing_plan


def parent(identifier: int, start: float, end: float) -> DubbingParentSegment:
    return DubbingParentSegment(
        id=identifier,
        source=f"Source {identifier}.",
        translation=f"Translation {identifier}.",
        start=start,
        end=end,
    )


def display(
    identifier: int,
    parent_id: int,
    part_index: int,
    text: str,
    start: float,
    end: float,
) -> DubbingDisplaySegment:
    return DubbingDisplaySegment(
        id=identifier,
        parent_id=parent_id,
        part_index=part_index,
        source=text,
        translation=text,
        start=start,
        end=end,
    )


def make_request(
    parents: list[DubbingParentSegment],
    displays: list[DubbingDisplaySegment],
) -> DubbingJobCreateRequest:
    return DubbingJobCreateRequest(
        source_language="en",
        target_language="vi",
        audio_segments=parents,
        display_segments=displays,
        voice=AutoVoice(mode="auto"),
    )


def limits(**overrides: object) -> DubbingLimits:
    values: dict[str, object] = {
        "max_concurrent_jobs": 1,
        "max_tts_concurrency": 2,
        "max_chunk_segments": 5,
        "accept_speed": 1.2,
        "max_speed": 1.4,
        "gap_tolerance_seconds": 1.5,
        "tts_retries": 2,
    }
    values.update(overrides)
    return DubbingLimits(**values)


class DubbingPlannerTest(unittest.TestCase):
    def test_groups_display_captions_into_one_tts_clip_per_parent_sentence(self):
        request = make_request(
            parents=[parent(1, 0.0, 2.0)],
            displays=[
                display(10, 1, 0, "First.", 0.0, 1.0),
                display(11, 1, 1, "Second.", 1.0, 2.0),
            ],
        )
        plan = build_dubbing_plan(request, limits())
        self.assertEqual([clip.id for clip in plan.clips], [1])
        self.assertEqual(
            [clip.tts_text for clip in plan.clips],
            ["Translation 1."],
        )

    def test_ends_chunks_at_large_gaps_and_five_parents(self):
        parents = [
            parent(index, float(index - 1) * 0.5, float(index - 1) * 0.5 + 0.4)
            for index in range(1, 7)
        ]
        parents[2] = parent(3, 1.0, 1.4)
        parents[3] = parent(4, 3.4, 3.8)
        parents[4] = parent(5, 3.9, 4.3)
        parents[5] = parent(6, 4.4, 4.8)
        displays = [
            display(index + 20, index, 0, f"Line {index}.", item.start, item.end)
            for index, item in enumerate(parents, start=1)
        ]
        request = make_request(parents, displays)
        plan = build_dubbing_plan(
            request,
            limits(max_chunk_segments=5, gap_tolerance_seconds=1.5),
        )
        self.assertEqual(
            [[item.id for item in chunk.parents] for chunk in plan.chunks],
            [[1, 2, 3], [4, 5, 6]],
        )

    def test_removes_parenthetical_annotations_only_from_tts_text(self):
        request = make_request(
            parents=[DubbingParentSegment(
                id=1,
                source="Hello (laughs)",
                translation="Hello (laughs)",
                start=0.0,
                end=1.0,
            )],
            displays=[display(10, 1, 0, "Hello (laughs)", 0.0, 1.0)],
        )
        clip = build_dubbing_plan(request, limits()).clips[0]
        self.assertEqual(clip.caption_text, "Hello (laughs)")
        self.assertEqual(clip.tts_text, "Hello")


if __name__ == "__main__":
    unittest.main()
