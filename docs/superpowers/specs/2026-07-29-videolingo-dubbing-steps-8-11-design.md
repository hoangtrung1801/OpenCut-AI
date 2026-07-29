# VideoLingo Dubbing Steps 8–11 Integration Design

## Goal

Integrate the behavior of VideoLingo steps 8.1, 8.2, 9, 10, and 11 into
OpenCut AI while reusing the existing Whisper, Demucs, contextual translation,
TTS, editor action, media, and command systems.

The completed workflow creates one individually editable dubbed audio clip for
each display caption, reuses the background stem already produced during
transcription, and mutes only the source media used for that transcription.

## Scope

This integration includes:

- preserving the Demucs vocal and background artifact references returned by
  Whisper step 2;
- constructing dubbing tasks from the existing audio-oriented translation
  segments and display-caption segments;
- resolving the voice mode explicitly selected in the AI Dubbing panel;
- generating speech through the existing `tts-service`;
- fitting generated speech to caption timing with chunk-level speed adjustment;
- returning individual WAV artifacts and retimed caption metadata;
- importing the background stem and speech clips into the editor;
- muting the transcribed source media; and
- applying timeline changes as one undoable action.

It does not include VideoLingo step 12 video rendering, a second Demucs pass,
source-speaker cloning, destructive replacement of existing dubbed tracks, or
Docker-based setup.

## Chosen Architecture

The AI backend owns dubbing orchestration. The existing `tts-service` remains a
focused speech-synthesis service, and the web remains responsible for importing
completed local artifacts into the editor.

This boundary was chosen over:

1. Browser orchestration, which would make FFmpeg timing, retries, long-running
   work, and cancellation unreliable.
2. TTS-service orchestration, which would couple the model service to Whisper
   artifacts, caption schemas, job progress, and editor behavior.

The service flow is:

```text
Whisper transcription
  -> transcript + persistent vocals/background URLs
  -> contextual translation + caption post-processing
  -> AI-backend dubbing job
      -> task construction and chunk planning
      -> existing tts-service generation
      -> FFmpeg speed fitting
      -> individual WAV clips + retimed caption metadata
  -> editor action
      -> persist background and clip media
      -> atomically update the timeline
```

## Existing Contracts Reused

### Demucs artifacts

`whisper-service` already runs Demucs during media preparation. It persists:

- `vocals.mp3`; and
- `background.mp3`, containing the sum of all non-vocal Demucs sources.

The transcription response exposes both through `separated_audio`. The AI
backend rewrites them to same-origin URLs under `/api/transcribe/artifacts/...`.
The web must retain those URLs instead of discarding them after transcription.
No later stage runs Demucs again.

### Translation granularity

The contextual translation workflow already produces two representations:

- `audio_segments`: original translation rows and timing parents; and
- `display_segments`: readable, potentially split caption lines with
  `parent_id` and `part_index`.

Dubbing uses both. Parent rows define chunk timing and tolerance. Display rows
define individual TTS calls, returned WAV files, and retimed captions.

### TTS voice inputs

The current TTS request supports:

- `speaker_wav` for a saved cloned voice;
- `speaker` for voice design; and
- neither field for automatic voice selection.

The new workflow passes one of these explicit modes to the existing TTS service.
It does not extract a source-speaker reference from the Demucs vocal stem.

## Public Dubbing API

### Create a job

`POST /api/dubbing/jobs` returns HTTP 202.

The request contains:

```json
{
  "source_language": "en",
  "target_language": "vi",
  "audio_segments": [
    {
      "id": 10,
      "source": "Hello.",
      "translation": "Xin chào.",
      "start": 2.0,
      "end": 3.2
    }
  ],
  "display_segments": [
    {
      "id": 20,
      "parent_id": 10,
      "part_index": 0,
      "source": "Hello.",
      "translation": "Xin chào.",
      "start": 2.0,
      "end": 3.2
    }
  ],
  "voice": {
    "mode": "design",
    "speaker": "female, young adult"
  },
  "pace": 1.0
}
```

`voice` is a discriminated union:

- clone: `{"mode": "clone", "speaker_wav": "<saved TTS path>"}`;
- design: `{"mode": "design", "speaker": "<non-empty description>"}`; or
- auto: `{"mode": "auto"}`.

Clone mode rejects `speaker`, design mode rejects `speaker_wav`, and auto mode
rejects both. The web sends the selected mode; the backend does not infer a
priority between populated fields. A clone path must be a normalized relative
path under `generated/voices/`, contain no `..` component, and use one of the
audio extensions already accepted by the TTS voice-upload route.

The accepted response is:

```json
{
  "job_id": "canonical-uuid",
  "status": "queued"
}
```

### Poll a job

`GET /api/dubbing/jobs/{job_id}` returns:

- `queued`;
- `preparing`;
- `generating`;
- `fitting`;
- `completed`; or
- `failed`.

In-progress responses include completed and total clip counts. Failed responses
include a stable public error code and an actionable, sanitized message.
Provider response bodies, prompts, local filesystem paths, and stack traces are
never returned.

The completed result contains:

```json
{
  "job_id": "canonical-uuid",
  "status": "completed",
  "result": {
    "clips": [
      {
        "id": 20,
        "parent_id": 10,
        "part_index": 0,
        "text": "Xin chào.",
        "start": 2.0,
        "end": 3.1,
        "duration": 1.1,
        "audio_url": "/generated/dubbing/canonical-uuid/clips/20.wav",
        "timing_warning": null
      }
    ],
    "captions": [
      {
        "id": 20,
        "parent_id": 10,
        "part_index": 0,
        "text": "Xin chào.",
        "start": 2.0,
        "end": 3.1
      }
    ],
    "srt": "1\n00:00:02,000 --> 00:00:03,100\nXin chào.\n"
  }
}
```

Generated paths are derived only from a server-generated UUID and validated
integer clip IDs. Request values are never interpolated into filesystem paths.

## Backend Components

### Dubbing schemas

A focused dubbing model module defines request validation, the voice union, job
states, clip metadata, public failure codes, and completed results. It reuses
translation field semantics without making the dubbing service depend on route
models.

Validation requires:

- distinct source and target languages;
- unique parent and display IDs;
- positive, finite, ordered timestamp ranges;
- every display `parent_id` to reference an audio segment;
- display parts for each parent to use contiguous `part_index` values;
- globally ordered, non-overlapping parent rows; and
- display rows to remain ordered within their parent range.

### Task construction

The task builder adapts VideoLingo steps 8.1 and 8.2 without Excel or SRT
intermediates:

1. Sort audio parents by start time.
2. Attach display rows by `parent_id` and `part_index`.
3. Remove parenthesized-only annotations and unsafe control characters from TTS
   text without changing the stored caption text.
4. Calculate each parent duration and following gap.
5. Cap usable tail tolerance at the configured limit.
6. End a timing chunk at a gap at least as large as the tolerance or after five
   parent rows, whichever comes first.

Display rows remain distinct tasks. Short display captions are not merged
because the user chose individually editable caption clips.

### Voice resolution

The selected mode is converted into the existing TTS JSON contract:

- clone -> `speaker_wav`;
- design -> `speaker`; and
- auto -> neither.

The same selected configuration applies to every clip in one job. The optional
`pace` is passed to the TTS service as its base `speed`.

### TTS generation

The AI backend checks TTS readiness before starting generation, then calls
`POST {TTS_SERVICE_URL}/generate` for every display task. Calls use bounded
concurrency so a local model is not flooded.

Each successful response must be a non-empty audio payload. It is written to a
job-private temporary WAV and measured with `ffprobe`. A zero-length, malformed,
or non-audio response fails the complete job.

The job does not retry a known validation failure. Transient connection or read
errors receive two additional attempts with short bounded backoff. The backend
does not ask an LLM to rewrite spoken content after translation approval.

### Chunk fitting

The timing fitter adapts VideoLingo step 10:

1. Sum generated clip durations and original internal gaps for each chunk.
2. Prefer preserving gaps when the result fits at or below the accepted speed.
3. Otherwise remove internal slack before increasing speed.
4. Apply one speed factor to the whole chunk, capped at the hard maximum.
5. Use FFmpeg `atempo` to create the final WAV for every display clip.
6. Place clips sequentially from the original chunk start, preserving original
   gaps only when the selected fit mode permits them.
7. Set caption start/end values directly from the fitted waveform placement.

Speech is never truncated. If a chunk still exceeds its allowed end at the hard
maximum speed, subsequent clips move forward enough to prevent speech overlap.
The affected clip receives `timing_warning: "overflow"`, and retimed captions
follow the moved speech. This favors complete, accessible speech over perfect
lip synchronization.

### Job storage and artifacts

The initial implementation uses an in-process, bounded job registry and local
artifact directories under:

`GENERATED_DIR/dubbing/<job-id>/`

One AI-backend process owns a job. A backend restart makes an unfinished job
unavailable, while already completed WAV files remain local and readable.
No automatic deletion is added in this integration.

Only one dubbing job runs concurrently by default. Additional accepted jobs
wait in FIFO order. Per-job TTS concurrency defaults to two.

## Configuration

The AI backend adds these settings, all using the existing
`OPENCUTAI_` environment prefix:

| Setting | Default | Meaning |
| --- | ---: | --- |
| `DUBBING_MAX_CONCURRENT_JOBS` | `1` | Active local dubbing jobs |
| `DUBBING_MAX_TTS_CONCURRENCY` | `2` | Concurrent TTS requests within a job |
| `DUBBING_MAX_CHUNK_SEGMENTS` | `5` | Maximum audio-parent rows in a timing chunk |
| `DUBBING_ACCEPT_SPEED` | `1.2` | Preferred maximum fitted speed |
| `DUBBING_MAX_SPEED` | `1.4` | Hard maximum fitted speed |
| `DUBBING_GAP_TOLERANCE_SECONDS` | `1.5` | Maximum tail gap available to a chunk |
| `DUBBING_TTS_RETRIES` | `2` | Additional transient TTS attempts |

Validation requires positive values, `DUBBING_ACCEPT_SPEED <=
DUBBING_MAX_SPEED`, and speed values supported by the existing TTS and FFmpeg
contracts.

## Web State

The transcript store retains:

- `separatedAudio`, containing the rewritten vocal and background URLs; and
- `sourceMediaId`, identifying the media asset submitted for transcription.

The transcription caller that locates the timeline media ID writes it alongside
the transcription result. Timeline elements created by splitting the same
source retain that media ID and are therefore all recognized as source pieces.

Each stored translation retains:

- its audio-oriented parent segments;
- its display-caption segments; and
- the target subtitle track ID already maintained by the store.

The added fields remain optional during persistence migration so existing local
projects can load. Dubbing validation presents an actionable instruction to
retranscribe or retranslate when an older project lacks required fields.

## AI Dubbing Panel

The existing panel keeps its target-language control and exposes one explicit
voice mode:

1. **Cloned voice** — the user selects one saved voice from the existing voice
   library.
2. **Voice design** — the user enters a non-empty description.
3. **Auto voice** — no clone or design is sent.

Choosing a cloned voice disables the design input. Clearing the cloned voice
enables it again. An empty design resolves to auto only when the user has chosen
auto mode; design mode itself requires non-empty text.

The Start Dubbing button invokes a new `generate-dubbing` editor action. React
components use `useEditor()` only for reactive editor state and never call
timeline mutation methods for this operation.

If the selected target has no stored contextual translation, the action first
runs the existing contextual translation and caption post-processing workflow,
stores both granularities, and creates the translated subtitle track. It does
not use the old segment-by-segment translation loop.

The background-task UI reports:

- translating, when required;
- preparing;
- generating `n/total`;
- fitting;
- importing; and
- completed or failed.

## Timeline Application

The web downloads and persists every completed clip before changing timeline
state. It also fetches and persists the Demucs background stem unless that
artifact has already been imported for the current transcript.

The resulting timeline has:

- one reusable background audio track containing the full Demucs background;
- one new dubbed-speech audio track for each run; and
- the existing translated subtitle track retimed to match returned clips.

The action mutes every audio-capable timeline element whose `mediaId` equals
`sourceMediaId`. It does not mute unrelated music, recordings, effects, or
previous dubbing tracks.

After media persistence succeeds, the action builds the complete `after`
timeline state in memory and executes one `TracksSnapshotCommand` from the
current `before` state. Undo therefore restores source mute flags, track
contents, and caption timing together. Persisted media assets remain in the
project media library after undo, matching existing generated-media behavior.

Re-running dubbing:

- never deletes an existing speech track or media asset;
- creates a new speech track;
- reuses the imported background asset and track when available; and
- retimes the selected target subtitle track to the newest run.

## Error Handling

The backend uses stable public errors for:

- invalid dubbing input;
- TTS service unavailable or model not loaded;
- TTS generation failure;
- malformed audio response;
- FFmpeg or ffprobe unavailable;
- timing-fit failure caused by corrupt input; and
- job not found after restart.

The web performs no timeline mutation for a failed or incomplete job. If media
download or persistence fails after backend completion, the action reports the
failed import and also leaves the timeline unchanged.

Source muting requires an exact stored media ID. Missing Demucs background data
or a missing source ID fails before job creation and instructs the user to
transcribe the source again.

## Privacy and Security

- All artifacts remain on local services.
- The AI backend accepts no arbitrary source URL or filesystem output path.
- Voice clone paths are normalized relative paths under `generated/voices/`;
  absolute paths, traversal components, unexpected prefixes, and unsupported
  extensions are rejected before a TTS request is made.
- Job IDs are canonical UUIDs.
- Artifact routes validate job and clip identifiers before resolving paths.
- Logs include job IDs, phase, counts, and exception classes, but not caption
  text, voice descriptions, provider bodies, or local voice paths.
- API failures never expose internal stack traces.

## Testing Strategy

### AI backend

Unit tests cover:

- all three voice union modes and invalid mixed modes;
- parent/display validation and deterministic ordering;
- five-row and pause-based chunk boundaries;
- gap-preserving and gap-removing fits;
- accepted-speed and hard-speed behavior;
- no-truncation overflow with sequential, non-overlapping clips;
- retimed caption/SRT generation;
- transient TTS retries and permanent failures;
- zero-length and malformed audio rejection;
- artifact identifier and traversal protection; and
- job state/progress transitions.

Route tests inject a fake orchestrator and verify accepted, polling, completed,
failed, invalid-ID, and missing-job responses without loading TTS models.

### TTS service

Existing adapter tests remain authoritative for clone, design, and auto request
mapping. No new orchestration logic is placed in this service.

### Web

Tests cover:

- preservation of `separated_audio` and `sourceMediaId`;
- persistence of both translation granularities;
- exact request mapping for clone, design, and auto modes;
- polling and public failure rendering;
- `invokeAction("generate-dubbing", ...)` from the panel;
- contextual translation fallback when a target is absent;
- background asset import and reuse;
- one clip element per display caption;
- source-media-only muting;
- unrelated audio preservation;
- retimed subtitle elements;
- no timeline changes on job or import failure; and
- one-step undo restoration.

No test requires Docker, a TTS model download, or a real LLM call. FFmpeg-facing
unit tests use injected command runners and small deterministic WAV fixtures.

## Success Criteria

The integration is complete when:

1. A transcription retains its Demucs stem references and exact source media
   identity.
2. A user can choose cloned, designed, or automatic voice behavior in AI
   Dubbing.
3. Starting dubbing runs through the action system and uses contextual
   translation data.
4. The existing TTS service produces one final fitted WAV per display caption.
5. Long generated speech is never truncated and returned clips do not overlap.
6. The editor reuses the Demucs background, creates a new speech track, retimes
   translated captions, and mutes only the transcribed source.
7. Undo restores the complete previous timeline state in one step.
8. Existing tracks and generated assets are never destructively deleted.
9. Automated tests pass without Docker or model downloads.
