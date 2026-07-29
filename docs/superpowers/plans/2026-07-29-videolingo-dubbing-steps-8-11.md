# VideoLingo Dubbing Steps 8–11 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate one timing-fitted WAV per translated display caption through the existing TTS service, reuse the Demucs background stem, and apply the result to the editor as one undoable dubbing action.

**Architecture:** The AI backend owns task construction, TTS orchestration, FFmpeg fitting, job progress, and local clip artifacts. The web preserves Whisper and translation metadata, polls the dubbing job, persists completed media, then applies source muting, background reuse, speech clips, and caption retiming through a single `TracksSnapshotCommand`.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, `httpx`, FFmpeg/ffprobe, `unittest`, TypeScript 5.8, React 19, Zustand, Bun test, EditorCore actions and commands.

## Global Constraints

- Work in the current workspace and preserve unrelated staged and unstaged changes.
- Do not use Docker.
- Do not run Demucs after transcription; reuse `separated_audio.background_url`.
- Do not clone the source vocal; use the explicit cloned, designed, or automatic voice selected in AI Dubbing.
- Return one WAV element per display caption.
- Never truncate spoken audio; ripple overflow and retime captions.
- Auto-mute only timeline elements whose `mediaId` matches the transcribed source media.
- Do not delete existing dubbing tracks or generated media.
- React components must use `useEditor()` and must invoke user operations through the actions system.
- Timeline changes must be reversible in one undo step.
- New production behavior must be introduced test-first.

---

## File Structure

### AI backend

- Create `services/ai-backend/app/models/dubbing.py` for API schemas, voice unions, job states, results, and runtime limits.
- Create `services/ai-backend/app/services/dubbing_planner.py` for deterministic parent/display validation and chunk construction.
- Create `services/ai-backend/app/services/dubbing_audio.py` for pure timing-fit calculations and FFmpeg/ffprobe execution.
- Create `services/ai-backend/app/services/dubbing_tts_client.py` for readiness checks, bounded retries, and WAV downloads from `tts-service`.
- Create `services/ai-backend/app/services/dubbing_service.py` for job state, concurrency, artifact directories, generation, fitting, and SRT output.
- Create `services/ai-backend/app/routes/dubbing.py` for job creation and polling.
- Modify `services/ai-backend/app/config.py` and `services/ai-backend/app/main.py` to configure and register dubbing.
- Modify `services/ai-backend/app/routes/tts.py` only to replace obsolete Docker instructions with local startup instructions.
- Add focused tests under `services/ai-backend/tests/test_dubbing_*.py`.

### Web

- Modify `apps/web/src/types/ai.ts` for dubbing API types and persisted translation display rows.
- Modify `apps/web/src/stores/transcript-store.ts` to retain Demucs URLs and `sourceMediaId`.
- Modify `apps/web/src/hooks/use-transcription.ts` and `apps/web/src/hooks/use-text-timeline-bridge.ts` to preserve the source identity and stems.
- Modify `apps/web/src/lib/transcription/translate-captions.ts` to store display and audio granularities together.
- Modify `apps/web/src/lib/ai-client.ts` for dubbing job creation, polling, and blob download.
- Create `apps/web/src/lib/dubbing/dubbing-workflow.ts` for pure orchestration with injected dependencies.
- Create `apps/web/src/lib/dubbing/timeline-state.ts` for a pure before-to-after timeline transformation.
- Modify `apps/web/src/lib/media/generated-audio.ts` to support persistence before insertion.
- Modify `apps/web/src/lib/actions/definitions.ts`, `apps/web/src/lib/actions/types.ts`, and `apps/web/src/hooks/actions/use-editor-actions.ts` for `generate-dubbing`.
- Rewrite `apps/web/src/hooks/use-ai-dubbing.ts` as voice/action/progress helpers without direct editor mutation.
- Modify `apps/web/src/components/editor/panels/assets/views/ai-dubbing.tsx` to select an explicit voice mode and invoke the action.
- Add focused Bun tests beside the corresponding web modules.

### Documentation

- Modify `docs/superpowers/videolingo-core-workflow.md` with the OpenCut steps 8–11 adaptation and local test commands.

---

### Task 1: Define strict backend dubbing contracts and limits

**Files:**

- Create: `services/ai-backend/app/models/dubbing.py`
- Modify: `services/ai-backend/app/config.py`
- Test: `services/ai-backend/tests/test_dubbing_models.py`

**Interfaces:**

- Produces: `DubbingParentSegment`, `DubbingDisplaySegment`,
  `DubbingJobCreateRequest`, `DubbingVoice`, `DubbingLimits`,
  `DubbingJobStatus`, `DubbingJobSnapshot`, `DubbingResult`, and
  `DubbingPublicError`.
- Consumes: no new project interface.

- [ ] **Step 1: Write failing model tests**

```python
# services/ai-backend/tests/test_dubbing_models.py
import unittest
from pydantic import ValidationError

from app.config import settings
from app.models.dubbing import DubbingJobCreateRequest, DubbingLimits


def request_payload(voice: dict) -> dict:
    return {
        "source_language": "en",
        "target_language": "vi",
        "audio_segments": [{
            "id": 10, "source": "Hello.", "translation": "Xin chào.",
            "start": 2.0, "end": 3.2,
        }],
        "display_segments": [{
            "id": 20, "parent_id": 10, "part_index": 0,
            "source": "Hello.", "translation": "Xin chào.",
            "start": 2.0, "end": 3.2,
        }],
        "voice": voice,
        "pace": 1.0,
    }


class DubbingModelsTest(unittest.TestCase):
    def test_accepts_explicit_clone_design_and_auto_modes(self):
        for voice in (
            {"mode": "clone", "speaker_wav": "generated/voices/alice.wav"},
            {"mode": "design", "speaker": "warm female narrator"},
            {"mode": "auto"},
        ):
            self.assertEqual(
                DubbingJobCreateRequest.model_validate(request_payload(voice)).voice.mode,
                voice["mode"],
            )

    def test_rejects_mixed_voice_fields_and_clone_path_traversal(self):
        invalid = (
            {"mode": "clone", "speaker_wav": "../../secret.wav"},
            {"mode": "design", "speaker": "warm", "speaker_wav": "generated/voices/a.wav"},
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
```

- [ ] **Step 2: Run the model test and verify RED**

Run:

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_dubbing_models -v
```

Expected: `ModuleNotFoundError: No module named 'app.models.dubbing'`.

- [ ] **Step 3: Implement schemas and settings**

Add these settings to `Settings`:

```python
DUBBING_MAX_CONCURRENT_JOBS: int = 1
DUBBING_MAX_TTS_CONCURRENCY: int = 2
DUBBING_MAX_CHUNK_SEGMENTS: int = 5
DUBBING_ACCEPT_SPEED: float = 1.2
DUBBING_MAX_SPEED: float = 1.4
DUBBING_GAP_TOLERANCE_SECONDS: float = 1.5
DUBBING_TTS_RETRIES: int = 2
```

Define a discriminated voice union and validated request:

```python
VoiceMode = Literal["clone", "design", "auto"]


class CloneVoice(BaseModel):
    mode: Literal["clone"]
    speaker_wav: str

    @field_validator("speaker_wav")
    @classmethod
    def validate_clone_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or ".." in path.parts
            or path.parts[:2] != ("generated", "voices")
            or path.suffix.lower() not in {".wav", ".mp3", ".flac", ".ogg"}
        ):
            raise ValueError("clone path must be a saved local voice")
        return path.as_posix()


class DesignVoice(BaseModel):
    mode: Literal["design"]
    speaker: str = Field(..., min_length=1, max_length=500)


class AutoVoice(BaseModel):
    mode: Literal["auto"]


DubbingVoice = Annotated[
    CloneVoice | DesignVoice | AutoVoice,
    Field(discriminator="mode"),
]
```

`DubbingJobCreateRequest` must validate unique IDs, distinct languages,
ordered non-overlapping parents, parent membership, contiguous part indices,
and finite positive ranges. `DubbingLimits.from_settings()` must validate all
positive values and `accept_speed <= max_speed`.

- [ ] **Step 4: Run the model test and full current backend suite**

Run:

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_dubbing_models -v
.venv/bin/python -m unittest discover -s tests -q
```

Expected: the new model tests and the existing suite pass.

- [ ] **Step 5: Commit only Task 1 files**

```bash
git add services/ai-backend/app/models/dubbing.py services/ai-backend/app/config.py services/ai-backend/tests/test_dubbing_models.py
git commit --only -m "feat: define dubbing job contracts" -- services/ai-backend/app/models/dubbing.py services/ai-backend/app/config.py services/ai-backend/tests/test_dubbing_models.py
```

---

### Task 2: Build VideoLingo-style dubbing tasks and chunks

**Files:**

- Create: `services/ai-backend/app/services/dubbing_planner.py`
- Test: `services/ai-backend/tests/test_dubbing_planner.py`

**Interfaces:**

- Consumes: `DubbingJobCreateRequest`, `DubbingLimits`.
- Produces: `DubbingClipTask`, `DubbingParentTask`, `DubbingChunk`, `DubbingPlan`, and `build_dubbing_plan(request, limits)`.

- [ ] **Step 1: Write failing planner tests**

```python
# services/ai-backend/tests/test_dubbing_planner.py
import unittest

from app.models.dubbing import DubbingJobCreateRequest, DubbingLimits
from app.services.dubbing_planner import build_dubbing_plan


class DubbingPlannerTest(unittest.TestCase):
    def test_keeps_every_display_caption_as_a_distinct_clip(self):
        request = make_request(
            parents=[parent(1, 0.0, 2.0)],
            displays=[
                display(10, 1, 0, "First.", 0.0, 1.0),
                display(11, 1, 1, "Second.", 1.0, 2.0),
            ],
        )
        plan = build_dubbing_plan(request, limits())
        self.assertEqual([clip.id for clip in plan.clips], [10, 11])
        self.assertEqual([clip.tts_text for clip in plan.clips], ["First.", "Second."])

    def test_ends_chunks_at_large_gaps_and_five_parents(self):
        request = make_six_parent_request(gap_after_third=2.0)
        plan = build_dubbing_plan(
            request,
            limits(max_chunk_segments=5, gap_tolerance_seconds=1.5),
        )
        self.assertEqual([[p.id for p in chunk.parents] for chunk in plan.chunks], [[1, 2, 3], [4, 5, 6]])

    def test_removes_parenthetical_annotations_only_from_tts_text(self):
        request = make_request(
            parents=[parent(1, 0.0, 1.0)],
            displays=[display(10, 1, 0, "Hello (laughs)", 0.0, 1.0)],
        )
        clip = build_dubbing_plan(request, limits()).clips[0]
        self.assertEqual(clip.caption_text, "Hello (laughs)")
        self.assertEqual(clip.tts_text, "Hello")
```

The test module must include concrete `parent`, `display`, `make_request`, and
`limits` helpers returning real Pydantic models, not mocks.

- [ ] **Step 2: Run the planner test and verify RED**

Run:

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_dubbing_planner -v
```

Expected: import failure for `app.services.dubbing_planner`.

- [ ] **Step 3: Implement the immutable planning types and builder**

```python
@dataclass(frozen=True)
class DubbingClipTask:
    id: int
    parent_id: int
    part_index: int
    caption_text: str
    tts_text: str
    original_start: float
    original_end: float


@dataclass(frozen=True)
class DubbingParentTask:
    id: int
    start: float
    end: float
    following_gap: float
    clips: tuple[DubbingClipTask, ...]


@dataclass(frozen=True)
class DubbingChunk:
    parents: tuple[DubbingParentTask, ...]
    clips: tuple[DubbingClipTask, ...]
    start: float
    allowed_end: float


@dataclass(frozen=True)
class DubbingPlan:
    parents: tuple[DubbingParentTask, ...]
    clips: tuple[DubbingClipTask, ...]
    chunks: tuple[DubbingChunk, ...]


def _clip_task(display: DubbingDisplaySegment) -> DubbingClipTask:
    cleaned = re.sub(
        r"\([^)]*\)|（[^）]*）",
        "",
        display.translation,
    )
    cleaned = "".join(
        character for character in cleaned
        if character in "\n\t" or ord(character) >= 32
    ).replace("-", "").strip()
    return DubbingClipTask(
        id=display.id,
        parent_id=display.parent_id,
        part_index=display.part_index,
        caption_text=display.translation,
        tts_text=cleaned,
        original_start=display.start,
        original_end=display.end,
    )


def build_dubbing_plan(
    request: DubbingJobCreateRequest,
    limits: DubbingLimits,
) -> DubbingPlan:
    displays_by_parent: dict[int, list[DubbingDisplaySegment]] = {}
    for display in request.display_segments:
        displays_by_parent.setdefault(display.parent_id, []).append(display)

    parents: list[DubbingParentTask] = []
    all_clips: list[DubbingClipTask] = []
    for index, segment in enumerate(request.audio_segments):
        following_gap = (
            request.audio_segments[index + 1].start - segment.end
            if index + 1 < len(request.audio_segments)
            else 0.0
        )
        clips = tuple(
            _clip_task(display)
            for display in sorted(
                displays_by_parent[segment.id],
                key=lambda item: item.part_index,
            )
        )
        parents.append(
            DubbingParentTask(
                id=segment.id,
                start=segment.start,
                end=segment.end,
                following_gap=max(0.0, following_gap),
                clips=clips,
            )
        )
        all_clips.extend(clips)

    chunks: list[DubbingChunk] = []
    pending: list[DubbingParentTask] = []
    for parent in parents:
        pending.append(parent)
        boundary = (
            parent.following_gap >= limits.gap_tolerance_seconds
            or len(pending) >= limits.max_chunk_segments
            or parent is parents[-1]
        )
        if boundary:
            tail = min(
                pending[-1].following_gap,
                limits.gap_tolerance_seconds,
            )
            chunks.append(
                DubbingChunk(
                    parents=tuple(pending),
                    clips=tuple(
                        clip for pending_parent in pending
                        for clip in pending_parent.clips
                    ),
                    start=pending[0].start,
                    allowed_end=pending[-1].end + tail,
                )
            )
            pending = []
    return DubbingPlan(
        parents=tuple(parents),
        clips=tuple(all_clips),
        chunks=tuple(chunks),
    )
```

Use the VideoLingo cleaning expression
`r"\([^)]*\)|（[^）]*）"` plus control-character removal. A caption that becomes
empty after cleaning must remain in the plan with `tts_text=""`; Task 5 will
create a short silent WAV without calling TTS.

Set a chunk boundary when the following parent gap is at least
`limits.gap_tolerance_seconds` or the chunk reaches
`limits.max_chunk_segments`. Set `allowed_end` to the last parent end plus the
smaller of its following gap and the configured tolerance.

- [ ] **Step 4: Run planner and model tests**

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_dubbing_planner tests.test_dubbing_models -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit only Task 2 files**

```bash
git add services/ai-backend/app/services/dubbing_planner.py services/ai-backend/tests/test_dubbing_planner.py
git commit --only -m "feat: plan dubbing caption chunks" -- services/ai-backend/app/services/dubbing_planner.py services/ai-backend/tests/test_dubbing_planner.py
```

---

### Task 3: Calculate non-truncating clip placement and run FFmpeg safely

**Files:**

- Create: `services/ai-backend/app/services/dubbing_audio.py`
- Test: `services/ai-backend/tests/test_dubbing_audio.py`

**Interfaces:**

- Consumes: `DubbingChunk`, raw duration by clip ID, `DubbingLimits`.
- Produces: `ChunkFit`, `FittedClip`, `fit_chunk_timing(...)`, and `DubbingAudioProcessor`.

- [ ] **Step 1: Write failing pure fitting tests**

```python
# services/ai-backend/tests/test_dubbing_audio.py
import unittest

from app.services.dubbing_audio import fit_chunk_timing


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
```

Also test `atempo` command construction through an injected command runner and
`ffprobe` JSON parsing through an injected probe runner.

- [ ] **Step 2: Run the audio test and verify RED**

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_dubbing_audio -v
```

Expected: import failure for `app.services.dubbing_audio`.

- [ ] **Step 3: Implement the pure fitter and command adapter**

```python
@dataclass(frozen=True)
class FittedClip:
    id: int
    start: float
    end: float
    duration: float
    timing_warning: Literal["overflow"] | None


@dataclass(frozen=True)
class ChunkFit:
    speed: float
    keep_gaps: bool
    clips: tuple[FittedClip, ...]


def fit_chunk_timing(
    *,
    clip_windows: Sequence[tuple[int, float, float]],
    raw_durations: Mapping[int, float],
    allowed_end: float,
    accept_speed: float,
    max_speed: float,
) -> ChunkFit:
    ordered = sorted(clip_windows, key=lambda item: (item[1], item[0]))
    window_start = ordered[0][1]
    window_duration = allowed_end - window_start
    gaps = [
        max(0.0, ordered[index][1] - ordered[index - 1][2])
        for index in range(1, len(ordered))
    ]
    raw_total = sum(raw_durations[clip_id] for clip_id, _, _ in ordered)
    with_gaps = raw_total + sum(gaps)

    keep_gaps = with_gaps / max(window_duration, 0.001) <= accept_speed
    fitted_total = with_gaps if keep_gaps else raw_total
    speed = min(
        max_speed,
        max(1.0, fitted_total / max(window_duration, 0.001)),
    )

    cursor = window_start
    fitted: list[FittedClip] = []
    for index, (clip_id, original_start, _original_end) in enumerate(ordered):
        if keep_gaps:
            cursor = max(cursor, original_start)
        duration = raw_durations[clip_id] / speed
        end = cursor + duration
        fitted.append(
            FittedClip(
                id=clip_id,
                start=cursor,
                end=end,
                duration=duration,
                timing_warning="overflow" if end > allowed_end else None,
            )
        )
        cursor = end
    return ChunkFit(speed=round(speed, 6), keep_gaps=keep_gaps, clips=tuple(fitted))
```

Compute placement in this order:

1. Preserve non-negative original gaps at speed `<= accept_speed`.
2. Remove internal gaps at speed `<= accept_speed`.
3. Remove gaps and raise speed up to `max_speed`.
4. If still long, keep `max_speed`, place clips sequentially, and mark every
   clip ending after `allowed_end` as overflow.

`DubbingAudioProcessor.adjust_speed(source, destination, speed)` must invoke:

```python
[
    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
    "-i", str(source), "-filter:a", f"atempo={speed:.6f}",
    "-c:a", "pcm_s16le", str(destination),
]
```

Speeds stay within 1.0–1.4, so one `atempo` filter is sufficient.
`probe_duration(path)` must use `ffprobe` JSON and reject non-positive or
non-finite duration. `write_silence(path, duration=0.1)` must use Python's
standard `wave` module so empty TTS text needs no provider request.

- [ ] **Step 4: Run audio and planner tests**

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_dubbing_audio tests.test_dubbing_planner -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit only Task 3 files**

```bash
git add services/ai-backend/app/services/dubbing_audio.py services/ai-backend/tests/test_dubbing_audio.py
git commit --only -m "feat: fit dubbing clips without truncation" -- services/ai-backend/app/services/dubbing_audio.py services/ai-backend/tests/test_dubbing_audio.py
```

---

### Task 4: Add a reusable local TTS HTTP client

**Files:**

- Create: `services/ai-backend/app/services/dubbing_tts_client.py`
- Modify: `services/ai-backend/app/routes/tts.py`
- Test: `services/ai-backend/tests/test_dubbing_tts_client.py`

**Interfaces:**

- Consumes: `settings.TTS_SERVICE_URL`, `DubbingVoice`, language, pace, text.
- Produces: `DubbingTTSClient.check_ready()` and `DubbingTTSClient.generate_to_file(...)`.

- [ ] **Step 1: Write failing client tests with an injected HTTP transport**

```python
# services/ai-backend/tests/test_dubbing_tts_client.py
import tempfile
import unittest
from pathlib import Path

import httpx

from app.models.dubbing import AutoVoice, CloneVoice, DesignVoice
from app.services.dubbing_tts_client import DubbingTTSClient, DubbingTTSUnavailable


class DubbingTTSClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_maps_each_explicit_voice_mode_to_existing_tts_json(self):
        seen = []

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, json={"model": {"installed": True, "loaded": True}})
            seen.append(request.read().decode())
            return httpx.Response(200, content=valid_wav_bytes(), headers={"content-type": "audio/wav"})

        client = make_client(handler)
        with tempfile.TemporaryDirectory() as directory:
            for index, voice in enumerate((
                CloneVoice(mode="clone", speaker_wav="generated/voices/alice.wav"),
                DesignVoice(mode="design", speaker="warm narrator"),
                AutoVoice(mode="auto"),
            )):
                await client.generate_to_file(
                    text="Hello", language="en", voice=voice, pace=1.0,
                    destination=Path(directory) / f"{index}.wav",
                )
        self.assertIn('"speaker_wav":"generated/voices/alice.wav"', seen[0])
        self.assertIn('"speaker":"warm narrator"', seen[1])
        self.assertNotIn("speaker_wav", seen[2])
        self.assertNotIn('"speaker"', seen[2])

    async def test_retries_transient_reads_but_not_readiness_failures(self):
        attempts = 0

        async def transient_handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            if request.url.path == "/health":
                return httpx.Response(
                    200,
                    json={"model": {"installed": True, "loaded": True}},
                )
            attempts += 1
            if attempts == 1:
                return httpx.Response(503, text="temporary")
            return httpx.Response(
                200,
                content=valid_wav_bytes(),
                headers={"content-type": "audio/wav"},
            )

        with tempfile.TemporaryDirectory() as directory:
            await make_client(transient_handler, retries=1).generate_to_file(
                text="Hello",
                language="en",
                voice=AutoVoice(mode="auto"),
                pace=1.0,
                destination=Path(directory) / "retry.wav",
            )
        self.assertEqual(attempts, 2)

        async def unavailable_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"model": {"installed": True, "loaded": False}},
            )

        with self.assertRaises(DubbingTTSUnavailable):
            await make_client(unavailable_handler).check_ready()
```

Implement `valid_wav_bytes()` with `io.BytesIO` and `wave`; do not use a real
TTS model.

- [ ] **Step 2: Run the client test and verify RED**

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_dubbing_tts_client -v
```

Expected: import failure for `app.services.dubbing_tts_client`.

- [ ] **Step 3: Implement readiness, mapping, retries, and atomic file write**

```python
class DubbingTTSClient:
    def __init__(
        self,
        *,
        base_url: str,
        retries: int,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.retries = retries
        self.client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=300)
        )

    async def check_ready(self) -> None:
        try:
            async with self.client_factory() as client:
                response = await client.get(f"{self.base_url}/health")
                response.raise_for_status()
                model = response.json().get("model", {})
        except (httpx.HTTPError, ValueError) as exc:
            raise DubbingTTSUnavailable("TTS service is unavailable.") from exc
        if not model.get("installed") or not model.get("loaded"):
            raise DubbingTTSUnavailable(
                "TTS model is not ready. Start local services and load the model."
            )

    async def generate_to_file(
        self,
        *,
        text: str,
        language: str,
        voice: DubbingVoice,
        pace: float,
        destination: Path,
    ) -> None:
        payload: dict[str, object] = {
            "text": text,
            "language": language,
            "speed": pace,
        }
        if voice.mode == "clone":
            payload["speaker_wav"] = voice.speaker_wav
        elif voice.mode == "design":
            payload["speaker"] = voice.speaker

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                async with self.client_factory() as client:
                    response = await client.post(
                        f"{self.base_url}/generate",
                        json=payload,
                    )
                if response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        "transient TTS failure",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                if "audio" not in response.headers.get("content-type", ""):
                    raise DubbingTTSGenerationError(
                        "TTS service returned a non-audio response."
                    )
                if not response.content:
                    raise DubbingTTSGenerationError(
                        "TTS service returned empty audio."
                    )
                partial = destination.with_suffix(".partial")
                partial.write_bytes(response.content)
                partial.replace(destination)
                return
            except DubbingTTSGenerationError:
                raise
            except (httpx.ConnectError, httpx.ReadError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt == self.retries:
                    break
                await asyncio.sleep(0.25 * (attempt + 1))
        raise DubbingTTSGenerationError(
            "TTS generation failed after retries."
        ) from last_error
```

Write to `destination.with_suffix(".partial")`, validate an audio content type
and non-empty bytes, then replace the final path. Retry only connect, read, and
5xx failures, for the configured number of additional attempts.

Update `routes/tts.py` messages to tell users to run:

```text
./scripts/start-local-services.sh
```

Remove Docker build/restart guidance from those public errors.

- [ ] **Step 4: Run client tests and existing TTS-service adapter tests**

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_dubbing_tts_client -v
cd ../tts-service
.venv/bin/python -m unittest tests.test_omnivoice_adapter -v
```

Expected: all tests pass without loading OmniVoice.

- [ ] **Step 5: Commit only Task 4 files**

```bash
git add services/ai-backend/app/services/dubbing_tts_client.py services/ai-backend/app/routes/tts.py services/ai-backend/tests/test_dubbing_tts_client.py
git commit --only -m "feat: add local dubbing TTS client" -- services/ai-backend/app/services/dubbing_tts_client.py services/ai-backend/app/routes/tts.py services/ai-backend/tests/test_dubbing_tts_client.py
```

---

### Task 5: Orchestrate queued dubbing jobs and local clip artifacts

**Files:**

- Create: `services/ai-backend/app/services/dubbing_service.py`
- Test: `services/ai-backend/tests/test_dubbing_service.py`

**Interfaces:**

- Consumes: planner, TTS client, audio processor, `DubbingLimits`, generated root.
- Produces: `DubbingJobManager.create(request)`, `get(job_id)`, and `run(job_id)`.

- [ ] **Step 1: Write failing service tests with fake TTS and audio adapters**

```python
# services/ai-backend/tests/test_dubbing_service.py
import tempfile
import unittest
from pathlib import Path

from app.models.dubbing import DubbingJobStatus
from app.services.dubbing_service import DubbingJobManager


class DubbingJobManagerTest(unittest.IsolatedAsyncioTestCase):
    async def test_completes_job_with_one_wav_and_caption_per_display_row(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = make_manager(
                root=Path(directory),
                tts=FakeTTS({10: 0.8, 11: 1.0}),
                audio=FakeAudioProcessor(),
            )
            accepted = manager.create(two_clip_request())
            await manager.wait(accepted.job_id)
            snapshot = manager.get(accepted.job_id)

        self.assertEqual(snapshot.status, DubbingJobStatus.COMPLETED)
        self.assertEqual([clip.id for clip in snapshot.result.clips], [10, 11])
        self.assertEqual(len(snapshot.result.captions), 2)
        self.assertIn("00:00:", snapshot.result.srt)

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
                tts=FailingTTS(RuntimeError("SECRET provider body")),
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
```

Fakes must write valid small WAVs so the service exercises real artifact and
result construction.

- [ ] **Step 2: Run the service test and verify RED**

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_dubbing_service -v
```

Expected: import failure for `app.services.dubbing_service`.

- [ ] **Step 3: Implement the job manager**

```python
class DubbingJobManager:
    def create(self, request: DubbingJobCreateRequest) -> DubbingJobAccepted:
        job_id = uuid.uuid4()
        self._jobs[job_id] = _MutableJob(request=request)
        self._tasks[job_id] = asyncio.create_task(self.run(job_id))
        return DubbingJobAccepted(job_id=job_id, status=DubbingJobStatus.QUEUED)

    def get(self, job_id: UUID) -> DubbingJobSnapshot:
        try:
            return self._jobs[job_id].snapshot()
        except KeyError as exc:
            raise DubbingJobNotFound(str(job_id)) from exc

    async def wait(self, job_id: UUID) -> None:
        try:
            task = self._tasks[job_id]
        except KeyError as exc:
            raise DubbingJobNotFound(str(job_id)) from exc
        await task

    async def run(self, job_id: UUID) -> None:
        async with self._job_semaphore:
            job = self._jobs[job_id]
            try:
                self._set_status(job, DubbingJobStatus.PREPARING)
                plan = build_dubbing_plan(job.request, self.limits)
                job_dir = self.generated_root / str(job_id)
                raw_paths = await self._generate_raw_clips(job, plan, job_dir)
                self._set_status(job, DubbingJobStatus.FITTING)
                result = await self._fit_and_publish(
                    job_id=job_id,
                    job=job,
                    plan=plan,
                    raw_paths=raw_paths,
                    job_dir=job_dir,
                )
                job.result = result
                self._set_status(job, DubbingJobStatus.COMPLETED)
            except Exception as exc:
                logger.warning(
                    "Dubbing job %s failed: %s",
                    job_id,
                    type(exc).__name__,
                )
                job.error = self._public_error(exc)
                self._set_status(job, DubbingJobStatus.FAILED)
```

Use a per-job semaphore for TTS calls, store raw clips under `raw/`, final clips
under `clips/`, and expose only final relative URLs. Update progress under an
`asyncio.Lock`. Generate raw silence for `tts_text == ""`. Fit chunks in
deterministic order and build SRT from fitted caption positions.

Implement the referenced private methods with these exact responsibilities:

- `_set_status(job, status)` updates the mutable job, notifies the optional
  observer, and never exposes request text.
- `_generate_raw_clips(job, plan, job_dir)` checks readiness once, switches the
  job to `GENERATING`, uses a per-job semaphore, writes one valid raw WAV per
  clip, and updates completed/total counts.
- `_fit_and_publish(...)` probes raw durations, calls `fit_chunk_timing`, writes
  every adjusted WAV under `clips/`, probes final durations, and returns
  `DubbingResult` with clips, captions, and SRT in display order.
- `_public_error(exc)` uses exception classes only to select the stable public
  code/message.

Catch internal exceptions once at the job boundary, log only job ID and
exception class, and map them to stable public codes:

```python
"tts_unavailable"
"tts_generation_failed"
"invalid_audio"
"audio_tool_failed"
"dubbing_failed"
```

- [ ] **Step 4: Run all new backend service tests**

```bash
cd services/ai-backend
.venv/bin/python -m unittest \
  tests.test_dubbing_service \
  tests.test_dubbing_tts_client \
  tests.test_dubbing_audio \
  tests.test_dubbing_planner \
  tests.test_dubbing_models -v
```

Expected: all pass.

- [ ] **Step 5: Commit only Task 5 files**

```bash
git add services/ai-backend/app/services/dubbing_service.py services/ai-backend/tests/test_dubbing_service.py
git commit --only -m "feat: orchestrate local dubbing jobs" -- services/ai-backend/app/services/dubbing_service.py services/ai-backend/tests/test_dubbing_service.py
```

---

### Task 6: Expose create and polling routes

**Files:**

- Create: `services/ai-backend/app/routes/dubbing.py`
- Modify: `services/ai-backend/app/main.py`
- Test: `services/ai-backend/tests/test_dubbing_routes.py`

**Interfaces:**

- Consumes: module-level `dubbing_job_manager`.
- Produces: `POST /api/dubbing/jobs`, `GET /api/dubbing/jobs/{job_id}`.

- [ ] **Step 1: Write failing route tests**

```python
# services/ai-backend/tests/test_dubbing_routes.py
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

from app.routes import dubbing


class DubbingRoutesTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_returns_accepted_snapshot(self):
        request = valid_request_model()
        accepted = accepted_model(uuid4())
        with patch.object(dubbing.dubbing_job_manager, "create", return_value=accepted):
            self.assertEqual(await dubbing.create_dubbing_job(request), accepted)

    async def test_poll_rejects_invalid_and_missing_job_ids(self):
        with self.assertRaises(HTTPException) as invalid:
            await dubbing.get_dubbing_job("not-a-uuid")
        self.assertEqual(invalid.exception.status_code, 422)
        missing_id = uuid4()
        with patch.object(
            dubbing.dubbing_job_manager,
            "get",
            side_effect=DubbingJobNotFound(str(missing_id)),
        ):
            with self.assertRaises(HTTPException) as missing:
                await dubbing.get_dubbing_job(str(missing_id))
        self.assertEqual(missing.exception.status_code, 404)

    async def test_poll_returns_sanitized_failed_snapshot(self):
        failed = failed_snapshot(
            job_id=uuid4(),
            code="tts_generation_failed",
            message="TTS generation failed after retries.",
        )
        with patch.object(
            dubbing.dubbing_job_manager,
            "get",
            return_value=failed,
        ):
            result = await dubbing.get_dubbing_job(str(failed.job_id))
        self.assertEqual(result.error.code, "tts_generation_failed")
        self.assertNotIn("provider", result.error.message.lower())
```

- [ ] **Step 2: Run route tests and verify RED**

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_dubbing_routes -v
```

Expected: import failure for `app.routes.dubbing`.

- [ ] **Step 3: Implement and register the router**

```python
router = APIRouter(prefix="/api/dubbing", tags=["dubbing"])


@router.post("/jobs", response_model=DubbingJobAccepted, status_code=202)
async def create_dubbing_job(
    request: DubbingJobCreateRequest,
) -> DubbingJobAccepted:
    return dubbing_job_manager.create(request)


@router.get("/jobs/{job_id}", response_model=DubbingJobSnapshot)
async def get_dubbing_job(job_id: str) -> DubbingJobSnapshot:
    try:
        parsed = UUID(job_id)
        if str(parsed) != job_id:
            raise ValueError
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid dubbing job id.") from exc
    try:
        return dubbing_job_manager.get(parsed)
    except DubbingJobNotFound as exc:
        raise HTTPException(status_code=404, detail="Dubbing job not found.") from exc
```

Parse canonical UUID spelling, return 422 for malformed IDs and 404 when the
registry does not contain the job. Register `dubbing.router` in `main.py`.

- [ ] **Step 4: Run route tests, compile, and full backend suite**

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_dubbing_routes -v
.venv/bin/python -m compileall -q app
.venv/bin/python -m unittest discover -s tests -q
```

Expected: all tests pass and compilation is silent.

- [ ] **Step 5: Commit only Task 6 files**

```bash
git add services/ai-backend/app/routes/dubbing.py services/ai-backend/app/main.py services/ai-backend/tests/test_dubbing_routes.py
git commit --only -m "feat: expose dubbing job API" -- services/ai-backend/app/routes/dubbing.py services/ai-backend/app/main.py services/ai-backend/tests/test_dubbing_routes.py
```

---

### Task 7: Add web dubbing API types and client methods

**Files:**

- Modify: `apps/web/src/types/ai.ts`
- Modify: `apps/web/src/lib/ai-client.ts`
- Test: `apps/web/src/lib/__tests__/ai-client-dubbing.test.ts`

**Interfaces:**

- Produces: `DubbingVoice`, `DubbingJobRequest`, `DubbingJobAccepted`,
  `DubbingJobSnapshot`, `aiClient.createDubbingJob`, `getDubbingJob`, and
  `downloadLocalAudioBlob`.
- Consumes: backend routes from Task 6.

- [ ] **Step 1: Write failing request mapping and polling tests**

```typescript
// apps/web/src/lib/__tests__/ai-client-dubbing.test.ts
import { describe, expect, test } from "bun:test";
import {
	buildDubbingJobRequestBody,
	type DubbingJobRequest,
} from "@/lib/ai-client";

describe("buildDubbingJobRequestBody", () => {
	test("preserves explicit clone, design, and auto voice modes", () => {
		const base = requestFixture();
		expect(buildDubbingJobRequestBody({
			...base,
			voice: { mode: "clone", speakerWav: "generated/voices/alice.wav" },
		}).voice).toEqual({
			mode: "clone",
			speaker_wav: "generated/voices/alice.wav",
		});
		expect(buildDubbingJobRequestBody({
			...base,
			voice: { mode: "design", speaker: "warm narrator" },
		}).voice).toEqual({ mode: "design", speaker: "warm narrator" });
		expect(buildDubbingJobRequestBody({
			...base,
			voice: { mode: "auto" },
		}).voice).toEqual({ mode: "auto" });
	});
});
```

Also test snake-case segment mapping and use a temporary local `fetch` stub to
verify `POST /api/dubbing/jobs`, `GET /api/dubbing/jobs/:id`, and binary
download error handling.

- [ ] **Step 2: Run the client test and verify RED**

```bash
bun test apps/web/src/lib/__tests__/ai-client-dubbing.test.ts
```

Expected: missing exports and methods.

- [ ] **Step 3: Implement types and client methods**

```typescript
export type DubbingVoice =
	| { mode: "clone"; speakerWav: string }
	| { mode: "design"; speaker: string }
	| { mode: "auto" };

export interface DubbingJobRequest {
	sourceLanguage: string;
	targetLanguage: string;
	audioSegments: ContextualTranslatedSegment[];
	displaySegments: DisplayCaptionSegment[];
	voice: DubbingVoice;
	pace: number;
}

export type DubbingJobStatus =
	| "queued"
	| "preparing"
	| "generating"
	| "fitting"
	| "completed"
	| "failed";
```

Add:

```typescript
async createDubbingJob(request: DubbingJobRequest): Promise<DubbingJobAccepted>
async getDubbingJob(jobId: string): Promise<DubbingJobSnapshot>
async downloadLocalAudioBlob(path: string): Promise<Blob>
```

The blob method must accept only same-origin relative paths beginning with
`/generated/dubbing/` or `/api/transcribe/artifacts/`.

- [ ] **Step 4: Run client and existing translation client tests**

```bash
bun test \
  apps/web/src/lib/__tests__/ai-client-dubbing.test.ts \
  apps/web/src/lib/__tests__/ai-client-translation.test.ts
```

Expected: both pass.

- [ ] **Step 5: Commit only Task 7 files**

```bash
git add apps/web/src/types/ai.ts apps/web/src/lib/ai-client.ts apps/web/src/lib/__tests__/ai-client-dubbing.test.ts
git commit --only -m "feat: add web dubbing job client" -- apps/web/src/types/ai.ts apps/web/src/lib/ai-client.ts apps/web/src/lib/__tests__/ai-client-dubbing.test.ts
```

---

### Task 8: Preserve Demucs and translation data in web state

**Files:**

- Modify: `apps/web/src/stores/transcript-store.ts`
- Modify: `apps/web/src/hooks/use-transcription.ts`
- Modify: `apps/web/src/hooks/use-text-timeline-bridge.ts`
- Modify: `apps/web/src/lib/transcription/translate-captions.ts`
- Test: `apps/web/src/stores/__tests__/transcript-store-dubbing.test.ts`
- Test: `apps/web/src/lib/transcription/__tests__/translate-captions.test.ts`

**Interfaces:**

- Produces: `separatedAudio`, `sourceMediaId`, and stored
  `TranslatedTranscript.displaySegments`.
- Consumes: Whisper `TranscriptionResult.separated_audio`.

- [ ] **Step 1: Write failing state and translation persistence tests**

```typescript
// apps/web/src/stores/__tests__/transcript-store-dubbing.test.ts
import { beforeEach, describe, expect, test } from "bun:test";
import { useTranscriptStore } from "@/stores/transcript-store";

describe("transcript dubbing metadata", () => {
	beforeEach(() => useTranscriptStore.getState().reset());

	test("stores source media identity and separated Demucs URLs together", () => {
		useTranscriptStore.getState().setTranscriptionSource({
			sourceMediaId: "media-1",
			duration: 12.5,
			separatedAudio: {
				vocals_url: "/api/transcribe/artifacts/id/vocals",
				background_url: "/api/transcribe/artifacts/id/background",
			},
		});
		expect(useTranscriptStore.getState()).toMatchObject({
			sourceMediaId: "media-1",
			duration: 12.5,
			separatedAudio: {
				background_url: "/api/transcribe/artifacts/id/background",
			},
		});
	});
});
```

Extend `translate-captions.test.ts` to assert that `storeTranslation` receives
the exact `contextualResult.display_segments` in addition to its audio
segments.

- [ ] **Step 2: Run the state tests and verify RED**

```bash
bun test \
  apps/web/src/stores/__tests__/transcript-store-dubbing.test.ts \
  apps/web/src/lib/transcription/__tests__/translate-captions.test.ts
```

Expected: missing store action/fields and missing display segment persistence.

- [ ] **Step 3: Implement state preservation**

Extend `TranslatedTranscript`:

```typescript
export interface TranslatedTranscript {
	languageCode: string;
	languageName: string;
	segments: TranscriptionSegment[];
	displaySegments?: DisplayCaptionSegment[];
}
```

Extend transcript state:

```typescript
separatedAudio: SeparatedAudio | null;
sourceMediaId: string | null;
setTranscriptionSource(input: {
	separatedAudio: SeparatedAudio | null;
	sourceMediaId: string;
	duration: number;
}): void;
```

Change `transcribeVideo` to accept `sourceMediaId` and call
`setTranscriptionSource` only after successful transcription:

```typescript
async (file: File, sourceMediaId: string, language?: string) => {
	const result = await aiClient.transcribe(file, language);
	setSegments(result.segments);
	setLanguage(result.language);
	setTranscriptionSource({
		sourceMediaId,
		duration: result.duration,
		separatedAudio: result.separated_audio ?? null,
	});
	return result;
}
```

Pass `foundMediaId` from `use-text-timeline-bridge.ts`. Update
`transcriptTranslation(...)` to receive and preserve display segments.

- [ ] **Step 4: Run the focused transcription and translation tests**

```bash
bun test \
  apps/web/src/stores/__tests__/transcript-store-dubbing.test.ts \
  apps/web/src/lib/transcription/__tests__/translate-captions.test.ts \
  apps/web/src/lib/transcription/__tests__/translation-control.test.ts
```

Expected: all pass.

- [ ] **Step 5: Commit only Task 8 files**

```bash
git add apps/web/src/stores/transcript-store.ts apps/web/src/hooks/use-transcription.ts apps/web/src/hooks/use-text-timeline-bridge.ts apps/web/src/lib/transcription/translate-captions.ts apps/web/src/stores/__tests__/transcript-store-dubbing.test.ts apps/web/src/lib/transcription/__tests__/translate-captions.test.ts
git commit --only -m "feat: preserve dubbing source metadata" -- apps/web/src/stores/transcript-store.ts apps/web/src/hooks/use-transcription.ts apps/web/src/hooks/use-text-timeline-bridge.ts apps/web/src/lib/transcription/translate-captions.ts apps/web/src/stores/__tests__/transcript-store-dubbing.test.ts apps/web/src/lib/transcription/__tests__/translate-captions.test.ts
```

---

### Task 9: Build a no-partial-mutation dubbing workflow and timeline snapshot

**Files:**

- Create: `apps/web/src/lib/dubbing/dubbing-workflow.ts`
- Create: `apps/web/src/lib/dubbing/timeline-state.ts`
- Modify: `apps/web/src/lib/media/generated-audio.ts`
- Test: `apps/web/src/lib/dubbing/__tests__/dubbing-workflow.test.ts`
- Test: `apps/web/src/lib/dubbing/__tests__/timeline-state.test.ts`
- Modify: `apps/web/src/lib/media/__tests__/generated-audio.test.ts`

**Interfaces:**

- Consumes: transcript/translation snapshots, dubbing client, media persistence,
  current tracks, and returned clips.
- Produces: `runDubbingWorkflow(args, deps)`, `buildDubbingTimelineState(input)`,
  and `persistGeneratedAudioAsset(...)`.

- [ ] **Step 1: Write failing pure workflow tests**

```typescript
// apps/web/src/lib/dubbing/__tests__/dubbing-workflow.test.ts
import { describe, expect, mock, test } from "bun:test";
import { runDubbingWorkflow } from "@/lib/dubbing/dubbing-workflow";

describe("runDubbingWorkflow", () => {
	test("waits for all downloads and persistence before applying the timeline", async () => {
		const calls: string[] = [];
		await runDubbingWorkflow(argsFixture(), dependencies({
			createJob: async () => queuedJob("job-1"),
			getJob: async () => completedJobFixture(),
			downloadBlob: async (url) => {
				calls.push(`download:${url}`);
				return new Blob(["audio"], { type: "audio/wav" });
			},
			persistAudio: async (input) => {
				calls.push(`persist:${input.name}`);
				return `media-${calls.length}`;
			},
			applyTimeline: () => calls.push("apply"),
			wait: async () => {},
		})); 
		expect(calls.at(-1)).toBe("apply");
	});

	test("does not persist or apply when the job fails", async () => {
		const persistAudio = mock(async () => "media");
		const applyTimeline = mock(() => {});
		await expect(runDubbingWorkflow(
			argsFixture(),
			dependencies({
				getJob: async () => failedJob("tts_unavailable"),
				persistAudio,
				applyTimeline,
			}),
		)).rejects.toThrow("TTS");
		expect(persistAudio).not.toHaveBeenCalled();
		expect(applyTimeline).not.toHaveBeenCalled();
	});
});
```

Write timeline tests that construct real `TimelineTrack` fixtures and assert:

- only elements with the source `mediaId` become muted;
- unrelated uploaded music remains unmuted;
- background is inserted once and reused on a second run;
- every returned clip becomes one audio element on a new track;
- target caption elements are retimed in stable order; and
- the input tracks are not mutated.

Extend generated-audio tests to prove media can be persisted without inserting
an element.

- [ ] **Step 2: Run the workflow tests and verify RED**

```bash
bun test \
  apps/web/src/lib/dubbing/__tests__/dubbing-workflow.test.ts \
  apps/web/src/lib/dubbing/__tests__/timeline-state.test.ts \
  apps/web/src/lib/media/__tests__/generated-audio.test.ts
```

Expected: missing modules and persistence helper.

- [ ] **Step 3: Extract persistence from generated-audio**

```typescript
export async function persistGeneratedAudioAsset({
	editor,
	projectId,
	file,
	duration,
}: {
	editor: GeneratedAudioEditor;
	projectId: string;
	file: File;
	duration: number;
}): Promise<{ mediaId: string; url: string }> {
	const url = URL.createObjectURL(file);
	try {
		const mediaId = await editor.media.addMediaAsset({
			projectId,
			asset: {
				name: file.name,
				type: "audio",
				file,
				url,
				duration,
			},
		});
		if (!editor.media.getAssetById(mediaId)) {
			throw new Error("Failed to persist generated audio");
		}
		return { mediaId, url };
	} catch (error) {
		URL.revokeObjectURL(url);
		throw error;
	}
}
```

Refactor `insertGeneratedAudioElement` to call this helper before its existing
element insertion. Preserve its rollback behavior and current tests.

- [ ] **Step 4: Implement polling and pure timeline construction**

`runDubbingWorkflow` must:

1. validate source media, Demucs background, audio parents, display rows, and
   translated subtitle track;
2. create the job;
3. poll at an injected delay while updating the background task;
4. stop on `completed` or `failed`;
5. download the background only when no reusable media exists;
6. download every clip;
7. persist all required media; and
8. call `applyTimeline` exactly once.

Define:

```typescript
export function buildDubbingTimelineState(input: {
	before: TimelineTrack[];
	sourceMediaId: string;
	targetSubtitleTrackId: string;
	background: { mediaId: string; duration: number; artifactKey: string };
	clips: Array<{ mediaId: string; clip: DubbingClipResult }>;
	captions: DubbingCaptionResult[];
	targetLanguageName: string;
	createId?: () => string;
}): TimelineTrack[] {
	const createId = input.createId ?? generateUUID;
	const after = structuredClone(input.before);

	for (const track of after) {
		track.elements = track.elements.map((element) =>
			hasMediaId(element) && element.mediaId === input.sourceMediaId
				? { ...element, muted: true }
				: element,
		) as typeof track.elements;
	}

	const backgroundName = `Dubbing background ${input.background.artifactKey}`;
	const hasBackground = after.some((track) =>
		track.elements.some((element) => element.name === backgroundName),
	);
	if (!hasBackground) {
		const backgroundTrack = buildEmptyTrack({
			id: createId(),
			type: "audio",
		});
		backgroundTrack.name = "Dubbing background";
		backgroundTrack.elements.push({
			...buildUploadAudioElement({
				mediaId: input.background.mediaId,
				name: backgroundName,
				duration: input.background.duration,
				startTime: 0,
			}),
			id: createId(),
		});
		after.push(backgroundTrack);
	}

	const speechTrack = buildEmptyTrack({ id: createId(), type: "audio" });
	speechTrack.name = `Dubbed speech: ${input.targetLanguageName}`;
	speechTrack.elements = input.clips.map(({ mediaId, clip }) => ({
		...buildUploadAudioElement({
			mediaId,
			name: `Dub: ${clip.text}`,
			duration: clip.duration,
			startTime: clip.start,
		}),
		id: createId(),
	}));
	after.push(speechTrack);

	const captionTrack = after.find(
		(track) => track.id === input.targetSubtitleTrackId && track.type === "text",
	);
	if (!captionTrack || captionTrack.elements.length !== input.captions.length) {
		throw new Error("Translated caption track does not match dubbing captions.");
	}
	const captions = [...input.captions].sort((left, right) =>
		left.start - right.start || left.id - right.id
	);
	captionTrack.elements = [...captionTrack.elements]
		.sort((left, right) => left.startTime - right.startTime)
		.map((element, index) => ({
			...element,
			startTime: captions[index].start,
			duration: captions[index].end - captions[index].start,
		}));
	return after;
}
```

Identify reusable background elements by a stable element name containing the
artifact UUID parsed from the same-origin background URL. Build tracks and
elements with existing `buildEmptyTrack`, `buildUploadAudioElement`, and
caption element shapes. Sort subtitle elements by `startTime` before zipping
them with ordered returned captions; fail before mutation if counts differ.

- [ ] **Step 5: Run workflow, media, and timeline tests**

```bash
bun test \
  apps/web/src/lib/dubbing/__tests__/dubbing-workflow.test.ts \
  apps/web/src/lib/dubbing/__tests__/timeline-state.test.ts \
  apps/web/src/lib/media/__tests__/generated-audio.test.ts
```

Expected: all pass.

- [ ] **Step 6: Commit only Task 9 files**

```bash
git add apps/web/src/lib/dubbing/dubbing-workflow.ts apps/web/src/lib/dubbing/timeline-state.ts apps/web/src/lib/dubbing/__tests__/dubbing-workflow.test.ts apps/web/src/lib/dubbing/__tests__/timeline-state.test.ts apps/web/src/lib/media/generated-audio.ts apps/web/src/lib/media/__tests__/generated-audio.test.ts
git commit --only -m "feat: prepare undoable dubbing timeline state" -- apps/web/src/lib/dubbing/dubbing-workflow.ts apps/web/src/lib/dubbing/timeline-state.ts apps/web/src/lib/dubbing/__tests__/dubbing-workflow.test.ts apps/web/src/lib/dubbing/__tests__/timeline-state.test.ts apps/web/src/lib/media/generated-audio.ts apps/web/src/lib/media/__tests__/generated-audio.test.ts
```

---

### Task 10: Wire the editor action and explicit AI Dubbing voice modes

**Files:**

- Modify: `apps/web/src/lib/actions/definitions.ts`
- Modify: `apps/web/src/lib/actions/types.ts`
- Modify: `apps/web/src/hooks/actions/use-editor-actions.ts`
- Modify: `apps/web/src/hooks/use-ai-dubbing.ts`
- Modify: `apps/web/src/components/editor/panels/assets/views/ai-dubbing.tsx`
- Test: `apps/web/src/hooks/__tests__/use-ai-dubbing.test.ts`
- Test: `apps/web/src/lib/dubbing/__tests__/dubbing-action.test.ts`

**Interfaces:**

- Consumes: Task 9 workflow and current EditorCore/store APIs.
- Produces: `generate-dubbing` action and explicit panel arguments.

- [ ] **Step 1: Write failing voice/action tests**

```typescript
// apps/web/src/hooks/__tests__/use-ai-dubbing.test.ts
import { describe, expect, test } from "bun:test";
import { buildDubbingActionArgs } from "@/hooks/use-ai-dubbing";

describe("buildDubbingActionArgs", () => {
	test("builds explicit clone, design, and auto actions", () => {
		expect(buildDubbingActionArgs({
			targetLanguage: "vi",
			targetLanguageName: "Vietnamese",
			voiceMode: "clone",
			clonedVoicePath: "generated/voices/alice.wav",
			voiceDesign: "",
			pace: 1,
		}).voice).toEqual({
			mode: "clone",
			speakerWav: "generated/voices/alice.wav",
		});
		expect(buildDubbingActionArgs({
			targetLanguage: "vi",
			targetLanguageName: "Vietnamese",
			voiceMode: "design",
			voiceDesign: "warm narrator",
			pace: 1,
		}).voice).toEqual({ mode: "design", speaker: "warm narrator" });
		expect(buildDubbingActionArgs({
			targetLanguage: "vi",
			targetLanguageName: "Vietnamese",
			voiceMode: "auto",
			voiceDesign: "",
			pace: 1,
		}).voice).toEqual({ mode: "auto" });
	});
});
```

`dubbing-action.test.ts` must exercise an exported dependency builder or action
workflow wrapper and assert that the resulting timeline is executed through:

```typescript
editor.commands.execute({
	command: new TracksSnapshotCommand(before, after),
});
```

It must also assert that a missing target translation invokes the existing
translation workflow before job creation.

- [ ] **Step 2: Run action tests and verify RED**

```bash
bun test \
  apps/web/src/hooks/__tests__/use-ai-dubbing.test.ts \
  apps/web/src/lib/dubbing/__tests__/dubbing-action.test.ts
```

Expected: missing action builder and handler.

- [ ] **Step 3: Define and handle the action**

Add:

```typescript
"generate-dubbing": {
	description: "Generate fitted dubbed speech and add it to the timeline",
	category: "ai",
	args: {
		targetLanguage: "string",
		targetLanguageName: "string",
		voice: "DubbingVoice",
		pace: "number",
	},
},
```

Add the exact TypeScript action map:

```typescript
"generate-dubbing": {
	targetLanguage: string;
	targetLanguageName: string;
	voice: DubbingVoice;
	pace: number;
} | undefined;
```

In `use-editor-actions.ts`, register `useActionHandler("generate-dubbing", ...)`.
If the target translation is missing, call `translateAndAddCaptions`, then
re-read `useTranscriptStore.getState()`. Resolve the subtitle track by target
language. Pass dependencies to `runDubbingWorkflow`, persist media, build
`after`, then execute one `TracksSnapshotCommand`.

- [ ] **Step 4: Rewrite the panel to invoke the action**

Keep `useEditor()` in the component. Add a `voiceMode` select with Auto,
Voice design, and Cloned voice. Show or enable only the relevant existing input
or `VoiceLibraryPicker`.

The click handler must be:

```typescript
const handleDub = () => {
	const target = OMNIVOICE_LANGUAGES.find(
		(item) => item.code === targetLanguage,
	);
	if (!target) return;
	const args = buildDubbingActionArgs({
		targetLanguage,
		targetLanguageName: target.name,
		voiceMode,
		clonedVoicePath: clonedVoice?.path,
		voiceDesign,
		pace,
	});
	invokeAction("generate-dubbing", args, "mouseclick");
};
```

Remove direct translation, TTS, media, and timeline mutation from
`use-ai-dubbing.ts`. Keep that file as focused action argument and background
progress helpers so existing imports are migrated rather than deleted.

- [ ] **Step 5: Run focused web tests and type checking**

```bash
bun test \
  apps/web/src/hooks/__tests__/use-ai-dubbing.test.ts \
  apps/web/src/lib/dubbing/__tests__/dubbing-action.test.ts \
  apps/web/src/lib/dubbing/__tests__/dubbing-workflow.test.ts \
  apps/web/src/lib/dubbing/__tests__/timeline-state.test.ts \
  apps/web/src/lib/transcription/__tests__/translate-captions.test.ts
bunx tsc -p apps/web/tsconfig.json --noEmit
```

Expected: tests and TypeScript pass.

- [ ] **Step 6: Commit only Task 10 files**

```bash
git add apps/web/src/lib/actions/definitions.ts apps/web/src/lib/actions/types.ts apps/web/src/hooks/actions/use-editor-actions.ts apps/web/src/hooks/use-ai-dubbing.ts apps/web/src/components/editor/panels/assets/views/ai-dubbing.tsx apps/web/src/hooks/__tests__/use-ai-dubbing.test.ts apps/web/src/lib/dubbing/__tests__/dubbing-action.test.ts
git commit --only -m "feat: add AI dubbing editor action" -- apps/web/src/lib/actions/definitions.ts apps/web/src/lib/actions/types.ts apps/web/src/hooks/actions/use-editor-actions.ts apps/web/src/hooks/use-ai-dubbing.ts apps/web/src/components/editor/panels/assets/views/ai-dubbing.tsx apps/web/src/hooks/__tests__/use-ai-dubbing.test.ts apps/web/src/lib/dubbing/__tests__/dubbing-action.test.ts
```

---

### Task 11: Document, verify, and manually exercise the integrated workflow

**Files:**

- Modify: `docs/superpowers/videolingo-core-workflow.md`
- Test: all backend and web tests from earlier tasks.

**Interfaces:**

- Consumes: completed backend and web implementation.
- Produces: maintainer instructions and final verification evidence.

- [ ] **Step 1: Update the workflow documentation**

Add an “OpenCut AI steps 8–11 adaptation” section documenting:

- no Excel/SRT intermediate contract between steps 8–10;
- the dubbing job endpoints and states;
- explicit clone/design/auto selection;
- Demucs background reuse from step 2;
- non-truncating overflow behavior;
- individual clip and retimed caption output;
- one-step editor undo; and
- local, non-Docker startup:

```bash
./scripts/start-local-services.sh
./scripts/start-ai-backend.sh
./scripts/start-web.sh
```

- [ ] **Step 2: Run backend verification**

```bash
cd services/ai-backend
.venv/bin/python -m compileall -q app
.venv/bin/python -m unittest discover -s tests -q
```

Expected: compilation succeeds and the full suite reports `OK`.

- [ ] **Step 3: Run TTS adapter verification**

```bash
cd services/tts-service
.venv/bin/python -m unittest tests.test_omnivoice_adapter tests.test_torch_compatibility -v
```

Expected: adapter and dependency compatibility tests pass without model
generation.

- [ ] **Step 4: Run web verification**

```bash
cd /Users/hoangtrung1801/develpoment/0-playground/OpenCut-AI
bun test apps/web/src/lib/dubbing apps/web/src/hooks/__tests__/use-ai-dubbing.test.ts apps/web/src/lib/transcription apps/web/src/lib/media/__tests__/generated-audio.test.ts
bunx tsc -p apps/web/tsconfig.json --noEmit
bunx biome check \
  apps/web/src/lib/dubbing \
  apps/web/src/hooks/use-ai-dubbing.ts \
  apps/web/src/components/editor/panels/assets/views/ai-dubbing.tsx \
  apps/web/src/hooks/actions/use-editor-actions.ts
```

Expected: tests, type checking, and targeted formatting/lint checks pass.

- [ ] **Step 5: Run repository integrity checks**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors. Confirm every unrelated pre-existing dirty file
is still present and was not included in task commits.

- [ ] **Step 6: Perform a local smoke test without Docker**

Start the services in separate terminals:

```bash
./scripts/start-local-services.sh
./scripts/start-ai-backend.sh
./scripts/start-web.sh
```

In the editor:

1. Import a short video and transcribe it.
2. Confirm the transcript result contains vocal and background artifact URLs.
3. Translate and add captions.
4. Open AI Dubbing and run Auto voice.
5. Confirm the original media is muted, the background remains audible, every
   displayed caption has its own speech clip, and captions follow overflow.
6. Undo once and confirm the previous timeline state returns.
7. Repeat with Voice design and one saved cloned voice.

- [ ] **Step 7: Commit documentation only**

```bash
git add -f docs/superpowers/videolingo-core-workflow.md
git commit --only -m "docs: document OpenCut dubbing workflow" -- docs/superpowers/videolingo-core-workflow.md
```

---

## Plan Self-Review Checklist

- Every approved specification requirement is assigned to a task.
- Backend interfaces are introduced before their consumers.
- Web state is introduced before the workflow and action use it.
- Each production module starts with a focused failing test.
- Model, planner, timing, HTTP, orchestration, route, state, workflow, timeline,
  action, and UI behavior have independent review boundaries.
- No task requires Docker, a real LLM, a TTS model download, or a second Demucs
  run.
- Path-specific commits protect the existing dirty worktree.
- No task deletes existing user media or dubbing tracks.
