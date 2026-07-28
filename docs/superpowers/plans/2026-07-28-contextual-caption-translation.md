# Contextual Caption Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add VideoLingo-style theme, terminology, and contextual translation to timestamped transcript segments, exposed through the AI backend and the existing Captions “Add language” control.

**Architecture:** The Whisper service remains unchanged and returns source-language semantic segments. A new AI-backend translation service validates those segments, extracts target-language context, translates strict ID-addressed batches through the existing unified LLM backend, and returns the original timing. The web invokes that service through a typed client and a `translate-captions` editor action, then creates a translated subtitle track only after a complete successful response.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, `asyncio`, existing `llm_backend`, `unittest`; TypeScript 5.8, React 19, Zustand, Bun test, existing EditorCore action/command systems.

## Global Constraints

- Do not change `services/whisper-service`, WhisperX, faster-whisper, Demucs, spaCy, or semantic segmentation.
- Do not run or require Docker.
- Keep `/transcribe` independent of target-language selection and translation availability.
- Use `app.services.model_backend.llm_backend`; do not introduce another local-LLM provider client.
- Preserve every source segment `id`, `start`, and `end`; never accept timing or identity from LLM output.
- Fail the contextual translation as one operation; never add a partial translated track or silently replace a failed translation with source text.
- Do not persist transcript text, prompts, theme, or terminology to new server-side files.
- Keep the existing Sarvam route and provider behavior for supported Indian-language pairs.
- Do not implement reflective translation, TTS-duration shortening, dubbing, persistent caching, or streaming progress.
- Keep unrelated dirty or staged workspace changes untouched. Stage and commit only the exact files listed by each task.

---

## File Structure

### AI backend

- Create `services/ai-backend/app/models/translation.py`
  - Public request/response schemas and aggregate request validation.
- Create `services/ai-backend/app/services/contextual_translation.py`
  - Context extraction, custom-term merging, batch construction, prompts,
    correction retries, concurrent translation, and result assembly.
- Create `services/ai-backend/app/routes/translation.py`
  - `/api/translations/contextual` availability check and HTTP error mapping.
- Modify `services/ai-backend/app/config.py`
  - Central contextual-translation limits.
- Modify `services/ai-backend/app/main.py`
  - Register the new router.
- Create `services/ai-backend/tests/test_contextual_translation_models.py`
- Create `services/ai-backend/tests/test_contextual_translation_service.py`
- Create `services/ai-backend/tests/test_contextual_translation_route.py`

### Web

- Modify `apps/web/src/types/ai.ts`
  - Structured contextual translation request and response types.
- Modify `apps/web/src/lib/ai-client.ts`
  - Typed `translateTranscript()` request.
- Create `apps/web/src/lib/transcription/translation-provider.ts`
  - Pure provider selection shared by the action and UI copy.
- Create `apps/web/src/lib/transcription/subtitle-track.ts`
  - Internal timeline helper moved out of the React component.
- Create `apps/web/src/lib/transcription/translate-captions.ts`
  - Testable async translation-and-commit workflow used by the action handler.
- Create `apps/web/src/lib/transcription/translation-control.ts`
  - Pure button visibility/disabled-state derivation.
- Modify `apps/web/src/lib/actions/definitions.ts`
  - Register `translate-captions`.
- Modify `apps/web/src/lib/actions/types.ts`
  - Add typed target-language arguments.
- Modify `apps/web/src/hooks/actions/use-editor-actions.ts`
  - Bind the translation action to the workflow.
- Modify `apps/web/src/stores/transcript-store.ts`
  - Store subtitle track IDs/languages so a global action can update them.
- Modify `apps/web/src/components/editor/panels/assets/views/captions.tsx`
  - Invoke the action from the renamed **Translate & add** button and remove
    prompt-building/response-parsing code.
- Create `apps/web/src/lib/transcription/__tests__/translation-provider.test.ts`
- Create `apps/web/src/lib/transcription/__tests__/translate-captions.test.ts`
- Create `apps/web/src/lib/transcription/__tests__/translation-control.test.ts`
- Create `apps/web/src/lib/__tests__/ai-client-translation.test.ts`

---

### Task 1: Translation API Models and Limits

**Files:**

- Create: `services/ai-backend/app/models/translation.py`
- Modify: `services/ai-backend/app/config.py`
- Create: `services/ai-backend/tests/test_contextual_translation_models.py`

**Interfaces:**

- Produces:
  - `TranslationTerm`
  - `TranslationSegmentInput`
  - `ContextualTranslationRequest`
  - `TranslatedSegment`
  - `ContextualTranslationResponse`
  - `ContextualTranslationLimits.from_settings(settings)`
- Consumers: Tasks 2–4.

- [ ] **Step 1: Write failing schema tests**

Create `tests/test_contextual_translation_models.py` with focused validation:

```python
import unittest
from pydantic import ValidationError

from app.models.translation import ContextualTranslationRequest


class ContextualTranslationModelTests(unittest.TestCase):
    def test_accepts_ordered_timestamped_segments(self):
        request = ContextualTranslationRequest(
            source_language="vi",
            target_language="en",
            segments=[
                {"id": 7, "text": "Xin chào.", "start": 1.25, "end": 2.5},
                {"id": 9, "text": "Hẹn gặp lại.", "start": 2.5, "end": 4.0},
            ],
        )
        self.assertEqual([segment.id for segment in request.segments], [7, 9])

    def test_rejects_same_source_and_target_language(self):
        with self.assertRaises(ValidationError):
            ContextualTranslationRequest(
                source_language="vi",
                target_language="VI",
                segments=[{"id": 0, "text": "Xin chào.", "start": 0, "end": 1}],
            )

    def test_rejects_duplicate_ids(self):
        with self.assertRaises(ValidationError):
            ContextualTranslationRequest(
                source_language="vi",
                target_language="en",
                segments=[
                    {"id": 1, "text": "Một.", "start": 0, "end": 1},
                    {"id": 1, "text": "Hai.", "start": 1, "end": 2},
                ],
            )

    def test_rejects_reversed_or_non_finite_timestamps(self):
        invalid_segments = [
            {"id": 0, "text": "Bad.", "start": 2, "end": 1},
            {"id": 0, "text": "Bad.", "start": float("inf"), "end": 2},
        ]
        for segment in invalid_segments:
            with self.subTest(segment=segment):
                with self.assertRaises(ValidationError):
                    ContextualTranslationRequest(
                        source_language="en",
                        target_language="es",
                        segments=[segment],
                    )
```

- [ ] **Step 2: Run the model tests and verify the missing module failure**

Run:

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_contextual_translation_models -v
```

Expected: `ModuleNotFoundError: No module named 'app.models.translation'`.

- [ ] **Step 3: Add bounded settings and Pydantic models**

Add these settings to `Settings` in `app/config.py`:

```python
CONTEXT_TRANSLATION_SUMMARY_CHARS: int = 12_000
CONTEXT_TRANSLATION_MAX_SOURCE_CHARS: int = 250_000
CONTEXT_TRANSLATION_MAX_SEGMENTS: int = 2_000
CONTEXT_TRANSLATION_BATCH_CHARS: int = 600
CONTEXT_TRANSLATION_BATCH_SEGMENTS: int = 10
CONTEXT_TRANSLATION_MAX_CONCURRENCY: int = 2
CONTEXT_TRANSLATION_CORRECTION_RETRIES: int = 2
```

Implement immutable response/input structures in `app/models/translation.py`.
Use `Field(min_length=2, max_length=16)` for language codes,
`Field(min_length=1, max_length=20_000)` for segment text,
`Field(min_length=1, max_length=200)` for term fields, finite non-negative
timestamp fields, and `model_validator(mode="after")`. The request validator
must compare languages with `casefold()` and reject duplicate IDs. The service
performs the configurable aggregate character/segment checks before making an
LLM call.

Define a frozen limits dataclass:

```python
@dataclass(frozen=True)
class ContextualTranslationLimits:
    summary_chars: int
    max_source_chars: int
    max_segments: int
    batch_chars: int
    batch_segments: int
    max_concurrency: int
    correction_retries: int

    @classmethod
    def from_settings(cls, value: Any) -> "ContextualTranslationLimits":
        return cls(
            summary_chars=value.CONTEXT_TRANSLATION_SUMMARY_CHARS,
            max_source_chars=value.CONTEXT_TRANSLATION_MAX_SOURCE_CHARS,
            max_segments=value.CONTEXT_TRANSLATION_MAX_SEGMENTS,
            batch_chars=value.CONTEXT_TRANSLATION_BATCH_CHARS,
            batch_segments=value.CONTEXT_TRANSLATION_BATCH_SEGMENTS,
            max_concurrency=value.CONTEXT_TRANSLATION_MAX_CONCURRENCY,
            correction_retries=value.CONTEXT_TRANSLATION_CORRECTION_RETRIES,
        )
```

The API models use snake_case fields matching the JSON contract in the design.

- [ ] **Step 4: Run the model tests**

Run:

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_contextual_translation_models -v
```

Expected: all model tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add services/ai-backend/app/config.py \
  services/ai-backend/app/models/translation.py \
  services/ai-backend/tests/test_contextual_translation_models.py
git commit -m "feat: define contextual translation contract"
```

---

### Task 2: Theme and Terminology Extraction

**Files:**

- Create: `services/ai-backend/app/services/contextual_translation.py`
- Create: `services/ai-backend/tests/test_contextual_translation_service.py`

**Interfaces:**

- Consumes:
  - `ContextualTranslationRequest`
  - `TranslationTerm`
  - `ContextualTranslationLimits`
  - a backend exposing
    `generate_json(prompt: str, system: str, _retries: int) -> Awaitable[dict]`
- Produces:
  - `ContextualTranslationError`
  - `TranslationProviderError`
  - `TranslationValidationError`
  - `merge_terms(inferred, custom) -> list[TranslationTerm]`
  - `ContextualTranslationService.extract_context(request) -> Awaitable[TranslationContext]`
- Consumers: Task 3.

- [ ] **Step 1: Write failing extraction and merge tests**

Start `test_contextual_translation_service.py` with:

```python
import unittest
from unittest.mock import AsyncMock

from app.models.translation import (
    ContextualTranslationLimits,
    ContextualTranslationRequest,
    TranslationTerm,
)
from app.services.contextual_translation import (
    ContextualTranslationService,
    merge_terms,
)


def limits(**overrides):
    values = {
        "summary_chars": 100,
        "max_source_chars": 1_000,
        "max_segments": 100,
        "batch_chars": 50,
        "batch_segments": 2,
        "max_concurrency": 2,
        "correction_retries": 2,
    }
    values.update(overrides)
    return ContextualTranslationLimits(**values)


def request():
    return ContextualTranslationRequest(
        source_language="vi",
        target_language="en",
        segments=[
            {"id": 0, "text": "OpenCut là trình biên tập.", "start": 0, "end": 2},
            {"id": 1, "text": "Nó bảo vệ riêng tư.", "start": 2, "end": 4},
        ],
        custom_terms=[
            {"source": "OpenCut", "target": "OpenCut", "note": "Keep product name."}
        ],
    )


class ContextExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_extracts_theme_and_custom_terms_override_inferred_terms(self):
        backend = AsyncMock()
        backend.generate_json.return_value = {
            "theme": "A private video editor.",
            "terms": [
                {"source": "OpenCut", "target": "Cắt Mở", "note": "Inferred."},
                {"source": "riêng tư", "target": "privacy", "note": "Concept."},
            ],
        }
        service = ContextualTranslationService(backend=backend, limits=limits())

        context = await service.extract_context(request())

        self.assertEqual(context.theme, "A private video editor.")
        self.assertEqual(
            [(term.source, term.target) for term in context.terms],
            [("OpenCut", "OpenCut"), ("riêng tư", "privacy")],
        )
        self.assertIn("vi", backend.generate_json.await_args.kwargs["prompt"])
        self.assertIn("en", backend.generate_json.await_args.kwargs["prompt"])

    async def test_retries_invalid_context_with_validation_error(self):
        backend = AsyncMock()
        backend.generate_json.side_effect = [
            {"theme": "", "terms": []},
            {"theme": "Valid theme.", "terms": []},
        ]
        service = ContextualTranslationService(backend=backend, limits=limits())

        context = await service.extract_context(request())

        self.assertEqual(context.theme, "Valid theme.")
        self.assertEqual(backend.generate_json.await_count, 2)
        self.assertIn("Previous validation error", backend.generate_json.await_args.kwargs["prompt"])
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```bash
cd services/ai-backend
.venv/bin/python -m unittest \
  tests.test_contextual_translation_service.ContextExtractionTests -v
```

Expected: import failure for the missing service.

- [ ] **Step 3: Implement extraction, validation, and deterministic term merging**

In `contextual_translation.py`:

- define frozen `TranslationContext(theme, terms)`;
- use `request.segments` in their supplied order;
- join their text and slice only the context sample to `summary_chars`;
- ask for strict JSON keys `theme` and `terms`;
- call
  `backend.generate_json(prompt=prompt, system="Return strict JSON only.", _retries=0)`
  so this service owns semantic correction retries;
- validate every term through `TranslationTerm.model_validate`;
- preserve inferred-term order;
- replace an inferred term in place when a custom term has the same
  `source.casefold()`; and
- append unmatched custom terms.

Use this retry skeleton for both context and later batch translation:

```python
for attempt in range(self.limits.correction_retries + 1):
    prompt = build_prompt(previous_error)
    try:
        payload = await self.backend.generate_json(
            prompt=prompt,
            system="Return strict JSON only.",
            _retries=0,
        )
        return validator(payload)
    except TranslationValidationError as exc:
        previous_error = str(exc)
        if attempt == self.limits.correction_retries:
            raise
    except Exception as exc:
        raise TranslationProviderError("Translation provider failed.") from exc
```

The exact call is
`backend.generate_json(prompt=prompt, system="Return strict JSON only.", _retries=0)`.
Never include backend exception details in the public error message.

- [ ] **Step 4: Run extraction tests**

Run:

```bash
cd services/ai-backend
.venv/bin/python -m unittest \
  tests.test_contextual_translation_service.ContextExtractionTests -v
```

Expected: all extraction tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add services/ai-backend/app/services/contextual_translation.py \
  services/ai-backend/tests/test_contextual_translation_service.py
git commit -m "feat: extract translation theme and terminology"
```

---

### Task 3: Contextual Batch Translation

**Files:**

- Modify: `services/ai-backend/app/services/contextual_translation.py`
- Modify: `services/ai-backend/tests/test_contextual_translation_service.py`

**Interfaces:**

- Consumes: `TranslationContext` and interfaces from Tasks 1–2.
- Produces:
  - `build_batches(segments, max_chars, max_segments)`
  - `matching_terms(text, terms)`
  - `ContextualTranslationService.translate(request) -> Awaitable[ContextualTranslationResponse]`
- Consumers: Task 4.

- [ ] **Step 1: Add failing batching and orchestration tests**

Append tests that prove:

```python
class ContextualTranslationTests(unittest.IsolatedAsyncioTestCase):
    async def test_translates_batches_with_neighbors_and_matching_terms(self):
        backend = AsyncMock()
        backend.generate_json.side_effect = [
            {
                "theme": "OpenCut tutorial.",
                "terms": [
                    {"source": "OpenCut", "target": "OpenCut", "note": "Product."},
                    {"source": "khác", "target": "other", "note": "Must not leak."},
                ],
            },
            {"translations": [{"id": 0, "translation": "OpenCut is private."}]},
            {"translations": [{"id": 1, "translation": "It runs locally."}]},
        ]
        service = ContextualTranslationService(
            backend=backend,
            limits=limits(batch_chars=1_000, batch_segments=1, max_concurrency=1),
        )
        result = await service.translate(request())

        self.assertEqual([segment.id for segment in result.segments], [0, 1])
        self.assertEqual(result.segments[0].start, 0)
        self.assertEqual(result.segments[1].end, 4)
        first_batch_prompt = backend.generate_json.await_args_list[1].kwargs["prompt"]
        self.assertIn("OpenCut", first_batch_prompt)
        self.assertNotIn('"source": "khác"', first_batch_prompt)
        self.assertIn("Following source context", first_batch_prompt)

    async def test_retries_when_response_ids_do_not_exactly_match(self):
        backend = AsyncMock()
        backend.generate_json.side_effect = [
            {"theme": "Theme.", "terms": []},
            {"translations": [{"id": 99, "translation": "Wrong."}]},
            {"translations": [{"id": 0, "translation": "One."}, {"id": 1, "translation": "Two."}]},
        ]
        service = ContextualTranslationService(
            backend=backend,
            limits=limits(batch_chars=1_000, batch_segments=10),
        )
        result = await service.translate(request())
        self.assertEqual([segment.translation for segment in result.segments], ["One.", "Two."])

    async def test_exhausted_validation_failure_returns_no_partial_result(self):
        backend = AsyncMock()
        backend.generate_json.side_effect = [
            {"theme": "Theme.", "terms": []},
            {"translations": []},
            {"translations": []},
            {"translations": []},
        ]
        service = ContextualTranslationService(backend=backend, limits=limits())
        with self.assertRaises(TranslationValidationError):
            await service.translate(request())

    async def test_concurrent_batches_are_reassembled_in_source_order(self):
        second_finished = asyncio.Event()
        context_returned = False

        async def generate_json(*, prompt, **_kwargs):
            nonlocal context_returned
            if not context_returned:
                context_returned = True
                return {"theme": "Theme.", "terms": []}
            if '"id": 0' in prompt:
                await second_finished.wait()
                return {"translations": [{"id": 0, "translation": "One."}]}
            second_finished.set()
            return {"translations": [{"id": 1, "translation": "Two."}]}

        backend = AsyncMock()
        backend.generate_json.side_effect = generate_json
        service = ContextualTranslationService(
            backend=backend,
            limits=limits(batch_chars=1_000, batch_segments=1, max_concurrency=2),
        )

        result = await service.translate(request())

        self.assertEqual([segment.id for segment in result.segments], [0, 1])
```

Import `asyncio` at the top of the test module. The side effect blocks ID `0`
until ID `1` completes, so the assertion proves source-order assembly rather
than task-completion order.

- [ ] **Step 2: Run the translation tests and verify the first missing-method failure**

Run:

```bash
cd services/ai-backend
.venv/bin/python -m unittest \
  tests.test_contextual_translation_service.ContextualTranslationTests -v
```

Expected: failure because `ContextualTranslationService.translate` is absent.

- [ ] **Step 3: Implement bounded batches, context prompts, concurrency, and assembly**

Implement `build_batches` so adding a segment flushes the current batch when
either the character limit or segment-count limit would be exceeded. A single
segment longer than `batch_chars` remains one batch; semantic segments are
never split or rewritten here.

For each batch:

- previous context is the preceding batch's last three source strings;
- following context is the next batch's first two source strings;
- terminology matching is case-insensitive substring matching against only the
  current batch text;
- the prompt contains numbered `{id, source}` records;
- response shape is exactly a `translations` list whose every entry has only a
  validated integer `id` and non-empty string `translation`; and
- returned IDs must equal requested IDs in the same order.

Run batch calls with:

```python
semaphore = asyncio.Semaphore(self.limits.max_concurrency)

async def guarded(index: int, batch: list[TranslationSegmentInput]):
    async with semaphore:
        return await self._translate_batch(index, batches, context)

translated_batches = await asyncio.gather(
    *(guarded(index, batch) for index, batch in enumerate(batches))
)
```

`asyncio.gather` is constructed in source order, so flatten
`translated_batches` directly. Build every `TranslatedSegment` by copying
`id`, `text`, `start`, and `end` from the request and only taking
`translation` from validated output.

- [ ] **Step 4: Run the complete service tests**

Run:

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_contextual_translation_service -v
```

Expected: all context, batching, concurrency, retry, and timestamp tests pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add services/ai-backend/app/services/contextual_translation.py \
  services/ai-backend/tests/test_contextual_translation_service.py
git commit -m "feat: translate transcript segments with context"
```

---

### Task 4: Public Translation Route

**Files:**

- Create: `services/ai-backend/app/routes/translation.py`
- Modify: `services/ai-backend/app/main.py`
- Create: `services/ai-backend/tests/test_contextual_translation_route.py`
- Modify: `services/ai-backend/tests/test_app_import.py`

**Interfaces:**

- Consumes: `ContextualTranslationService.translate()` from Task 3.
- Produces: `POST /api/translations/contextual`.
- Consumers: Task 5.

- [ ] **Step 1: Write failing route tests**

Create route tests with `IsolatedAsyncioTestCase`:

```python
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.models.translation import ContextualTranslationRequest
from app.routes.translation import contextual_translation
from app.services.contextual_translation import TranslationProviderError


def request():
    return ContextualTranslationRequest(
        source_language="vi",
        target_language="en",
        segments=[{"id": 0, "text": "Xin chào.", "start": 0, "end": 1}],
    )


class ContextualTranslationRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_service_response_when_llm_is_available(self):
        with (
            patch("app.routes.translation.llm_backend.check_available", new=AsyncMock(return_value=True)),
            patch("app.routes.translation.translation_service.translate", new=AsyncMock()) as translate,
        ):
            translate.return_value = {
                "source_language": "vi",
                "target_language": "en",
                "theme": "Greeting.",
                "terminology": [],
                "segments": [
                    {
                        "id": 0,
                        "source": "Xin chào.",
                        "translation": "Hello.",
                        "start": 0,
                        "end": 1,
                    }
                ],
            }
            result = await contextual_translation(request())
        self.assertEqual(result["segments"][0]["translation"], "Hello.")

    async def test_returns_503_when_no_llm_is_available(self):
        with patch(
            "app.routes.translation.llm_backend.check_available",
            new=AsyncMock(return_value=False),
        ):
            with self.assertRaises(HTTPException) as raised:
                await contextual_translation(request())
        self.assertEqual(raised.exception.status_code, 503)

    async def test_sanitizes_provider_failure_as_502(self):
        with (
            patch("app.routes.translation.llm_backend.check_available", new=AsyncMock(return_value=True)),
            patch(
                "app.routes.translation.translation_service.translate",
                new=AsyncMock(side_effect=TranslationProviderError("private detail")),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await contextual_translation(request())
        self.assertEqual(raised.exception.status_code, 502)
        self.assertNotIn("private detail", raised.exception.detail)
```

- [ ] **Step 2: Run the route tests and verify import failure**

Run:

```bash
cd services/ai-backend
.venv/bin/python -m unittest tests.test_contextual_translation_route -v
```

Expected: import failure for the missing route.

- [ ] **Step 3: Implement and register the route**

Create a router with:

```python
router = APIRouter(prefix="/api/translations", tags=["translations"])
translation_service = ContextualTranslationService(
    backend=llm_backend,
    limits=ContextualTranslationLimits.from_settings(settings),
)


@router.post("/contextual", response_model=ContextualTranslationResponse)
async def contextual_translation(
    request: ContextualTranslationRequest,
) -> ContextualTranslationResponse:
    if not await llm_backend.check_available():
        raise HTTPException(status_code=503, detail="No LLM backend available.")
    try:
        return await translation_service.translate(request)
    except ContextualTranslationError as exc:
        logger.warning("Contextual translation failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail="Contextual translation failed.",
        ) from exc
```

Import and include `translation.router` in `app/main.py`. Extend
`test_app_import.py` to assert the application exposes
`/api/translations/contextual`.

- [ ] **Step 4: Run all AI-backend tests**

Run:

```bash
cd services/ai-backend
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests pass with no network services running because provider calls
are mocked.

- [ ] **Step 5: Commit Task 4**

```bash
git add services/ai-backend/app/routes/translation.py \
  services/ai-backend/app/main.py \
  services/ai-backend/tests/test_contextual_translation_route.py \
  services/ai-backend/tests/test_app_import.py
git commit -m "feat: expose contextual translation endpoint"
```

---

### Task 5: Typed Web Client

**Files:**

- Modify: `apps/web/src/types/ai.ts`
- Modify: `apps/web/src/lib/ai-client.ts`
- Create: `apps/web/src/lib/__tests__/ai-client-translation.test.ts`

**Interfaces:**

- Consumes: `POST /api/translations/contextual` from Task 4.
- Produces:
  - `ContextualTranslationRequest`
  - `ContextualTranslationResult`
  - `AIClient.translateTranscript(request) -> Promise<ContextualTranslationResult>`
- Consumers: Task 6.

- [ ] **Step 1: Write a failing client contract test**

Mock `globalThis.fetch` with Bun and assert the exact URL/body:

```typescript
import { afterEach, describe, expect, mock, test } from "bun:test";
import { aiClient } from "@/lib/ai-client";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
  mock.restore();
});

describe("AIClient.translateTranscript", () => {
  test("posts the structured transcript to the contextual endpoint", async () => {
    const fetchMock = mock(async (_url: string | URL | Request, init?: RequestInit) =>
      new Response(JSON.stringify({
        source_language: "vi",
        target_language: "en",
        theme: "Greeting.",
        terminology: [],
        segments: [{
          id: 4,
          source: "Xin chào.",
          translation: "Hello.",
          start: 1,
          end: 2,
        }],
      }), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    globalThis.fetch = fetchMock as typeof fetch;

    const result = await aiClient.translateTranscript({
      source_language: "vi",
      target_language: "en",
      segments: [{ id: 4, text: "Xin chào.", start: 1, end: 2 }],
      custom_terms: [],
    });

    expect(result.segments[0].translation).toBe("Hello.");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toEndWith("/api/translations/contextual");
    expect(JSON.parse(String(init?.body))).toEqual({
      source_language: "vi",
      target_language: "en",
      segments: [{ id: 4, text: "Xin chào.", start: 1, end: 2 }],
      custom_terms: [],
    });
  });
});
```

- [ ] **Step 2: Run the client test and verify the missing-method failure**

Run:

```bash
cd apps/web
bun test src/lib/__tests__/ai-client-translation.test.ts
```

Expected: TypeScript/runtime failure because `translateTranscript` is absent.

- [ ] **Step 3: Add exact request/response types and client method**

Add snake_case wire types to `types/ai.ts`, including term input/output,
timestamped request segments, translated output segments, and the complete
result. Do not reuse `TranscriptionSegment` because it has word/confidence
fields that are not part of this API.

Add:

```typescript
async translateTranscript(
  request: ContextualTranslationRequest,
): Promise<ContextualTranslationResult> {
  return this.request<ContextualTranslationResult>(
    "/api/translations/contextual",
    {
      method: "POST",
      body: JSON.stringify(request),
    },
    LLM_TIMEOUT_MS,
  );
}
```

Keep the old `translateText()` method because other features may still consume
it. Only Captions stops using it in Task 7.

- [ ] **Step 4: Run the client test and TypeScript compiler**

Run:

```bash
cd apps/web
bun test src/lib/__tests__/ai-client-translation.test.ts
bunx tsc --noEmit
```

Expected: client test passes and TypeScript exits zero.

- [ ] **Step 5: Commit Task 5**

`apps/web/src/lib/ai-client.ts` already contains unrelated staged user edits.
Do not stage or commit that path in this task. Leave the feature method in the
working tree and commit only the new clean type/test paths. Record this
intentional uncommitted overlap in the final handoff.

```bash
git add apps/web/src/types/ai.ts \
  apps/web/src/lib/__tests__/ai-client-translation.test.ts
git diff --cached --check
git commit --only \
  apps/web/src/types/ai.ts \
  apps/web/src/lib/__tests__/ai-client-translation.test.ts \
  -m "feat: define contextual translation web contract"
```

---

### Task 6: Translation Provider and Action Workflow

**Files:**

- Create: `apps/web/src/lib/transcription/translation-provider.ts`
- Create: `apps/web/src/lib/transcription/subtitle-track.ts`
- Create: `apps/web/src/lib/transcription/translate-captions.ts`
- Modify: `apps/web/src/lib/actions/definitions.ts`
- Modify: `apps/web/src/lib/actions/types.ts`
- Modify: `apps/web/src/hooks/actions/use-editor-actions.ts`
- Modify: `apps/web/src/stores/transcript-store.ts`
- Create: `apps/web/src/lib/transcription/__tests__/translation-provider.test.ts`
- Create: `apps/web/src/lib/transcription/__tests__/translate-captions.test.ts`

**Interfaces:**

- Consumes:
  - `aiClient.translateTranscript()` from Task 5
  - existing `aiClient.sarvamTranslate()`
  - transcript/background-task stores
  - `buildCaptionChunks()`
  - `EditorCore`
- Produces:
  - `shouldUseSarvamTranslation(source, target) -> boolean`
  - `createSubtitleTrack(editor, input) -> string`
  - `translateAndAddCaptions(args, dependencies) -> Promise<string>`
  - action `translate-captions` with
    `{ targetLanguage: string; targetLanguageName: string }`
- Consumers: Task 7.

- [ ] **Step 1: Write failing provider and atomic-workflow tests**

Provider tests cover English↔Indian, Indian↔Indian, and global pairs:

```typescript
expect(shouldUseSarvamTranslation("en", "hi")).toBe(true);
expect(shouldUseSarvamTranslation("hi", "ta")).toBe(true);
expect(shouldUseSarvamTranslation("vi", "en")).toBe(false);
```

Workflow tests use dependency injection:

```typescript
test("commits translation and track only after contextual success", async () => {
  const calls: string[] = [];
  const trackId = await translateAndAddCaptions(
    { targetLanguage: "en", targetLanguageName: "English" },
    {
      getTranscript: () => ({
        language: "vi",
        segments: [{ id: 0, text: "Xin chào.", start: 0, end: 1, words: [] }],
      }),
      translateContextual: async () => ({
        source_language: "vi",
        target_language: "en",
        theme: "Greeting.",
        terminology: [],
        segments: [{
          id: 0,
          source: "Xin chào.",
          translation: "Hello.",
          start: 0,
          end: 1,
        }],
      }),
      translateSarvam: async () => { throw new Error("not used"); },
      addTask: () => calls.push("task"),
      updateTask: (_id, update) => calls.push(String(update.status ?? update.progress)),
      storeTranslation: () => calls.push("translation"),
      createTrack: () => { calls.push("track"); return "track-1"; },
      storeTrack: () => calls.push("track-state"),
      now: () => 100,
    },
  );

  expect(trackId).toBe("track-1");
  expect(calls.indexOf("translation")).toBeLessThan(calls.indexOf("track"));
});

test("does not mutate transcript or timeline when translation fails", async () => {
  const storeTranslation = mock(() => {});
  const createTrack = mock(() => "track-1");
  const failureDependencies = {
    getTranscript: () => ({
      language: "vi",
      segments: [{ id: 0, text: "Xin chào.", start: 0, end: 1, words: [] }],
    }),
    translateContextual: async () => { throw new Error("provider failed"); },
    translateSarvam: async () => { throw new Error("not used"); },
    addTask: mock(() => {}),
    updateTask: mock(() => {}),
    storeTranslation,
    createTrack,
    storeTrack: mock(() => {}),
    now: () => 100,
  };
  await expect(
    translateAndAddCaptions(
      { targetLanguage: "en", targetLanguageName: "English" },
      failureDependencies,
    ),
  ).rejects.toThrow("provider failed");
  expect(storeTranslation).not.toHaveBeenCalled();
  expect(createTrack).not.toHaveBeenCalled();
});
```

Both tests use complete dependency objects so failure behavior is independently
reproducible.

- [ ] **Step 2: Run the new tests and verify import failures**

Run:

```bash
cd apps/web
bun test \
  src/lib/transcription/__tests__/translation-provider.test.ts \
  src/lib/transcription/__tests__/translate-captions.test.ts
```

Expected: import failures for the missing modules.

- [ ] **Step 3: Implement provider selection and testable workflow**

Move the existing Sarvam language-pair decision into
`translation-provider.ts`, importing the existing Sarvam constants.

In `translate-captions.ts`, define a dependency interface matching the test.
The workflow must:

1. capture transcript state once;
2. reject empty transcripts and identical source/target languages;
3. create a `translation-<target>-<timestamp>` background task;
4. use contextual translation for global pairs;
5. preserve the existing segment-by-segment Sarvam path for supported Indian
   pairs;
6. build the complete translated segment list in memory;
7. call `storeTranslation`;
8. call `createTrack`;
9. store `{trackId, language: targetLanguage}`;
10. mark the task completed; and
11. on any error, mark the task failed and rethrow without steps 7–9.

For local LLM translation, set progress to
`Translating with video context…`, then `Adding subtitle track…`. Sarvam may
retain per-segment progress.

Move the component's current `addSubtitleTrack` implementation to
`subtitle-track.ts` as `createSubtitleTrack(editor, input)`. Continue using
`editor.timeline.addTrack`, `renameTrack`, and `insertElement`; these manager
calls already execute undoable commands.

- [ ] **Step 4: Register and bind the action**

Add to `ACTIONS`:

```typescript
"translate-captions": {
  description: "Translate transcript and add subtitle track",
  category: "ai",
  args: {
    targetLanguage: "string",
    targetLanguageName: "string",
  },
},
```

Add to `TActionArgsMap`:

```typescript
"translate-captions": {
  targetLanguage: string;
  targetLanguageName: string;
};
```

In `use-editor-actions.ts`, bind the action and assemble production
dependencies from `aiClient`, `useTranscriptStore.getState()`,
`useBackgroundTasksStore.getState()`, `createSubtitleTrack`, and the current
`editor`. Start the async workflow with `void`, and let the workflow's
background-task update produce the failure toast:

```typescript
useActionHandler(
  "translate-captions",
  (args) => {
    void translateAndAddCaptions(
      args,
      createCaptionTranslationDependencies(editor),
    ).catch(() => undefined);
  },
  undefined,
);
```

Add `subtitleTracks`, `addSubtitleTrack`, `removeSubtitleTrack`, and
`setSubtitleTracks` to `transcript-store.ts`. Reset clears them with the rest of
the transcript state.

- [ ] **Step 5: Run workflow tests and TypeScript compiler**

Run:

```bash
cd apps/web
bun test \
  src/lib/transcription/__tests__/translation-provider.test.ts \
  src/lib/transcription/__tests__/translate-captions.test.ts
bunx tsc --noEmit
```

Expected: tests pass and TypeScript exits zero.

- [ ] **Step 6: Commit Task 6**

```bash
git add apps/web/src/lib/transcription/translation-provider.ts \
  apps/web/src/lib/transcription/subtitle-track.ts \
  apps/web/src/lib/transcription/translate-captions.ts \
  apps/web/src/lib/transcription/__tests__/translation-provider.test.ts \
  apps/web/src/lib/transcription/__tests__/translate-captions.test.ts \
  apps/web/src/lib/actions/definitions.ts \
  apps/web/src/lib/actions/types.ts \
  apps/web/src/hooks/actions/use-editor-actions.ts \
  apps/web/src/stores/transcript-store.ts
git commit -m "feat: add contextual caption translation action"
```

---

### Task 7: Captions Translate & Add Control

**Files:**

- Create: `apps/web/src/lib/transcription/translation-control.ts`
- Create: `apps/web/src/lib/transcription/__tests__/translation-control.test.ts`
- Modify: `apps/web/src/components/editor/panels/assets/views/captions.tsx`

**Interfaces:**

- Consumes:
  - `translate-captions` action from Task 6
  - subtitle track state from `useTranscriptStore`
  - translation background tasks
- Produces: the final **Translate & add** UI.

- [ ] **Step 1: Write failing pure control-state tests**

```typescript
import { describe, expect, test } from "bun:test";
import { getTranslationControlState } from "@/lib/transcription/translation-control";

describe("getTranslationControlState", () => {
  test("hides the control until a transcript exists", () => {
    expect(getTranslationControlState({
      segmentCount: 0,
      targetLanguage: "es",
      activeLanguages: [],
      translating: false,
    })).toEqual({ visible: false, disabled: true });
  });

  test("disables an active or already-added language", () => {
    expect(getTranslationControlState({
      segmentCount: 2,
      targetLanguage: "es",
      activeLanguages: ["es"],
      translating: false,
    }).disabled).toBe(true);
    expect(getTranslationControlState({
      segmentCount: 2,
      targetLanguage: "fr",
      activeLanguages: [],
      translating: true,
    }).disabled).toBe(true);
  });

  test("enables an eligible target", () => {
    expect(getTranslationControlState({
      segmentCount: 2,
      targetLanguage: "es",
      activeLanguages: [],
      translating: false,
    })).toEqual({ visible: true, disabled: false });
  });
});
```

- [ ] **Step 2: Run the test and verify import failure**

Run:

```bash
cd apps/web
bun test src/lib/transcription/__tests__/translation-control.test.ts
```

Expected: import failure for the missing helper.

- [ ] **Step 3: Implement the helper and replace component-local orchestration**

Implement the pure helper exactly from the tested input/output shape.

In `captions.tsx`:

- import `invokeAction`;
- import `shouldUseSarvamTranslation` rather than defining it locally;
- use subtitle track state from `useTranscriptStore` instead of component-local
  `useState`;
- read the newest running `translation` background task for
  `isTranslating`/progress;
- delete the local generic LLM batching and numbered-line parsing;
- delete the moved `addSubtitleTrack` function and import
  `createSubtitleTrack` only for the existing original-subtitle button;
- keep filtering target-language options already present as active tracks;
- keep the selector in **Captions → Add language**;
- rename the button from `Add` to `Translate & add`; and
- invoke:

```typescript
invokeAction(
  "translate-captions",
  {
    targetLanguage: targetLang.code,
    targetLanguageName: targetLang.name,
  },
  "mouseclick",
);
```

The local-LLM description becomes:
`Translate with video context and add a new subtitle track.`
The Sarvam description remains provider-specific.

- [ ] **Step 4: Run focused web tests and compiler**

Run:

```bash
cd apps/web
bun test \
  src/lib/transcription/__tests__/translation-control.test.ts \
  src/lib/transcription/__tests__/translation-provider.test.ts \
  src/lib/transcription/__tests__/translate-captions.test.ts \
  src/lib/__tests__/ai-client-translation.test.ts
bunx tsc --noEmit
```

Expected: all focused tests pass and TypeScript exits zero.

- [ ] **Step 5: Commit Task 7**

```bash
git add apps/web/src/lib/transcription/translation-control.ts \
  apps/web/src/lib/transcription/__tests__/translation-control.test.ts \
  apps/web/src/components/editor/panels/assets/views/captions.tsx
git commit -m "feat: add contextual translation caption control"
```

---

### Task 8: Full Verification and Documentation Check

**Files:**

- Verify only; modify a task-owned file only if verification exposes a defect.

**Interfaces:**

- Consumes: all previous tasks.
- Produces: verified backend route, typed web integration, and clean task diff.

- [ ] **Step 1: Run the complete AI-backend suite**

```bash
cd services/ai-backend
.venv/bin/python -m unittest discover -s tests -v
```

Expected: zero failures and zero errors.

- [ ] **Step 2: Run the complete Whisper suite to prove isolation**

```bash
cd services/whisper-service
.venv/bin/python -m unittest discover -s tests -v
```

Expected: all existing Whisper tests pass with no translation-specific changes.

- [ ] **Step 3: Run all web tests and TypeScript**

```bash
cd apps/web
bun test
bunx tsc --noEmit
```

Expected: all Bun tests pass and TypeScript exits zero.

- [ ] **Step 4: Run Python syntax compilation**

```bash
cd services/ai-backend
.venv/bin/python -m compileall -q app tests
```

Expected: exit zero.

- [ ] **Step 5: Check formatting and exact diff scope**

```bash
git diff --check
git status --short
git log --oneline -10
```

Confirm:

- no Docker files or commands were added;
- no Whisper service files changed;
- no transcript/prompt persistence was introduced;
- existing unrelated dirty and staged files remain present and unmodified by
  this feature; and
- every feature commit contains only its task-owned paths/hunks.

- [ ] **Step 6: Perform one local API smoke test when an LLM is available**

Start the existing AI backend locally, then:

```bash
curl -sS -X POST http://127.0.0.1:8420/api/translations/contextual \
  -H 'Content-Type: application/json' \
  -d '{
    "source_language": "vi",
    "target_language": "en",
    "segments": [
      {"id": 0, "text": "Xin chào mọi người.", "start": 0.5, "end": 2.0}
    ],
    "custom_terms": []
  }'
```

Expected: JSON containing `theme`, `terminology`, and segment `id: 0` with
unchanged `start: 0.5` and `end: 2.0`. If no LLM is running, record the expected
HTTP `503` and rely on the mocked route/service tests; do not start Docker.

- [ ] **Step 7: Commit only if verification required a corrective change**

If a defect was fixed, rerun the command that exposed it plus the complete
affected suite, then return to the responsible task's exact `git add` list and
commit those corrective paths with
`git commit -m "fix: complete contextual caption translation"`.

If verification required no changes, do not create an empty commit.
