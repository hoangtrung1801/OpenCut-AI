# Caption Splitting and Subtitle Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert oversized translated captions into separately timed display elements and return aligned source, translated, and bilingual subtitle documents.

**Architecture:** The ai-backend extends the contextual translation contract with optional source word timings, runs a shared caption post-processor after contextual or Sarvam translation, and serializes final display cues in SRT and WebVTT. The web continues to invoke the existing `translate-captions` action, stores original-granularity translations, and builds the timeline track from final display segments.

**Tech Stack:** Python 3, FastAPI, Pydantic v2, asyncio, unittest, TypeScript, React, Zustand, Bun test.

## Global Constraints

- Follow `docs/superpowers/specs/2026-07-28-caption-splitting-subtitle-generation-design.md`.
- Default maximum caption length is exactly `32`.
- Target length multiplier defaults to exactly `1.0`.
- Split processing uses `3` normal passes and allows up to `8` adaptive passes.
- Positive gaps strictly smaller than `1.0` second may be closed.
- Contextual alignment uses the existing configured LLM backend with exactly `2` correction retries after the first attempt.
- Keep the existing `segments` response field backward compatible.
- Do not move translation or subtitle generation into whisper-service.
- Do not use Docker.
- Do not delete existing tracks, media, stems, artifacts, or unrelated workspace files.
- React components continue to use `useEditor()`.
- User-triggered translation continues through the existing `translate-captions` action and `invokeAction()`.
- Preserve all pre-existing staged and unstaged user changes.
- `apps/web/src/lib/ai-client.ts` already contains overlapping staged and unstaged changes. Edit it carefully, do not reset it, and do not include unrelated hunks in a commit.

---

## File Structure

### ai-backend

- `app/models/translation.py`: public request/response models and processing limits.
- `app/services/caption_splitter.py`: pure weighted-length, source splitting, timing allocation, and gap-closing logic.
- `app/services/caption_postprocessor.py`: LLM translation-part alignment and display/audio response construction.
- `app/services/subtitle_service.py`: SRT/WebVTT timestamp formatting and monolingual/bilingual document serialization.
- `app/services/contextual_translation.py`: existing contextual translation followed by shared caption post-processing.
- `app/routes/translation.py`: contextual and already-translated caption post-processing endpoints.
- `app/config.py`: caption processing defaults.
- `tests/test_caption_splitter.py`: pure splitting and timing behavior.
- `tests/test_caption_postprocessor.py`: LLM alignment, retries, and output granularity.
- `tests/test_subtitle_service.py`: document formatting.
- Existing contextual translation model/service/route tests: additive contract and endpoint integration.

### web

- `src/types/ai.ts`: enriched translation and post-processing API types.
- `src/lib/ai-client.ts`: contextual and post-processing requests.
- `src/lib/transcription/translate-captions.ts`: send words, post-process Sarvam results, and consume display segments.
- `src/hooks/actions/use-editor-actions.ts`: provide the post-processing dependency to the existing action workflow.
- Existing transcription tests: API contract, atomic workflow, and one-element-per-display-segment behavior.

---

### Task 1: Define caption-processing models and configuration

**Files:**

- Modify: `services/ai-backend/app/config.py`
- Modify: `services/ai-backend/app/models/translation.py`
- Modify: `services/ai-backend/tests/test_contextual_translation_models.py`

**Interfaces:**

- Produces: `TranslationWordInput`, `CaptionTranslationInput`, `DisplayCaptionSegment`, `SubtitleDocumentSet`, `CaptionPostProcessRequest`, `CaptionPostProcessResponse`.
- Extends: `TranslationSegmentInput.words`, `ContextualTranslationResponse.display_segments`, `.audio_segments`, and `.subtitles`.
- Extends: `ContextualTranslationLimits` with `max_caption_chars: int`, `target_length_multiplier: float`, `split_passes: int`, and `gap_close_seconds: float`.

- [ ] **Step 1: Write failing model and limit tests**

Add tests equivalent to:

```python
def test_accepts_optional_words_inside_parent_segment(self):
    request = ContextualTranslationRequest(
        source_language="vi",
        target_language="en",
        segments=[{
            "id": 7,
            "text": "Xin chào.",
            "start": 1.0,
            "end": 2.0,
            "words": [{"word": "Xin", "start": 1.0, "end": 1.4}],
        }],
    )
    self.assertEqual(request.segments[0].words[0].word, "Xin")

def test_rejects_word_outside_parent_segment(self):
    with self.assertRaises(ValidationError):
        ContextualTranslationRequest(
            source_language="vi",
            target_language="en",
            segments=[{
                "id": 0,
                "text": "Xin chào.",
                "start": 1.0,
                "end": 2.0,
                "words": [{"word": "Xin", "start": 0.5, "end": 1.4}],
            }],
        )

def test_caption_post_process_request_preserves_original_pair(self):
    request = CaptionPostProcessRequest(
        source_language="vi",
        target_language="en",
        segments=[{
            "id": 4,
            "source": "Xin chào.",
            "translation": "Hello.",
            "start": 0,
            "end": 1,
            "words": [],
        }],
    )
    self.assertEqual(request.segments[0].translation, "Hello.")
```

Also test `ContextualTranslationLimits.from_settings` with a fake settings
object and assert the four exact values `32`, `1.0`, `3`, and `1.0`.

- [ ] **Step 2: Run the model tests and verify failure**

Run:

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_contextual_translation_models -v
```

Expected: FAIL because the new models and `words` field do not exist.

- [ ] **Step 3: Implement the models and settings**

Add these settings to `Settings`:

```python
CONTEXT_TRANSLATION_MAX_CAPTION_CHARS: int = 32
CONTEXT_TRANSLATION_TARGET_LENGTH_MULTIPLIER: float = 1.0
CONTEXT_TRANSLATION_SPLIT_PASSES: int = 3
CONTEXT_TRANSLATION_MAX_SPLIT_PASSES: int = 8
CONTEXT_TRANSLATION_GAP_CLOSE_SECONDS: float = 1.0
```

Define strict models with finite, ordered timestamp validation:

```python
class TranslationWordInput(BaseModel):
    word: str = Field(..., min_length=1, max_length=1_000)
    start: float = Field(..., ge=0, allow_inf_nan=False)
    end: float = Field(..., ge=0, allow_inf_nan=False)

class CaptionTranslationInput(BaseModel):
    id: int = Field(..., ge=0)
    source: str = Field(..., min_length=1, max_length=20_000)
    translation: str = Field(..., min_length=1, max_length=20_000)
    start: float = Field(..., ge=0, allow_inf_nan=False)
    end: float = Field(..., ge=0, allow_inf_nan=False)
    words: list[TranslationWordInput] = Field(default_factory=list)

class DisplayCaptionSegment(BaseModel):
    id: int = Field(..., ge=0)
    parent_id: int = Field(..., ge=0)
    part_index: int = Field(..., ge=0)
    source: str
    translation: str
    start: float
    end: float

class SubtitleVariants(BaseModel):
    srt: str
    vtt: str

class SubtitleDocumentSet(BaseModel):
    source: SubtitleVariants
    translation: SubtitleVariants
    source_translation: SubtitleVariants
    translation_source: SubtitleVariants
```

Use model validators to require unique IDs, `end > start`, ordered non-overlapping words, and words contained by the parent segment. Empty `words` is valid.

- [ ] **Step 4: Run the model tests**

Run the command from Step 2.

Expected: PASS.

- [ ] **Step 5: Commit only the backend contract files**

```bash
git add services/ai-backend/app/config.py \
  services/ai-backend/app/models/translation.py \
  services/ai-backend/tests/test_contextual_translation_models.py
git commit --only \
  services/ai-backend/app/config.py \
  services/ai-backend/app/models/translation.py \
  services/ai-backend/tests/test_contextual_translation_models.py \
  -m "feat: define aligned caption processing contract"
```

Before committing, inspect `git diff --cached --name-only` and ensure no unrelated path is staged for this commit. If unrelated paths are already staged by the user, use a path-limited commit that does not include them.

---

### Task 2: Implement deterministic weighted splitting and timestamps

**Files:**

- Create: `services/ai-backend/app/services/caption_splitter.py`
- Create: `services/ai-backend/tests/test_caption_splitter.py`

**Interfaces:**

- Produces: `weighted_length(text: str) -> float`.
- Produces: `requires_split(source: str, translation: str, *, max_chars: int, target_multiplier: float) -> bool`.
- Produces: `split_timed_source(...) -> tuple[TimedSourcePart, TimedSourcePart]`.
- Produces: `close_short_gaps(parts: list[DisplayCaptionSegment], threshold: float) -> list[DisplayCaptionSegment]`.

- [ ] **Step 1: Write failing weighted-length tests**

```python
class WeightedLengthTests(unittest.TestCase):
    def test_applies_videolingo_script_weights(self):
        self.assertEqual(weighted_length("abc"), 3)
        self.assertEqual(weighted_length("漢"), 1.75)
        self.assertEqual(weighted_length("あ"), 1.75)
        self.assertEqual(weighted_length("한"), 1.5)
        self.assertEqual(weighted_length("ก"), 1.0)
        self.assertEqual(weighted_length("Ａ"), 1.75)
        self.assertEqual(weighted_length("Tiếng Việt"), 10)

    def test_target_multiplier_can_trigger_split(self):
        self.assertTrue(requires_split(
            "short",
            "12345678901234567",
            max_chars=32,
            target_multiplier=2.0,
        ))
```

- [ ] **Step 2: Run the focused test and verify failure**

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_caption_splitter.WeightedLengthTests -v
```

Expected: FAIL because `caption_splitter` does not exist.

- [ ] **Step 3: Implement weighted length and split policy**

Implement the exact Unicode ranges from the design. Source uses `len(source)`;
target uses `weighted_length(translation) * target_multiplier`.

- [ ] **Step 4: Write failing boundary and timing tests**

Cover:

```python
def test_vietnamese_prefers_punctuation_then_word_boundaries(self):
    left, right = split_timed_source(
        source="Đây là phần đầu, và đây là phần tiếp theo",
        start=0,
        end=4,
        words=[],
        max_chars=24,
    )
    self.assertEqual(f"{left.text} {right.text}", "Đây là phần đầu, và đây là phần tiếp theo")
    self.assertTrue(left.text.endswith(","))

def test_uses_word_timestamps_when_words_reconstruct_source(self):
    left, right = split_timed_source(
        source="one two three four",
        start=1,
        end=5,
        words=[
            TranslationWordInput(word="one", start=1, end=2),
            TranslationWordInput(word="two", start=2, end=3),
            TranslationWordInput(word="three", start=3, end=4),
            TranslationWordInput(word="four", start=4, end=5),
        ],
        max_chars=10,
    )
    self.assertEqual((left.start, left.end), (1, 3))
    self.assertEqual((right.start, right.end), (3, 5))

def test_missing_word_coverage_uses_proportional_parent_timing(self):
    left, right = split_timed_source(
        source="one two three four",
        start=10,
        end=14,
        words=[],
        max_chars=10,
    )
    self.assertEqual(left.start, 10)
    self.assertEqual(right.end, 14)
    self.assertEqual(left.end, right.start)
```

Also test a 40-character token split into two parts with proportional timing.

- [ ] **Step 5: Run timing tests and verify failure**

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_caption_splitter -v
```

Expected: weighted tests pass; new splitting tests fail.

- [ ] **Step 6: Implement balanced source splitting**

Create:

```python
@dataclass(frozen=True)
class TimedSourcePart:
    text: str
    start: float
    end: float
    words: tuple[TranslationWordInput, ...]
```

Choose the valid split nearest the balanced midpoint using the design's
punctuation priority. Preserve normalized text order. Use exact first/last word
timestamps when words reconstruct the part; otherwise distribute the parent
duration by normalized character length. Clamp the split point inside the
parent range and require positive durations.

- [ ] **Step 7: Add and implement short-gap tests**

```python
def test_closes_only_positive_gaps_below_threshold(self):
    result = close_short_gaps(
        [
            display(id=0, parent_id=0, start=0, end=1),
            display(id=1, parent_id=0, start=1.5, end=2),
            display(id=2, parent_id=1, start=3.5, end=4),
        ],
        threshold=1.0,
    )
    self.assertEqual(result[0].end, 1.5)
    self.assertEqual(result[1].end, 2)
```

Close a short gap only when adjacent parts have the same `parent_id`. Do not
extend a cue across a parent boundary or past its parent end.

- [ ] **Step 8: Run all splitter tests**

Run the command from Step 5.

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add services/ai-backend/app/services/caption_splitter.py \
  services/ai-backend/tests/test_caption_splitter.py
git commit --only \
  services/ai-backend/app/services/caption_splitter.py \
  services/ai-backend/tests/test_caption_splitter.py \
  -m "feat: split captions with multilingual timing"
```

---

### Task 3: Align translated parts and build display/audio results

**Files:**

- Create: `services/ai-backend/app/services/caption_postprocessor.py`
- Create: `services/ai-backend/tests/test_caption_postprocessor.py`

**Interfaces:**

- Consumes: model contracts from Task 1 and pure splitter functions from Task 2.
- Produces: `CaptionPostProcessor(backend, limits)`.
- Produces: internal `CaptionProcessingResult` containing `display_segments` and `audio_segments`.
- Produces: `async process_pairs(request: CaptionPostProcessRequest) -> CaptionProcessingResult`.
- Raises: `CaptionPolicyError`, `CaptionAlignmentError`, or `CaptionProviderError`.

- [ ] **Step 1: Write a failing no-split preservation test**

```python
async def test_short_pair_keeps_original_display_and_audio_granularity(self):
    processor = CaptionPostProcessor(backend=AsyncMock(), limits=limits())
    result = await processor.process_pairs(postprocess_request(
        source="Xin chào.",
        translation="Hello.",
    ))
    self.assertEqual(len(result.display_segments), 1)
    self.assertEqual(result.display_segments[0].translation, "Hello.")
    self.assertEqual(result.audio_segments[0].translation, "Hello.")
    processor.backend.generate_json.assert_not_awaited()
```

- [ ] **Step 2: Run the focused test and verify failure**

```bash
cd services/ai-backend
.venv/bin/python -m unittest \
  tests.test_caption_postprocessor.CaptionPostProcessorTests.test_short_pair_keeps_original_display_and_audio_granularity -v
```

Expected: FAIL because the processor does not exist.

- [ ] **Step 3: Implement the short-pair path**

Construct one `DisplayCaptionSegment` per short input. Assign sequential display
IDs while preserving `parent_id`, source, translation, and timestamps. Copy the
original pairs to `audio_segments`.

- [ ] **Step 4: Write failing LLM alignment tests**

Use an oversized pair and verify:

```python
backend.generate_json.return_value = {
    "alignments": [
        {"id": 0, "translation": "Phần một"},
        {"id": 1, "translation": "phần hai"},
    ]
}
result = await processor.process_pairs(request)
self.assertEqual(
    [part.translation for part in result.display_segments],
    ["Phần một", "phần hai"],
)
self.assertEqual(len(result.audio_segments), 1)
self.assertEqual(result.audio_segments[0].translation, original_translation)
```

Add cases for missing IDs, reordered IDs, empty translations, correction on the
third total attempt, and exhaustion after three total attempts.

- [ ] **Step 5: Run the alignment tests and verify failure**

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_caption_postprocessor -v
```

Expected: short-pair test passes; alignment tests fail.

- [ ] **Step 6: Implement strict alignment**

The prompt must include source language, target language, original source,
original translation, and exact source parts:

```python
{
    "source_parts": [
        {"id": 0, "source": "..."},
        {"id": 1, "source": "..."},
    ]
}
```

Validate an `alignments` list with exact ordered IDs and non-empty translation
strings. Reuse `limits.correction_retries`. Include only the previous validation
message in retries, never provider exception detail.

- [ ] **Step 7: Write recursive pass and terminal-policy tests**

Test that:

- a still-oversized part is split again on the next pass;
- high-expansion output can continue through `max_split_passes == 8`;
- output IDs and `part_index` are sequential;
- every output range stays within the parent segment; and
- a caption still oversized after the eighth pass raises `CaptionPolicyError`
  without returning partial output.

- [ ] **Step 8: Implement recursive processing and gap closing**

Run split/check passes in source order. Start with three passes and continue
adaptively through eight when any part remains oversized. A split part receives
a fresh alignment request for its two new source parts. After all parents are complete, flatten,
renumber, validate, and call `close_short_gaps`.

- [ ] **Step 9: Run post-processor tests**

Run the command from Step 5.

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add services/ai-backend/app/services/caption_postprocessor.py \
  services/ai-backend/tests/test_caption_postprocessor.py
git commit --only \
  services/ai-backend/app/services/caption_postprocessor.py \
  services/ai-backend/tests/test_caption_postprocessor.py \
  -m "feat: align translated caption parts"
```

---

### Task 4: Generate monolingual and bilingual subtitle documents

**Files:**

- Modify: `services/ai-backend/app/services/subtitle_service.py`
- Create: `services/ai-backend/tests/test_subtitle_service.py`

**Interfaces:**

- Consumes: `list[DisplayCaptionSegment]`.
- Produces: `build_subtitle_documents(segments) -> SubtitleDocumentSet`.
- Extends: `CaptionPostProcessor.process(request) -> CaptionPostProcessResponse`
  by combining `process_pairs()` with `build_subtitle_documents()`.
- Preserves: existing `segments_to_srt`, `segments_to_vtt`, and `segments_to_ass`.

- [ ] **Step 1: Write failing timestamp-boundary tests**

```python
def test_srt_rounding_carries_into_next_second(self):
    self.assertEqual(_format_srt_time(1.9996), "00:00:02,000")

def test_vtt_rounding_carries_into_next_second(self):
    self.assertEqual(_format_vtt_time(59.9996), "00:01:00.000")
```

- [ ] **Step 2: Run and verify failure**

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_subtitle_service -v
```

Expected: FAIL because current rounding can emit millisecond value `1000`.

- [ ] **Step 3: Correct timestamp formatting**

Convert to rounded total milliseconds first:

```python
total_ms = max(0, round(seconds * 1000))
hours, remainder = divmod(total_ms, 3_600_000)
minutes, remainder = divmod(remainder, 60_000)
whole_seconds, milliseconds = divmod(remainder, 1_000)
```

Use comma for SRT and period for WebVTT.

- [ ] **Step 4: Write failing document-layout tests**

For two display segments, assert:

- source SRT contains source text only;
- translated SRT contains translation only;
- source-first bilingual SRT has source then translation on exactly two lines;
- translation-first bilingual VTT reverses those lines;
- each display segment becomes exactly one cue; and
- no serializer re-wraps the already split text.

- [ ] **Step 5: Implement `build_subtitle_documents`**

Create a shared cue renderer accepting a text selector:

```python
def _source_translation(segment):
    return f"{segment.source}\n{segment.translation}"
```

Return a typed `SubtitleDocumentSet` with all eight documents.

- [ ] **Step 6: Complete the public post-processing response**

Add:

```python
async def process(
    self,
    request: CaptionPostProcessRequest,
) -> CaptionPostProcessResponse:
    processed = await self.process_pairs(request)
    return CaptionPostProcessResponse(
        source_language=request.source_language,
        target_language=request.target_language,
        display_segments=processed.display_segments,
        audio_segments=processed.audio_segments,
        subtitles=build_subtitle_documents(processed.display_segments),
    )
```

Keep the Task 3 `process_pairs()` tests unchanged and add one assertion that
`process()` returns all subtitle variants.

- [ ] **Step 7: Run subtitle tests and existing transcription subtitle tests**

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_subtitle_service -v
.venv/bin/python -m unittest tests.test_transcription_proxy -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add services/ai-backend/app/services/subtitle_service.py \
  services/ai-backend/app/services/caption_postprocessor.py \
  services/ai-backend/tests/test_caption_postprocessor.py \
  services/ai-backend/tests/test_subtitle_service.py
git commit --only \
  services/ai-backend/app/services/subtitle_service.py \
  services/ai-backend/app/services/caption_postprocessor.py \
  services/ai-backend/tests/test_caption_postprocessor.py \
  services/ai-backend/tests/test_subtitle_service.py \
  -m "feat: generate aligned subtitle documents"
```

---

### Task 5: Integrate contextual translation and expose post-processing

**Files:**

- Modify: `services/ai-backend/app/services/caption_postprocessor.py`
- Modify: `services/ai-backend/app/services/contextual_translation.py`
- Modify: `services/ai-backend/app/routes/translation.py`
- Modify: `services/ai-backend/tests/test_contextual_translation_service.py`
- Modify: `services/ai-backend/tests/test_contextual_translation_route.py`
- Modify: `services/ai-backend/tests/test_app_import.py`

**Interfaces:**

- Contextual endpoint: `POST /api/translations/contextual`.
- Sarvam path: `POST /api/translations/captions/post-process`.
- Both return the shared display/audio/subtitle models.

- [ ] **Step 1: Write failing contextual integration test**

Extend the existing translation fixture with words and assert:

```python
result = await service.translate(request())
self.assertEqual(result.segments[0].translation, "OpenCut is private.")
self.assertEqual(result.audio_segments[0].translation, "OpenCut is private.")
self.assertEqual(result.display_segments[0].parent_id, 0)
self.assertIn("WEBVTT", result.subtitles.translation.vtt)
```

Use short translations so no extra alignment response is needed in existing
contextual translation tests.

- [ ] **Step 2: Run service tests and verify failure**

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_contextual_translation_service -v
```

Expected: FAIL because contextual responses lack the new fields.

- [ ] **Step 3: Run shared post-processing after translation**

Build `CaptionTranslationInput` values by combining:

- source text and words from `request.segments`;
- translation from the validated LLM result; and
- original IDs and timestamps.

Call `CaptionPostProcessor.process`, attach its output to
`ContextualTranslationResponse`, and keep `segments` unchanged.

- [ ] **Step 4: Write failing route tests**

Add tests that:

```python
self.assertIn("/api/translations/captions/post-process", app_paths)
```

Patch the shared processor for the new endpoint and assert its response is
returned. Verify:

- Pydantic/model errors remain HTTP 422;
- `CaptionPolicyError` maps to sanitized HTTP 422;
- alignment exhaustion maps to sanitized HTTP 502; and
- `CaptionProviderError` caused by an unavailable LLM maps to sanitized HTTP
  503 when alignment is required.

- [ ] **Step 5: Implement route and exception mapping**

Define:

```python
@router.post(
    "/captions/post-process",
    response_model=CaptionPostProcessResponse,
)
async def post_process_captions(
    request: CaptionPostProcessRequest,
) -> CaptionPostProcessResponse:
    ...
```

Instantiate one shared `CaptionPostProcessor` using `llm_backend` and current
limits. Keep all error text sanitized.

- [ ] **Step 6: Run all translation and import tests**

```bash
cd services/ai-backend
.venv/bin/python -m unittest \
  tests.test_contextual_translation_models \
  tests.test_contextual_translation_service \
  tests.test_contextual_translation_route \
  tests.test_app_import -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add services/ai-backend/app/services/caption_postprocessor.py \
  services/ai-backend/app/services/contextual_translation.py \
  services/ai-backend/app/routes/translation.py \
  services/ai-backend/tests/test_contextual_translation_service.py \
  services/ai-backend/tests/test_contextual_translation_route.py \
  services/ai-backend/tests/test_app_import.py
git commit --only \
  services/ai-backend/app/services/caption_postprocessor.py \
  services/ai-backend/app/services/contextual_translation.py \
  services/ai-backend/app/routes/translation.py \
  services/ai-backend/tests/test_contextual_translation_service.py \
  services/ai-backend/tests/test_contextual_translation_route.py \
  services/ai-backend/tests/test_app_import.py \
  -m "feat: expose aligned caption post-processing"
```

---

### Task 6: Extend web API types and client

**Files:**

- Modify: `apps/web/src/types/ai.ts`
- Modify carefully: `apps/web/src/lib/ai-client.ts`
- Create: `apps/web/src/lib/transcription/__tests__/caption-api.test.ts`

**Interfaces:**

- Produces: `ContextualTranslationWordInput`, `DisplayCaptionSegment`, `CaptionPostProcessRequest`, `CaptionPostProcessResult`, and subtitle document types.
- Produces: `aiClient.postProcessCaptions(request)`.
- Extends: `ContextualTranslationResult`.

- [ ] **Step 1: Write failing API-client tests**

Mock `fetch`, call both client methods, and assert:

```typescript
expect(JSON.parse(String(init?.body)).segments[0].words).toEqual([
  { word: "Xin", start: 0, end: 0.4 },
]);
expect(url).toEndWith("/api/translations/captions/post-process");
```

Also define a result fixture whose `display_segments` contains two parts and
whose `audio_segments` contains one original-granularity part.

- [ ] **Step 2: Run and verify failure**

```bash
cd apps/web
bun test src/lib/transcription/__tests__/caption-api.test.ts
```

Expected: FAIL because the types and post-processing client method do not exist.

- [ ] **Step 3: Add exact TypeScript contracts**

Mirror backend snake_case fields exactly. Add `words` to
`ContextualTranslationSegmentInput`; do not rename the backend response at the
client boundary.

- [ ] **Step 4: Add the post-processing request**

In `AIClient`:

```typescript
async postProcessCaptions(
  request: CaptionPostProcessRequest,
): Promise<CaptionPostProcessResult> {
  return this.request<CaptionPostProcessResult>(
    "/api/translations/captions/post-process",
    {
      method: "POST",
      body: JSON.stringify(request),
    },
    LLM_TIMEOUT_MS,
  );
}
```

Preserve both the staged transcription timeout hunk and the existing unstaged
`translateTranscript` implementation in `apps/web/src/lib/ai-client.ts`.

- [ ] **Step 5: Run the client test and TypeScript**

```bash
cd apps/web
bun test src/lib/transcription/__tests__/caption-api.test.ts
bunx tsc --noEmit
```

Expected: PASS.

- [ ] **Step 6: Commit only safe, non-overlapping paths**

Commit the type and test paths if their index state is clean:

```bash
git add apps/web/src/types/ai.ts \
  apps/web/src/lib/transcription/__tests__/caption-api.test.ts
git commit --only \
  apps/web/src/types/ai.ts \
  apps/web/src/lib/transcription/__tests__/caption-api.test.ts \
  -m "feat: define aligned caption web contract"
```

Leave `apps/web/src/lib/ai-client.ts` uncommitted if isolating only the new
hunks from its pre-existing user changes cannot be proven safe. Do not reset,
unstage, or overwrite its existing changes.

---

### Task 7: Use display segments for contextual and Sarvam tracks

**Files:**

- Modify: `apps/web/src/lib/transcription/translate-captions.ts`
- Modify: `apps/web/src/hooks/actions/use-editor-actions.ts`
- Modify: `apps/web/src/lib/transcription/__tests__/translate-captions.test.ts`
- Modify: `apps/web/src/lib/transcription/__tests__/subtitle-track.test.ts`
- Verify existing: `apps/web/src/constants/transcription-constants.ts`
- Verify existing: `apps/web/src/lib/transcription/__tests__/caption.test.ts`

**Interfaces:**

- Consumes: contextual `display_segments`.
- Consumes: `postProcessCaptions` for already translated Sarvam pairs.
- Stores: original-granularity `audio_segments`.
- Creates: one text element per display segment through `createSubtitleTrack`.

- [ ] **Step 1: Write failing contextual display-segment test**

Change the contextual fixture to contain one audio segment and two display
segments. Assert:

```typescript
expect(storeTranslation).toHaveBeenCalledWith(
  expect.objectContaining({
    segments: [expect.objectContaining({ text: "Original full translation" })],
  }),
);
expect(createTrack).toHaveBeenCalledWith(
  expect.objectContaining({
    segments: [
      expect.objectContaining({ text: "First display part", start: 0, end: 1 }),
      expect.objectContaining({ text: "Second display part", start: 1, end: 2 }),
    ],
  }),
);
```

- [ ] **Step 2: Write failing request-word test**

Capture the request passed to `translateContextual` and assert source words are
sent as `{word, start, end}` without the web-only `confidence`.

- [ ] **Step 3: Write failing Sarvam post-processing test**

Add `postProcessCaptions` to `CaptionTranslationDependencies`. Assert Sarvam
translation runs first, its original pairs are sent to post-processing with
source word timings, and only the returned display segments create the track.

- [ ] **Step 4: Run workflow tests and verify failure**

```bash
cd apps/web
bun test src/lib/transcription/__tests__/translate-captions.test.ts
```

Expected: FAIL because the workflow currently creates tracks from
original-granularity translated segments and never post-processes Sarvam.

- [ ] **Step 5: Implement provider-independent output handling**

Create helpers:

```typescript
function displaySegments(
  result: CaptionPostProcessResult,
): CaptionSourceSegment[]

function storedTranslationSegments(
  result: CaptionPostProcessResult,
): TranslatedTranscript["segments"]
```

For contextual translation, use its enriched result directly. For Sarvam:

1. translate original segments;
2. call `postProcessCaptions`;
3. store `audio_segments`; and
4. create the track from `display_segments`.

Keep all store and timeline mutation after successful post-processing.

- [ ] **Step 6: Wire the existing action dependency**

In `use-editor-actions.ts`, supply:

```typescript
postProcessCaptions: (request) => aiClient.postProcessCaptions(request),
```

Do not add a new action or bypass `translate-captions`.

- [ ] **Step 7: Verify one timeline element per display segment**

Extend `subtitle-track.test.ts` or add a focused test with a fake editor that
records `insertElement` calls:

```typescript
expect(insertElement).toHaveBeenCalledTimes(2);
expect(insertElement.mock.calls[0][0].element.startTime).toBe(0);
expect(insertElement.mock.calls[1][0].element.startTime).toBe(1);
```

- [ ] **Step 8: Run focused web tests**

```bash
cd apps/web
bun test \
  src/lib/transcription/__tests__/translate-captions.test.ts \
  src/lib/transcription/__tests__/subtitle-track.test.ts \
  src/lib/transcription/__tests__/caption.test.ts \
  src/lib/transcription/__tests__/caption-api.test.ts
bunx tsc --noEmit
```

Expected: PASS.

- [ ] **Step 9: Commit only non-overlapping web files**

```bash
git add apps/web/src/lib/transcription/translate-captions.ts \
  apps/web/src/hooks/actions/use-editor-actions.ts \
  apps/web/src/lib/transcription/__tests__/translate-captions.test.ts \
  apps/web/src/lib/transcription/__tests__/subtitle-track.test.ts \
  apps/web/src/constants/transcription-constants.ts \
  apps/web/src/lib/transcription/__tests__/caption.test.ts
git commit --only \
  apps/web/src/lib/transcription/translate-captions.ts \
  apps/web/src/hooks/actions/use-editor-actions.ts \
  apps/web/src/lib/transcription/__tests__/translate-captions.test.ts \
  apps/web/src/lib/transcription/__tests__/subtitle-track.test.ts \
  apps/web/src/constants/transcription-constants.ts \
  apps/web/src/lib/transcription/__tests__/caption.test.ts \
  -m "feat: add separately timed translated captions"
```

Inspect the staged paths first. Exclude any file containing unrelated user
changes that cannot be isolated safely.

---

### Task 8: Full regression verification and documentation check

**Files:**

- Verify: `docs/superpowers/specs/2026-07-28-caption-splitting-subtitle-generation-design.md`
- Verify: all files changed in Tasks 1–7.

**Interfaces:**

- Confirms: the complete design is implemented without changing whisper-service behavior or deleting workspace artifacts.

- [ ] **Step 1: Run the complete ai-backend suite**

```bash
cd services/ai-backend
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Run the complete whisper-service suite**

```bash
cd services/whisper-service
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests pass; no Docker is used.

- [ ] **Step 3: Run the complete web suite**

```bash
cd apps/web
bun test
bunx tsc --noEmit
```

Expected: all tests and type checking pass.

- [ ] **Step 4: Compile modified Python modules**

```bash
services/ai-backend/.venv/bin/python -m compileall -q \
  services/ai-backend/app/models/translation.py \
  services/ai-backend/app/services/caption_splitter.py \
  services/ai-backend/app/services/caption_postprocessor.py \
  services/ai-backend/app/services/contextual_translation.py \
  services/ai-backend/app/services/subtitle_service.py \
  services/ai-backend/app/routes/translation.py
```

Expected: exit code `0`.

- [ ] **Step 5: Check diff integrity and workspace preservation**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors. Pre-existing user changes and audio artifacts
remain present. No deletion is introduced.

- [ ] **Step 6: Compare implementation against the approved spec**

Confirm each of these exact outcomes:

- max length `32`;
- weighted multilingual target measurement;
- separately timed `display_segments`;
- original-granularity `audio_segments`;
- contextual and Sarvam post-processing;
- source, translated, and both bilingual SRT/VTT documents;
- two correction retries;
- atomic web mutation; and
- no new UI button.

- [ ] **Step 7: Prepare the handoff**

Report:

- exact test totals;
- any pre-existing warnings;
- any intentionally uncommitted overlapping `ai-client.ts` hunk;
- changed endpoint and response fields; and
- local non-Docker commands for manual testing.
