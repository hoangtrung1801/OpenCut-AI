# Whisper Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace raw faster-whisper segment output with a tested pipeline that separates persistent audio stems, optionally force-aligns words with WhisperX, applies spaCy and mandatory LLM semantic segmentation, and preserves the existing transcription API with additive artifact URLs.

**Architecture:** The Whisper service owns media preparation, Demucs, canonical faster-whisper ASR, optional WhisperX alignment, deterministic spaCy grouping, semantic-boundary validation, final segment reconstruction, and persistent artifacts. The AI backend owns LLM prompting plus browser-safe proxy routes. Original ASR words remain canonical; WhisperX and the LLM may change timestamps or boundaries but never transcript text.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, faster-whisper, WhisperX, Demucs, PyTorch 2.8, spaCy 3.8, FFmpeg, httpx, unittest, Docker Compose, TypeScript.

## Global Constraints

- Demucs `htdemucs` separation is mandatory for every transcription.
- Completed `vocals.mp3` and `background.mp3` artifacts use 192 kbps and are never deleted automatically.
- faster-whisper transcribes the normalized original mix with native word timestamps.
- WhisperX aligns against the normalized vocal stem and falls back to native faster-whisper timestamps on any alignment-specific failure.
- WhisperX speaker diarization is out of scope.
- spaCy packages and pipelines are pinned at build time; a request never downloads or installs them.
- Vietnamese uses `xx_sent_ud_sm` plus conservative connector rules and never an English parser.
- Semantic splitting is enabled by default and is required only for groups over 20 words.
- A required semantic-refinement failure fails `/transcribe`; the LLM may return only word-boundary indexes.
- Successfully returned audio artifacts have no expiration or automatic cleanup.
- The existing `text`, `segments`, `language`, and `duration` response fields remain compatible.
- No VideoLingo Excel workspace, translation, subtitle rendering, dubbing, or speaker diarization is added.

---

## File Structure

### Whisper service

- `services/whisper-service/settings.py`: validated environment configuration and language/model maps.
- `services/whisper-service/models.py`: public Pydantic models and internal immutable word/media records.
- `services/whisper-service/media_pipeline.py`: FFmpeg normalization, Demucs model reuse, MP3 artifact persistence, and failure cleanup.
- `services/whisper-service/alignment.py`: optional WhisperX forced alignment over canonical faster-whisper output.
- `services/whisper-service/segmentation.py`: timestamp repair, spaCy boundary mapping, Vietnamese rules, boundary validation, and final reconstruction.
- `services/whisper-service/semantic_client.py`: typed AI-backend client with three validated attempts.
- `services/whisper-service/pipeline.py`: orchestration from prepared media through the final response.
- `services/whisper-service/app.py`: model lifecycle and HTTP routes only.
- `services/whisper-service/tests/`: unit and service-contract tests.

### AI backend and web

- `services/ai-backend/app/routes/transcription_refine.py`: internal LLM boundary endpoint.
- `services/ai-backend/app/routes/transcribe.py`: public transcription proxy, URL rewriting, and artifact streaming proxy.
- `services/ai-backend/app/main.py`: registers the internal route.
- `services/ai-backend/tests/test_transcription_refine.py`: internal prompt/validation tests.
- `services/ai-backend/tests/test_transcription_proxy.py`: artifact and downstream-error proxy tests.
- `apps/web/src/types/ai.ts`: primary response type with separated-audio URLs.
- `apps/web/src/types/transcription.ts`: shared response type with separated-audio URLs.

### Deployment

- `services/whisper-service/requirements.txt`: resolvable runtime dependencies and pinned spaCy pipeline wheels.
- `services/whisper-service/requirements-demucs.txt`: pinned Demucs Git revision installed with `--no-deps`.
- `services/whisper-service/requirements.lock`: regenerated universal dependency lock.
- `services/whisper-service/Dockerfile`: installs the locked stack and the isolated Demucs package.
- `docker-compose.yml`: AI callback URL, artifact configuration, and persistent artifact volume.

---

### Task 1: Establish typed settings and shared models

**Files:**
- Create: `services/whisper-service/settings.py`
- Create: `services/whisper-service/models.py`
- Create: `services/whisper-service/tests/__init__.py`
- Create: `services/whisper-service/tests/test_settings_models.py`
- Modify: `services/whisper-service/app.py`

**Interfaces:**
- Produces: `Settings.from_env() -> Settings`
- Produces: `WordToken`, `PreparedMedia`, `SeparatedAudio`, `TranscriptionWord`, `TranscriptionSegment`, and `TranscriptionResult`
- Consumes: existing environment names and public JSON fields from `app.py`

- [ ] **Step 1: Write failing settings and serialization tests**

```python
class SettingsModelTests(unittest.TestCase):
    def test_defaults_enable_required_pipeline(self):
        settings = Settings.from_env({})
        self.assertEqual(settings.semantic_max_words, 20)
        self.assertEqual(settings.semantic_max_retries, 3)
        self.assertEqual(settings.demucs_model, "htdemucs")
        self.assertEqual(settings.artifact_dir, Path("artifacts"))

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
        self.assertEqual(result.model_dump()["separated_audio"]["vocals_url"], "/artifacts/abc/vocals")
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
cd services/whisper-service
python -m unittest tests.test_settings_models -v
```

Expected: import failure for missing `settings` and `models` modules.

- [ ] **Step 3: Implement immutable settings and models**

Define `Settings` as a frozen dataclass with `from_env(environ: Mapping[str, str] | None = None)`. Parse booleans strictly from `1/true/yes/on`, validate positive integer limits, require `semantic_min_words < semantic_max_words <= semantic_window_words`, and expose these defaults:

```python
ai_backend_url = "http://localhost:8420"
artifact_dir = Path("artifacts")
demucs_model = "htdemucs"
demucs_device = "auto"
demucs_mp3_bitrate = "192k"
whisperx_alignment_enabled = True
whisperx_device = "auto"
spacy_enabled = True
spacy_fallback_model = "xx_sent_ud_sm"
semantic_split_enabled = True
semantic_max_words = 20
semantic_min_words = 3
semantic_window_words = 60
semantic_max_retries = 3
semantic_timeout_seconds = 300.0
```

Define `WordToken` with `raw_text`, `word`, `start`, `end`, `probability`, `source_segment_id`, `avg_logprob`, and `no_speech_prob`. Define `PreparedMedia` with artifact and temporary paths. Move the public Pydantic models unchanged from `app.py`, then add `separated_audio: SeparatedAudio | None = None`. The completed Whisper pipeline always supplies it; the optional model default keeps transitional code and non-Whisper consumers compatible.

- [ ] **Step 4: Update `app.py` imports without changing runtime behavior**

Remove duplicate Pydantic class definitions and import them from `models.py`. Instantiate one `settings = Settings.from_env()` and preserve current endpoint behavior until later tasks.

- [ ] **Step 5: Run tests and the import smoke check**

```bash
cd services/whisper-service
python -m unittest tests.test_settings_models -v
python -c "import app"
```

Expected: all tests pass and `app` imports.

- [ ] **Step 6: Commit only Task 1 files**

```bash
git add services/whisper-service/settings.py services/whisper-service/models.py services/whisper-service/tests/__init__.py services/whisper-service/tests/test_settings_models.py services/whisper-service/app.py
git commit --only services/whisper-service/settings.py services/whisper-service/models.py services/whisper-service/tests/__init__.py services/whisper-service/tests/test_settings_models.py services/whisper-service/app.py -m "refactor: add typed whisper pipeline foundations"
```

---

### Task 2: Build persistent Demucs media processing

**Files:**
- Create: `services/whisper-service/media_pipeline.py`
- Create: `services/whisper-service/tests/test_media_pipeline.py`

**Interfaces:**
- Consumes: `Settings`, uploaded/extracted source path, artifact UUID
- Produces: `MediaPipeline.prepare(source_path: Path, artifact_id: str) -> PreparedMedia`
- Produces: `MediaPipeline.artifact_path(artifact_id: str, stem: str) -> Path`

- [ ] **Step 1: Write failing tests for separation, encoding, and cleanup**

Use a fake separator returning `{"vocals": vocal_tensor, "drums": drums, "bass": bass, "other": other}` and a fake command runner that records FFmpeg arguments.

```python
def test_prepare_sums_non_vocal_sources_and_uses_original_mix_for_asr(self):
    prepared = self.pipeline.prepare(self.source, self.artifact_id)
    self.assertEqual(self.separator.background_sources, ["drums", "bass", "other"])
    self.assertIn("original-asr.wav", str(prepared.asr_path))
    self.assertIn("vocal-align.wav", str(prepared.alignment_path))
    self.assertTrue(prepared.vocals_path.name == "vocals.mp3")
    self.assertTrue(prepared.background_path.name == "background.mp3")

def test_failed_prepare_removes_partial_artifact_directory(self):
    self.runner.fail_on = "background.mp3"
    with self.assertRaises(MediaProcessingError):
        self.pipeline.prepare(self.source, self.artifact_id)
    self.assertFalse((self.artifact_root / self.artifact_id).exists())

def test_completed_artifacts_are_not_removed_by_temporary_cleanup(self):
    prepared = self.pipeline.prepare(self.source, self.artifact_id)
    prepared.cleanup_temporary()
    self.assertTrue(prepared.vocals_path.exists())
    self.assertTrue(prepared.background_path.exists())
```

- [ ] **Step 2: Run the tests and verify RED**

```bash
cd services/whisper-service
python -m unittest tests.test_media_pipeline -v
```

Expected: import failure for missing `media_pipeline`.

- [ ] **Step 3: Implement safe artifact resolution**

Accept artifact IDs only when `uuid.UUID(value).hex == value.replace("-", "")`. Accept stems only from `{"vocals", "background"}`. Resolve the final path and assert it remains below `artifact_dir` before returning `{stem}.mp3`.

- [ ] **Step 4: Implement FFmpeg preparation and encoding**

Use argument arrays, `check=True`, and captured stderr. Required transforms:

```text
source -> separation-source.wav              preserve sample rate/channels
source -> original-asr.wav                    pcm_s16le, 16 kHz, mono
vocals lossless -> vocal-align.wav            loudnorm I=-20, pcm_s16le, 16 kHz, mono
vocals/background lossless -> artifact MP3    libmp3lame, 192k
```

No shell strings or unresolved paths are permitted.

- [ ] **Step 5: Implement lazy reusable Demucs separation**

Create a `DemucsSeparator` that lazily calls `demucs.pretrained.get_model(settings.demucs_model)`, chooses CUDA → MPS → CPU for `auto`, reuses the model, returns vocals directly, and sums every source whose name is not `vocals`. Guard model inference with a process lock because the singleton model is not request-reentrant.

- [ ] **Step 6: Implement transactional artifacts**

Write into `{artifact_id}.partial`, verify both MP3 files are non-empty, then atomically rename to `{artifact_id}`. Remove temporary files and `.partial` on failure. Never remove the completed artifact directory.

- [ ] **Step 7: Run media tests**

```bash
cd services/whisper-service
python -m unittest tests.test_media_pipeline -v
```

Expected: all tests pass without importing or downloading a real Demucs model.

- [ ] **Step 8: Commit only Task 2 files**

```bash
git add services/whisper-service/media_pipeline.py services/whisper-service/tests/test_media_pipeline.py
git commit --only services/whisper-service/media_pipeline.py services/whisper-service/tests/test_media_pipeline.py -m "feat: add persistent demucs audio artifacts"
```

---

### Task 3: Add faster-whisper canonical words and WhisperX alignment

**Files:**
- Create: `services/whisper-service/alignment.py`
- Create: `services/whisper-service/tests/test_alignment.py`
- Modify: `services/whisper-service/app.py`

**Interfaces:**
- Consumes: faster-whisper raw segments, detected language, vocal alignment path
- Produces: `WhisperAligner.align(words, raw_segments, language, audio_path) -> list[WordToken]`
- Guarantee: returns the original `words` unchanged on any alignment-specific exception

- [ ] **Step 1: Write failing alignment and fallback tests**

```python
def test_aligned_timestamps_replace_native_times_without_rewriting_words(self):
    aligned = self.aligner.align(self.native_words, self.raw_segments, "en", self.vocals)
    self.assertEqual([w.word for w in aligned], ["hello", "world"])
    self.assertEqual([(w.start, w.end) for w in aligned], [(0.12, 0.44), (0.51, 0.91)])

def test_unsupported_language_returns_native_word_objects(self):
    self.loader.side_effect = ValueError("unsupported language")
    aligned = self.aligner.align(self.native_words, self.raw_segments, "vi", self.vocals)
    self.assertEqual(aligned, self.native_words)

def test_unalignable_token_keeps_native_timestamp(self):
    self.whisperx_result = [{"word": "2014.", "start": None, "end": None}]
    aligned = self.aligner.align(self.native_words, self.raw_segments, "en", self.vocals)
    self.assertEqual((aligned[0].start, aligned[0].end), (1.0, 1.4))
```

- [ ] **Step 2: Run alignment tests and verify RED**

```bash
cd services/whisper-service
python -m unittest tests.test_alignment -v
```

- [ ] **Step 3: Make faster-whisper words canonical**

In `WhisperService`, retain leading whitespace in `raw_text`, trim only the public `word`, preserve native word timestamps and probability, and retain source-segment metrics. Keep `word_timestamps=True`, VAD, beam size, and model lazy loading.

- [ ] **Step 4: Implement WhisperX alignment as a replaceable timing layer**

Import WhisperX lazily. Load/cache the alignment model by `(language, device)`, call `whisperx.align()` with source segment text and the vocal alignment WAV, and overlay valid aligned timestamps onto canonical words in stable order. An aligned token with missing timestamps keeps its canonical native timestamps. Catch alignment-model lookup, download, load, and inference errors; log one warning and return the complete native list.

- [ ] **Step 5: Run alignment and settings tests**

```bash
cd services/whisper-service
python -m unittest tests.test_alignment tests.test_settings_models -v
```

- [ ] **Step 6: Commit only Task 3 files**

```bash
git add services/whisper-service/alignment.py services/whisper-service/tests/test_alignment.py services/whisper-service/app.py
git commit --only services/whisper-service/alignment.py services/whisper-service/tests/test_alignment.py services/whisper-service/app.py -m "feat: align whisper words against vocal audio"
```

---

### Task 4: Port deterministic spaCy segmentation with Vietnamese support

**Files:**
- Create: `services/whisper-service/segmentation.py`
- Create: `services/whisper-service/tests/test_segmentation.py`

**Interfaces:**
- Consumes: `list[WordToken]`, ISO language code
- Produces: `SpacySegmenter.preliminary_groups(words, language) -> list[list[WordToken]]`
- Produces: `reconstruct_segments(groups) -> list[TranscriptionSegment]`

- [ ] **Step 1: Write failing timestamp and boundary tests**

Cover punctuation, pauses, dependency-aware commas, connectors, roots, Vietnamese, parserless fallback, and exact reconstruction:

```python
def test_vietnamese_uses_multilingual_senter_and_never_english_parser(self):
    groups = self.segmenter.preliminary_groups(self.vi_words, "vi")
    self.assertEqual(self.loader.requested_models, ["xx_sent_ud_sm"])
    self.assertEqual([" ".join(w.word for w in g) for g in groups], [
        "Tôi muốn đi",
        "nhưng trời đang mưa.",
    ])

def test_spacy_character_boundary_maps_to_original_word_timestamp(self):
    groups = self.segmenter.preliminary_groups(self.words, "en")
    self.assertEqual(groups[1][0].start, self.words[4].start)

def test_parserless_pipeline_does_not_read_dependency_annotations(self):
    self.fallback_doc.has_annotation.return_value = False
    groups = self.segmenter.preliminary_groups(self.words, "xx")
    self.assertTrue(groups)

def test_reconstruction_is_lossless_and_monotonic(self):
    segments = reconstruct_segments([self.words[:2], self.words[2:]])
    self.assertEqual([w.word for s in segments for w in s.words], [w.word for w in self.words])
    self.assertLessEqual(segments[0].end, segments[1].start)
```

- [ ] **Step 2: Run segmentation tests and verify RED**

```bash
cd services/whisper-service
python -m unittest tests.test_segmentation -v
```

- [ ] **Step 3: Implement timestamp repair and canonical text spans**

Repair invalid timestamps by clamping to zero, the previous end, and the next valid boundary. Render canonical text while storing each word's `[char_start, char_end)` span. Map every spaCy boundary to the first canonical word whose span intersects or follows it.

- [ ] **Step 4: Implement the pinned language map and lazy cache**

Use exactly:

```python
SPACY_MODELS = {
    "en": "en_core_web_sm",
    "ru": "ru_core_news_sm",
    "fr": "fr_core_news_sm",
    "ja": "ja_core_news_sm",
    "es": "es_core_news_sm",
    "de": "de_core_news_sm",
    "it": "it_core_news_sm",
    "zh": "zh_core_web_sm",
    "vi": "xx_sent_ud_sm",
}
```

All other languages use `xx_sent_ud_sm`. Cache loaded pipelines by model name.
Expose `validate_spacy_packages()` to verify every configured package can be
resolved without loading all parser weights into memory.

- [ ] **Step 5: Implement VideoLingo-inspired passes**

Apply passes in order: sentence marks, valid comma clauses, connectors with five context words per side, and long parsed sentences. Run dependency logic only when both `DEP` and `POS` annotations exist. For Vietnamese add the approved connector phrases and require at least three source words on both sides. Add pause boundaries at gaps of at least 0.8 seconds. Preserve punctuation-only tokens with the preceding group.

- [ ] **Step 6: Implement final reconstruction**

Assign sequential IDs. Segment start/end come from first/last words. Aggregate `avg_logprob` and `no_speech_prob` as word-count-weighted source values. Reconstruct text from `raw_text` and trim only outer whitespace.

- [ ] **Step 7: Run segmentation tests**

```bash
cd services/whisper-service
python -m unittest tests.test_segmentation -v
```

- [ ] **Step 8: Commit only Task 4 files**

```bash
git add services/whisper-service/segmentation.py services/whisper-service/tests/test_segmentation.py
git commit --only services/whisper-service/segmentation.py services/whisper-service/tests/test_segmentation.py -m "feat: add multilingual spacy transcript segmentation"
```

---

### Task 5: Add validated semantic splitting and Whisper orchestration

**Files:**
- Create: `services/whisper-service/semantic_client.py`
- Create: `services/whisper-service/pipeline.py`
- Create: `services/whisper-service/tests/test_semantic_client.py`
- Create: `services/whisper-service/tests/test_pipeline.py`

**Interfaces:**
- Produces: `SemanticClient.split(words, language, candidates) -> list[list[WordToken]]`
- Produces: `TranscriptionPipeline.run(source_path, language, artifact_id) -> TranscriptionResult`
- Consumes: media, ASR, alignment, spaCy segmenter, and AI-backend refinement endpoint

- [ ] **Step 1: Write failing semantic validation tests**

```python
def test_valid_indexes_split_without_changing_words(self):
    self.transport.responses = [{"split_after": [8, 17]}]
    parts = self.client.split(self.words, "en", self.candidates)
    self.assertEqual([len(p) for p in parts], [9, 9, 3])
    self.assertEqual([w.word for p in parts for w in p], [w.word for w in self.words])

def test_invalid_boundaries_retry_three_times_then_fail(self):
    self.transport.responses = [
        {"split_after": [99]},
        {"split_after": [1, 1]},
        {"split_after": []},
    ]
    with self.assertRaises(SemanticSegmentationError):
        self.client.split(self.words, "en", [])
    self.assertEqual(self.transport.call_count, 3)

def test_connection_failure_is_not_a_deterministic_fallback(self):
    self.transport.error = TimeoutError()
    with self.assertRaises(SemanticSegmentationError):
        self.client.split(self.words, "en", [])
```

- [ ] **Step 2: Write failing orchestration tests**

Verify call order `media -> ASR(original) -> align(vocals) -> spaCy -> semantic(long only) -> reconstruct`, temporary cleanup on success/error, and persistent artifact URLs in the result. Verify a short transcript never calls the semantic endpoint.

- [ ] **Step 3: Run both test modules and verify RED**

```bash
cd services/whisper-service
python -m unittest tests.test_semantic_client tests.test_pipeline -v
```

- [ ] **Step 4: Implement strict boundary validation**

Require a JSON object containing `split_after: list[int]`. Reject booleans, duplicates, unsorted/out-of-range indexes, non-final parts under three words, any part over 20 words, and any non-lossless reconstruction. Before calling the endpoint, partition groups over 60 words losslessly at the last deterministic candidate within each 60-word window; use balanced hard windows only when no candidate exists. On validation failure, include the prior validation message in the next attempt. A transport error fails immediately; invalid model data consumes up to three attempts.

- [ ] **Step 5: Implement the typed httpx transport**

POST to `{AI_BACKEND_URL}/api/internal/transcription/refine` with timeout `SEMANTIC_TIMEOUT_SECONDS`. Send indexed words and deterministic candidates only. Convert non-2xx, connection, timeout, JSON, and schema errors into `SemanticSegmentationError` without including transcript text in public errors.

- [ ] **Step 6: Implement pipeline orchestration**

Use constructor injection for all stages. Invoke semantic splitting only for preliminary groups longer than `semantic_max_words`. Always clean temporary inputs in `finally`. Preserve completed artifacts only after media success. Build Whisper-local URLs `/artifacts/{artifact_id}/vocals` and `/artifacts/{artifact_id}/background`.

- [ ] **Step 7: Run Whisper unit suite**

```bash
cd services/whisper-service
python -m unittest discover -s tests -v
```

- [ ] **Step 8: Commit only Task 5 files**

```bash
git add services/whisper-service/semantic_client.py services/whisper-service/pipeline.py services/whisper-service/tests/test_semantic_client.py services/whisper-service/tests/test_pipeline.py
git commit --only services/whisper-service/semantic_client.py services/whisper-service/pipeline.py services/whisper-service/tests/test_semantic_client.py services/whisper-service/tests/test_pipeline.py -m "feat: orchestrate semantic whisper segmentation"
```

---

### Task 6: Add the AI-backend semantic refinement endpoint

**Files:**
- Create: `services/ai-backend/app/routes/transcription_refine.py`
- Create: `services/ai-backend/tests/test_transcription_refine.py`
- Modify: `services/ai-backend/app/main.py`

**Interfaces:**
- Consumes: indexed words, language, candidate boundaries, min/max limits, attempt feedback
- Produces: `POST /api/internal/transcription/refine -> {"split_after": list[int]}`
- Uses: `llm_backend.check_available()` and `llm_backend.generate_json()`

- [ ] **Step 1: Write failing endpoint/service tests**

Use `unittest.IsolatedAsyncioTestCase` and patch the module-local `llm_backend`.

```python
async def test_refine_returns_only_integer_boundaries(self):
    llm_backend.check_available.return_value = True
    llm_backend.generate_json.return_value = {"split_after": [8, 17]}
    result = await refine_transcription(self.request)
    self.assertEqual(result.model_dump(), {"split_after": [8, 17]})

async def test_unavailable_llm_returns_503(self):
    llm_backend.check_available.return_value = False
    with self.assertRaises(HTTPException) as raised:
        await refine_transcription(self.request)
    self.assertEqual(raised.exception.status_code, 503)

async def test_prompt_contains_indexed_words_but_forbids_rewriting(self):
    await refine_transcription(self.request)
    prompt = llm_backend.generate_json.call_args.kwargs["prompt"]
    self.assertIn("0:", prompt)
    self.assertIn("Return only split_after indexes", prompt)
```

- [ ] **Step 2: Run tests and verify RED**

```bash
cd services/ai-backend
PYTHONPATH=. python -m unittest tests.test_transcription_refine -v
```

- [ ] **Step 3: Implement bounded Pydantic request/response models**

Limit request words to 60, word length to 200 characters, candidates to 59, language to 16 characters, min words to 1–20, and max words to 2–60. Require unique contiguous input indexes beginning at zero.

- [ ] **Step 4: Implement the VideoLingo-derived prompt**

Ask for coherent, balanced parts; prefer punctuation, clauses, connectors, and pause candidates; require every part within supplied limits; and explicitly prohibit rewriting, translating, adding, or deleting words. Use `generate_json()` and return only validated integer indexes. Map unavailable inference to 503, malformed output to 502, and invalid requests to 422.

- [ ] **Step 5: Register the router and run backend tests**

```bash
cd services/ai-backend
PYTHONPATH=. python -m unittest discover -s tests -v
```

- [ ] **Step 6: Commit only Task 6 files**

```bash
git add services/ai-backend/app/routes/transcription_refine.py services/ai-backend/tests/test_transcription_refine.py services/ai-backend/app/main.py
git commit --only services/ai-backend/app/routes/transcription_refine.py services/ai-backend/tests/test_transcription_refine.py services/ai-backend/app/main.py -m "feat: add internal transcript refinement endpoint"
```

---

### Task 7: Integrate the public Whisper routes and artifact downloads

**Files:**
- Modify: `services/whisper-service/app.py`
- Create: `services/whisper-service/tests/test_app_routes.py`

**Interfaces:**
- Produces: `POST /transcribe -> TranscriptionResult`
- Produces: `GET /artifacts/{artifact_id}/{stem} -> audio/mpeg`
- Preserves: `/health`, `/models`, `/load`, `/unload`, and `/test`

- [ ] **Step 1: Write failing route tests**

Use `fastapi.testclient.TestClient`, replace the module-level transcription pipeline with a fake, and use a temporary upload/artifact root.

```python
def test_transcribe_returns_refined_result_and_artifact_paths(self):
    response = self.client.post(
        "/transcribe",
        files={"file": ("sample.wav", b"RIFF...", "audio/wav")},
    )
    self.assertEqual(response.status_code, 200)
    self.assertIn("separated_audio", response.json())

def test_artifact_route_serves_only_allowed_stems(self):
    ok = self.client.get(f"/artifacts/{self.artifact_id}/vocals")
    bad = self.client.get(f"/artifacts/{self.artifact_id}/../secret")
    self.assertEqual(ok.headers["content-type"], "audio/mpeg")
    self.assertIn(bad.status_code, {404, 422})

def test_semantic_failure_returns_stage_specific_error_and_cleans_upload(self):
    self.pipeline.error = SemanticSegmentationError("timeout")
    response = self.client.post("/transcribe", files=self.files)
    self.assertEqual(response.status_code, 502)
    self.assertFalse(any(self.upload_dir.iterdir()))
```

- [ ] **Step 2: Run route tests and verify RED**

```bash
cd services/whisper-service
python -m unittest tests.test_app_routes -v
```

- [ ] **Step 3: Replace inline endpoint processing with the pipeline**

Save uploads in chunks rather than reading the entire file into memory. Generate a full `str(uuid.uuid4())` artifact identifier, not the current eight-character upload suffix. Run CPU/model work in `asyncio.to_thread`. Preserve extension allowlisting and video support. Map media errors to 500, semantic upstream errors to 502/503, and validation errors to 400. Always unlink request uploads.

- [ ] **Step 4: Validate spaCy packages during application startup**

Add a FastAPI lifespan handler that calls `validate_spacy_packages()` before
serving requests. Missing or incompatible pinned pipeline packages fail startup;
heavy Demucs, ASR, and alignment weights remain lazy.

- [ ] **Step 5: Add artifact streaming**

Return `FileResponse(path, media_type="audio/mpeg", filename=f"{stem}.mp3")` only after safe resolver validation and existence checks. Completed artifacts are never unlinked by this route.

- [ ] **Step 6: Update health metadata**

Expose configured Demucs model, semantic maximum, spaCy enabled state, WhisperX alignment enabled state, and artifact directory readiness without loading heavy models during `/health`.

- [ ] **Step 7: Run the full Whisper suite**

```bash
cd services/whisper-service
python -m unittest discover -s tests -v
```

- [ ] **Step 8: Commit only Task 7 files**

```bash
git add services/whisper-service/app.py services/whisper-service/tests/test_app_routes.py
git commit --only services/whisper-service/app.py services/whisper-service/tests/test_app_routes.py -m "feat: expose enriched transcription and stem downloads"
```

---

### Task 8: Proxy artifacts through the AI backend and expose web types

**Files:**
- Modify: `services/ai-backend/app/routes/transcribe.py`
- Create: `services/ai-backend/tests/test_transcription_proxy.py`
- Modify: `apps/web/src/types/ai.ts`
- Modify: `apps/web/src/types/transcription.ts`

**Interfaces:**
- Produces: `GET /api/transcribe/artifacts/{artifact_id}/{stem}`
- Rewrites: `/artifacts/{id}/{stem}` to `/api/transcribe/artifacts/{id}/{stem}`
- Adds: `SeparatedAudio` TypeScript interface and the `separated_audio` JSON field

- [ ] **Step 1: Write failing proxy tests**

```python
async def test_transcribe_rewrites_both_whisper_artifact_urls(self):
    artifact_id = "7ec1c6ec-6eb9-45f4-846c-f11a345c4bc2"
    downstream = {
        "separated_audio": {
            "vocals_url": f"/artifacts/{artifact_id}/vocals",
            "background_url": f"/artifacts/{artifact_id}/background",
        }
    }
    result = await transcribe(self.upload)
    self.assertEqual(
        result["separated_audio"]["vocals_url"],
        f"/api/transcribe/artifacts/{artifact_id}/vocals",
    )

async def test_artifact_proxy_rejects_unknown_stem_before_downstream_call(self):
    with self.assertRaises(HTTPException) as raised:
        await proxy_artifact(self.artifact_id, "secret")
    self.assertEqual(raised.exception.status_code, 422)
```

- [ ] **Step 2: Run proxy tests and verify RED**

```bash
cd services/ai-backend
PYTHONPATH=. python -m unittest tests.test_transcription_proxy -v
```

- [ ] **Step 3: Implement URL rewriting and streaming proxy**

Validate UUID and stem locally. Return a `StreamingResponse` whose async iterator opens `httpx.AsyncClient` and `client.stream()` inside the iterator so both contexts remain alive until the final byte is yielded. Preserve `content-length`, `content-type`, and content disposition. Map connect errors to 503 and downstream 404 to 404. Do not buffer the entire MP3.

- [ ] **Step 4: Update both TypeScript response definitions**

Add `SeparatedAudio` to both files with these concrete response declarations:

```typescript
export interface SeparatedAudio {
	vocals_url: string;
	background_url: string;
}

// apps/web/src/types/ai.ts
export interface TranscriptionResult {
	segments: TranscriptionSegment[];
	language: string;
	duration: number;
	separated_audio?: SeparatedAudio;
}

// apps/web/src/types/transcription.ts
export interface TranscriptionResult {
	text: string;
	segments: TranscriptionSegment[];
	language: string;
	separated_audio?: SeparatedAudio;
}
```

Keep the field optional because Sarvam and Smallest transcription engines do not return Demucs artifacts.

- [ ] **Step 5: Run backend tests and web type/lint checks**

```bash
cd services/ai-backend
PYTHONPATH=. python -m unittest discover -s tests -v
cd ../../apps/web
bunx tsc --noEmit
bun run lint
```

- [ ] **Step 6: Commit only Task 8 files**

```bash
git add services/ai-backend/app/routes/transcribe.py services/ai-backend/tests/test_transcription_proxy.py apps/web/src/types/ai.ts apps/web/src/types/transcription.ts
git commit --only services/ai-backend/app/routes/transcribe.py services/ai-backend/tests/test_transcription_proxy.py apps/web/src/types/ai.ts apps/web/src/types/transcription.ts -m "feat: proxy separated whisper audio artifacts"
```

---

### Task 9: Pin the model stack and persist artifacts in Docker

**Files:**
- Modify: `services/whisper-service/requirements.txt`
- Create: `services/whisper-service/requirements-demucs.txt`
- Modify: `services/whisper-service/requirements.lock`
- Modify: `services/whisper-service/Dockerfile`
- Modify: `docker-compose.yml`
- Create: `services/whisper-service/tests/test_deployment_contract.py`

**Interfaces:**
- Produces: reproducible Python 3.11 image with WhisperX, Demucs, spaCy models, and FFmpeg
- Produces: named `whisper_artifacts` volume mounted at `/artifacts`

- [ ] **Step 1: Write a failing deployment-contract test**

```python
def test_compose_persists_artifacts_and_configures_ai_callback(self):
    compose = Path("../../docker-compose.yml").resolve().read_text()
    self.assertIn("whisper_artifacts:/artifacts", compose)
    self.assertIn("AI_BACKEND_URL=http://ai-backend:8420", compose)
    self.assertIn("whisper_artifacts:", compose)

def test_requirements_pin_whisperx_spacy_and_all_pipeline_wheels(self):
    requirements = Path("requirements.txt").read_text()
    for package in ("whisperx==3.8.5", "spacy==3.8.14", "xx_sent_ud_sm"):
        self.assertIn(package, requirements)
```

- [ ] **Step 2: Run deployment test and verify RED**

```bash
cd services/whisper-service
python -m unittest tests.test_deployment_contract -v
```

- [ ] **Step 3: Pin resolvable primary dependencies**

Set `whisperx==3.8.5`, `faster-whisper==1.2.1`, `spacy==3.8.14`, `httpx==0.27.0`, and direct wheel URLs for the eight `*_sm==3.8.0` pipelines plus `xx_sent_ud_sm==3.8.0`. Include Demucs runtime dependencies (`dora-search`, `einops`, `julius`, `lameenc`, `openunmix`, `soundfile`, `submitit`, and `treetable`) in the main requirements.

- [ ] **Step 4: Pin Demucs without its obsolete dependency metadata**

Put exactly this immutable source in `requirements-demucs.txt`:

```text
demucs @ git+https://github.com/adefossez/demucs@b9ab48cad45976ba42b2ff17b229c071f0df9390
```

Install it after the locked stack with:

```dockerfile
RUN uv pip install --system --no-deps -r requirements-demucs.txt
```

This mirrors the verified VideoLingo compatibility strategy and prevents Demucs' old torchaudio metadata from downgrading WhisperX's Torch 2.8 stack.

- [ ] **Step 5: Regenerate and inspect the universal lock**

```bash
uv pip compile services/whisper-service/requirements.txt \
  -o services/whisper-service/requirements.lock \
  --python-version 3.11 \
  --universal
```

Expected: successful resolution with Torch/Torchaudio 2.8-compatible WhisperX and all spaCy model wheels represented.

- [ ] **Step 6: Update Docker and Compose**

Copy `requirements-demucs.txt` before dependency installation. Create `/artifacts`. Add to `whisper-service.environment`:

```yaml
- AI_BACKEND_URL=http://ai-backend:8420
- ARTIFACT_DIR=/artifacts
- DEMUCS_MODEL=htdemucs
- DEMUCS_DEVICE=auto
- DEMUCS_MP3_BITRATE=192k
- WHISPERX_ALIGNMENT_ENABLED=true
- WHISPERX_DEVICE=auto
- SPACY_ENABLED=true
- SPACY_FALLBACK_MODEL=xx_sent_ud_sm
- SEMANTIC_SPLIT_ENABLED=true
- SEMANTIC_MAX_WORDS=20
- SEMANTIC_MIN_WORDS=3
- SEMANTIC_WINDOW_WORDS=60
- SEMANTIC_MAX_RETRIES=3
- SEMANTIC_TIMEOUT_SECONDS=300
```

Mount `whisper_artifacts:/artifacts` and declare `whisper_artifacts:` under top-level volumes.

- [ ] **Step 7: Run dependency and Compose verification**

```bash
cd services/whisper-service
python -m unittest tests.test_deployment_contract -v
cd ../..
docker compose config --quiet
```

- [ ] **Step 8: Build the Whisper image**

```bash
docker compose build whisper-service
```

Expected: dependency installation succeeds, all spaCy packages import, and the image completes without runtime model downloads.

- [ ] **Step 9: Commit only Task 9 files**

```bash
git add services/whisper-service/requirements.txt services/whisper-service/requirements-demucs.txt services/whisper-service/requirements.lock services/whisper-service/Dockerfile services/whisper-service/tests/test_deployment_contract.py docker-compose.yml
git commit --only services/whisper-service/requirements.txt services/whisper-service/requirements-demucs.txt services/whisper-service/requirements.lock services/whisper-service/Dockerfile services/whisper-service/tests/test_deployment_contract.py docker-compose.yml -m "build: package enriched whisper pipeline"
```

---

### Task 10: Run end-to-end contract verification

**Files:**
- Modify only if verification exposes a defect in files already owned by Tasks 1–9.

**Interfaces:**
- Verifies all approved public, internal, model-fallback, artifact, and deployment contracts.

- [ ] **Step 1: Run all Whisper tests**

```bash
cd services/whisper-service
python -m unittest discover -s tests -v
```

- [ ] **Step 2: Run all AI-backend tests**

```bash
cd services/ai-backend
PYTHONPATH=. python -m unittest discover -s tests -v
```

- [ ] **Step 3: Run web static checks**

```bash
cd apps/web
bunx tsc --noEmit
bun run lint
```

- [ ] **Step 4: Run deployment checks**

```bash
docker compose config --quiet
docker compose build whisper-service ai-backend
```

- [ ] **Step 5: Run a container smoke test without downloading ASR weights**

Start services, check `/health`, and verify the response reports Demucs, WhisperX, spaCy, semantic configuration, and writable artifact storage:

```bash
docker compose up -d whisper-service ai-backend
curl --fail http://localhost:8421/health
curl --fail http://localhost:8420/health
```

- [ ] **Step 6: Confirm the final diff is scoped**

```bash
git status --short
git diff --check
git diff --stat HEAD~10..HEAD
```

Verify unrelated pre-existing changes remain untouched and no generated model cache, upload, `.DS_Store`, or audio artifact is staged.

- [ ] **Step 7: Commit any verification-only correction**

If a defect required a code correction, commit only its exact files with a message describing that correction. If no correction was needed, do not create an empty commit.
