# WhisperX, Demucs, spaCy, and Semantic Segmentation Design

## Goal

Improve `services/whisper-service` by adapting VideoLingo's Demucs,
WhisperX, spaCy, and semantic workflow. Every transcription separates vocals
from background audio, transcribes the original mix with faster-whisper, aligns
the transcript against the vocal stem when a compatible WhisperX model is
available, applies language-aware deterministic segmentation, returns
persistent download URLs for both stems, and preserves word timestamps through
semantic segmentation.

Semantic splitting is enabled by default. When a sentence needs semantic
refinement, failure to reach the AI backend, invoke an LLM, or validate the LLM
result must fail the transcription request. Short sentences that need no
semantic refinement do not require an LLM call.

## Context

The current Whisper service sends the uploaded media directly to
faster-whisper and returns the segments chosen by the model. Background music
can reduce recognition quality, and model-defined boundaries are not
consistently natural sentence or subtitle boundaries. The service deletes its
temporary upload after each request and returns no reusable audio artifacts.

VideoLingo addresses these concerns in four stages:

1. Demucs separates vocals from the other audio sources.
2. faster-whisper transcribes the original audio and WhisperX aligns the
   transcript against the separated vocal audio.
3. ASR is flattened into cleaned word-level data.
4. Deterministic spaCy passes split the word stream at punctuation, commas,
   connectors, and grammatical roots.
5. An LLM refines sentences that remain longer than the configured limit.

OpenCut should preserve that shape without copying VideoLingo's file-based
pipeline, request-time model downloads, or text-rematching through
`difflib.SequenceMatcher`. OpenCut already has word timestamps in memory and a
separate AI backend that owns LLM routing.

## Chosen Architecture

`POST /transcribe` in `services/whisper-service` owns the complete public
pipeline:

1. Uploaded audio, or lossless audio extracted from uploaded video, is decoded
   at source quality for Demucs.
2. Demucs `htdemucs` separates a vocal stem from the sum of all non-vocal
   sources.
3. Both stems are encoded as persistent 192 kbps MP3 artifacts.
4. faster-whisper transcribes a normalized copy of the original mix and
   produces raw segments with native word timestamps.
5. WhisperX forced-aligns the transcript against a normalized copy of the
   separated vocal stem when it can load a compatible language model.
6. The native faster-whisper timings remain the fallback when WhisperX
   alignment is unsupported or unavailable.
7. A local deterministic spaCy segmentation module cleans and groups the word
   stream.
8. Groups longer than the configured maximum are sent to a new internal AI
   backend endpoint.
9. The AI backend asks its existing `llm_backend` to choose word-boundary
   indexes.
10. Whisper validates those indexes and reconstructs final segments exclusively
   from the original ASR words.

The internal request direction is:

```text
client
  -> AI backend /api/transcribe proxy
     -> Whisper /transcribe
        -> persistent vocals.mp3 + background.mp3
        -> AI backend /api/internal/transcription/refine
        <- validated split indexes
     <- refined transcription + artifact identifiers
  <- refined transcription + AI-backend download URLs

client
  -> AI backend /api/transcribe/artifacts/{artifact_id}/{stem}
     -> Whisper /artifacts/{artifact_id}/{stem}
  <- persistent MP3 stream
```

The proxy route is asynchronous while waiting for Whisper, so the AI backend
can serve the internal refinement request without blocking on the original
request.

This architecture keeps media processing and public transcription behavior in
the Whisper service, reuses the AI backend's Ollama/TurboQuant selection,
timeouts, and JSON parsing, and avoids exposing Docker-internal hostnames to
the browser.

## Whisper-Side Components

The existing `app.py` remains the FastAPI entry point and model wrapper.
Audio separation and segmentation responsibilities move into focused modules
so media preparation, Demucs inference, artifact encoding, ASR inference,
WhisperX alignment, spaCy grouping, and remote semantic refinement can be
tested independently.

### Media preparation and Demucs separation

Each request receives a UUID artifact identifier. The service decodes the input
to a temporary lossless waveform while preserving its sample rate and channel
layout for separation. It does not downsample to 16 kHz mono before Demucs,
because doing so would discard information used by the separation model.

The separation module preloads and reuses the `htdemucs` model when practical,
selecting CUDA, then MPS, then CPU according to configured availability. It
uses Demucs' vocals output directly and sums every other returned source into
the background stem, matching VideoLingo's behavior.

The vocal and background tensors are written to temporary lossless files and
encoded through FFmpeg as:

```text
{ARTIFACT_DIR}/{artifact_id}/vocals.mp3
{ARTIFACT_DIR}/{artifact_id}/background.mp3
```

Both persistent outputs use 192 kbps MP3. Two temporary 16 kHz mono files are
prepared:

- the original mix is normalized for faster-whisper transcription; and
- the vocal stem is normalized to -20 dBFS for WhisperX alignment.

This matches VideoLingo's separation of transcription audio from alignment
audio and avoids making ASR text quality depend on Demucs artifacts. A
separation, normalization, or encoding failure fails the transcription request.
Partial artifact directories are removed after failures, while successfully
completed artifacts are never deleted automatically.

The artifact root is a dedicated persistent Docker volume, so completed stems
survive service and container restarts.

### Faster-whisper transcription and WhisperX alignment

faster-whisper remains the canonical ASR decoder. It runs with native word
timestamps enabled so a complete timed transcript exists before alignment.

WhisperX then loads the detected language's phoneme alignment model and aligns
the ASR segment text against the normalized vocal audio. Successfully aligned
timestamps replace native timestamps without changing the recognized text or
word order. Tokens that WhisperX cannot align retain their native
faster-whisper timestamps and then pass through the normal timestamp-repair
rules.

If the detected language has no configured WhisperX alignment model, the model
cannot be downloaded or loaded, or alignment fails, the service logs the
reason and returns the faster-whisper native word timestamps. An ASR decoding
failure still fails the request.

WhisperX diarization is not enabled. Speaker assignment remains outside this
feature and therefore requires no Hugging Face diarization token.

### Word representation and cleanup

Each internal word retains:

- the original token text, including Whisper's spacing information;
- the trimmed public word text;
- start and end timestamps;
- recognition probability;
- source-segment quality metrics.

The cleanup pass:

- removes empty tokens;
- repairs missing, negative, reversed, or non-monotonic timestamps using the
  closest valid timeline boundary;
- keeps recognized token text instead of dropping long words;
- preserves original order and never invents transcript text.

The returned public word model remains unchanged.

### Deterministic spaCy grouping

Raw faster-whisper segments are flattened before regrouping. The canonical word
stream is rendered to text with recorded character spans for every source word.
spaCy sentence and token boundaries are mapped back to those spans and then to
source word indexes. spaCy never rewrites the public transcript or owns its
timestamps.

For languages with an official parser used by the VideoLingo workflow, the
service loads a pinned small pipeline:

| Language | Pipeline |
| --- | --- |
| English | `en_core_web_sm` |
| Russian | `ru_core_news_sm` |
| French | `fr_core_news_sm` |
| Japanese | `ja_core_news_sm` |
| Spanish | `es_core_news_sm` |
| German | `de_core_news_sm` |
| Italian | `it_core_news_sm` |
| Chinese | `zh_core_web_sm` |

Small pipelines are sufficient because the workflow uses sentence boundaries,
part-of-speech tags, and dependency relations but does not use medium-model word
vectors. Every selected model is pinned and installed during the Docker build.
The service never downloads or installs a spaCy package while handling a
request.

For Vietnamese, spaCy has no official Vietnamese dependency parser. The service
uses the pinned multilingual `xx_sent_ud_sm` sentence recognizer, which includes
Vietnamese Universal Dependencies training data, plus conservative connector
rules for words and phrases such as `nhưng`, `vì`, `nên`, `nếu`, `mặc dù`,
`tuy nhiên`, `và`, and `hoặc`. It does not use an English parser for Vietnamese.

Other languages without a configured parser also use `xx_sent_ud_sm` for
sentence boundaries and language-aware punctuation rules. Dependency-based
comma, connector, and root logic runs only when the active pipeline provides
the required POS and dependency annotations.

Local boundary candidates are derived from:

- terminal punctuation;
- meaningful inter-word pauses;
- spaCy sentence boundaries;
- grammatical comma and connector positions when dependency annotations exist;
- conservative language-aware connectors for Vietnamese and parserless
  languages;
- dependency roots and verb/auxiliary boundaries in very long parsed sentences;
- the end of the source transcript; and
- balanced hard boundaries for unusually long unpunctuated speech.

The deterministic pass performs the role of VideoLingo's punctuation, comma,
connector, and long-sentence stages. Parserless language paths intentionally
avoid pretending that multilingual sentence recognition supplies grammatical
dependencies.

Groups containing at most `SEMANTIC_MAX_WORDS` words become final segments
immediately. The default is 20 words. Longer groups are divided into semantic
request windows of no more than `SEMANTIC_WINDOW_WORDS`, defaulting to 60, so
LLM prompts remain bounded.

### Semantic refinement client

For every oversized group, Whisper sends:

- the detected or requested language;
- the maximum and minimum words per result;
- ordered source words with stable numeric indexes;
- local candidate boundaries and their reasons.

The LLM does not return rewritten text. It returns only indexes after which a
split should occur, for example:

```json
{
  "split_after": [8, 17]
}
```

Whisper validates that boundaries are:

- integers;
- sorted and unique;
- inside the source-word range;
- sufficient to keep every part at or below the maximum;
- balanced so every non-final part contains at least the configured minimum;
  and
- lossless when applied to the original ordered words.

Invalid responses are retried up to `SEMANTIC_MAX_RETRIES`, defaulting to three
attempts. Validation feedback is included in the next request. Exhausting the
attempts fails transcription.

## AI-Backend Component

A new internal route,
`POST /api/internal/transcription/refine`, validates the bounded request and
uses `llm_backend.generate_json()`.

The prompt adapts VideoLingo's semantic splitting requirements:

- preserve coherent meaning;
- keep parts roughly balanced;
- prefer punctuation, clause, connector, and pause boundaries;
- keep each part within the supplied word limits; and
- return only source word indexes.

The route validates the basic response shape before returning it. Final
boundary and losslessness validation remains in Whisper, which owns the source
words and public transcription result.

The endpoint uses the existing backend-selection behavior. TurboQuant may be
used when configured and available; otherwise the existing LLM backend may
fall back to Ollama. If no configured route succeeds, the internal endpoint
returns an error and Whisper fails the public request.

## Public API and Artifact Downloads

The public `TranscriptionResult` keeps its existing fields:

- `text`
- `segments`
- `language`
- `duration`

It adds:

```json
{
  "separated_audio": {
    "vocals_url": "/api/transcribe/artifacts/{artifact_id}/vocals",
    "background_url": "/api/transcribe/artifacts/{artifact_id}/background"
  }
}
```

The added object is backward compatible with clients that ignore unknown JSON
properties. AI-backend and frontend transcription types are updated so new
callers can use both URLs.

Each final segment retains:

- a sequential `id`;
- text reconstructed from original Whisper tokens;
- the first word's start and last word's end;
- the exact contributing public words and probabilities;
- aggregate `avg_logprob` and `no_speech_prob` values from contributing raw
  segments.

`TranscriptionResult.text` remains the complete transcript in source order.
Existing REST proxy, WebSocket, analysis, clip-detection, caption, and subtitle
callers receive refined segments without changing their current behavior.

Whisper exposes
`GET /artifacts/{artifact_id}/{stem}` for `vocals` and `background`. The route
validates the UUID and fixed stem allowlist before returning a file. The AI
backend exposes the corresponding
`GET /api/transcribe/artifacts/{artifact_id}/{stem}` proxy and rewrites
Whisper's internal artifact references in `/api/transcribe` responses to these
browser-safe URLs.

Artifacts are immutable after a successful response. They have no expiration
or automatic cleanup. Operators remove them only through direct volume
management outside this feature.

## Configuration

The Whisper service gains environment-based settings with these defaults:

| Setting | Default | Purpose |
| --- | --- | --- |
| `AI_BACKEND_URL` | `http://ai-backend:8420` in Compose | Internal refinement endpoint base URL |
| `ARTIFACT_DIR` | `/artifacts` in Compose | Persistent separated-audio root |
| `DEMUCS_MODEL` | `htdemucs` | Separation model |
| `DEMUCS_DEVICE` | `auto` | Selects CUDA, MPS, or CPU |
| `DEMUCS_MP3_BITRATE` | `192k` | Encoding bitrate for both persistent stems |
| `WHISPERX_ALIGNMENT_ENABLED` | `true` | Enables forced alignment when supported |
| `WHISPERX_DEVICE` | `auto` | Selects the alignment device |
| `SPACY_ENABLED` | `true` | Enables deterministic spaCy segmentation |
| `SPACY_FALLBACK_MODEL` | `xx_sent_ud_sm` | Sentence recognizer for Vietnamese and unsupported languages |
| `SEMANTIC_SPLIT_ENABLED` | `true` | Enables semantic segmentation by default |
| `SEMANTIC_MAX_WORDS` | `20` | Maximum words in a final segment |
| `SEMANTIC_MIN_WORDS` | `3` | Preferred minimum words in a non-final part |
| `SEMANTIC_WINDOW_WORDS` | `60` | Maximum words in one LLM refinement request |
| `SEMANTIC_MAX_RETRIES` | `3` | Maximum validated LLM attempts |
| `SEMANTIC_TIMEOUT_SECONDS` | `300` | Internal AI request timeout |

Although enabled by default, semantic refinement is invoked only for groups
over the configured maximum. The setting exists for controlled diagnostics and
tests, not as a public per-request opt-out.

Compose mounts a named `whisper_artifacts` volume at `/artifacts`. WhisperX,
Demucs, faster-whisper, spaCy, the selected spaCy pipeline wheels, and a
mutually compatible Torch audio stack are pinned in the Whisper service
requirements and lockfile. faster-whisper is upgraded from the current `1.0.3`
pin to the version required by the selected WhisperX release.

All spaCy pipeline packages are checked for availability and compatibility
during service startup. Active pipelines are loaded lazily and cached by
language so the service does not keep every parser in memory. A missing or
incompatible required package makes service startup fail rather than triggering
a network download during transcription.

## Failure Behavior

These media-processing conditions always fail `/transcribe`:

- source normalization or video-audio extraction failure;
- Demucs model loading or inference failure;
- missing vocal or background output;
- transcription or alignment-audio normalization failure;
- faster-whisper model loading or decoding failure;
- required spaCy pipeline validation failure at startup;
- MP3 encoding failure; or
- persistent artifact write failure.

WhisperX language-model discovery, download, loading, or alignment errors do
not fail transcription. They produce a warning and use native faster-whisper
word timestamps.

When semantic refinement is required, these conditions also fail
`/transcribe`:

- AI backend connection failure;
- refinement timeout;
- unavailable Ollama/TurboQuant model;
- non-success internal response;
- malformed JSON;
- missing or invalid split indexes; or
- exhausted validation retries.

The Whisper endpoint returns a concise stage-specific processing error and logs
the detailed cause server-side. Uploaded media, extracted temporary media,
lossless intermediate stems, and partial failed artifacts are removed in
`finally` blocks. Completed MP3 artifacts are retained permanently.

The AI backend proxy preserves the downstream status and useful error detail.
Internal validation errors use a client-error status; unavailable inference
uses a service-unavailable status; unexpected generation failures use a
gateway/server error status.

## Testing Strategy

Automated tests do not load faster-whisper models or contact a real LLM.

Whisper-side unit and contract tests cover:

- Demucs device selection and model reuse;
- vocal extraction and non-vocal source summation;
- 192 kbps MP3 encoding command construction;
- source-quality separation, original-mix ASR preparation, and -20 dBFS vocal
  alignment preparation;
- original-mix selection as the faster-whisper input;
- vocal-stem selection as the WhisperX alignment input;
- successful replacement of native timings with aligned timings;
- unsupported-language and alignment-error fallback to native timings;
- preservation of native timings for unalignable tokens;
- character-span mapping from spaCy boundaries to canonical ASR words;
- dedicated parser selection for the eight configured languages;
- Vietnamese `xx_sent_ud_sm` sentence boundaries and connector rules;
- Vietnamese and unsupported-language rejection of the English parser;
- dependency-aware comma, connector, and root boundaries;
- parserless behavior that does not require POS or dependency annotations;
- partial-artifact cleanup after processing failures;
- preservation of completed artifact files;
- artifact identifier and stem path validation;
- vocals and background download responses;
- empty-token removal;
- timestamp repair and monotonicity;
- punctuation, pause, connector, and hard-boundary grouping;
- short transcripts that do not call semantic refinement;
- valid split indexes and exact reconstruction;
- multilingual and punctuation-only inputs;
- malformed, duplicate, unsorted, and out-of-range boundaries;
- undersized and oversized resulting parts;
- three-attempt validation retry behavior;
- AI connection errors and timeouts;
- sequential segment IDs and aggregated quality metrics; and
- additive public response serialization with both separated-audio URLs.

AI-backend tests cover:

- artifact URL rewriting;
- safe artifact download proxying;
- missing artifact and downstream error propagation;
- internal request validation;
- prompt constraints and indexed input;
- valid `generate_json()` results;
- unavailable LLM behavior;
- malformed model responses; and
- error status propagation.

HTTP dependencies and model output are represented by narrow contract fakes.
Mocks are used only at the network and model boundaries; grouping,
reconstruction, and validation run as real production code.

## Scope Boundaries

This change does not:

- copy VideoLingo's Excel or temporary-file pipeline;
- add WhisperX speaker diarization;
- download spaCy or pipeline packages during a transcription request;
- add translation, subtitle rendering, or dubbing stages;
- allow the LLM to rewrite transcript words; or
- add artifact expiration or automatic deletion.
