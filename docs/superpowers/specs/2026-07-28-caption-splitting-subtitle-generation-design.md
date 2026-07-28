# Caption Splitting and Subtitle Generation Design

**Date:** 2026-07-28

**Status:** Approved

## Objective

Integrate the behavior of VideoLingo stages `_5_split_sub.py` and
`_6_gen_sub.py` into OpenCut AI's existing contextual caption translation
workflow.

Long source and translated captions will become separate, precisely timed
timeline elements instead of remaining one long element with visually wrapped
text. The workflow will also expose aligned source, translated, and bilingual
subtitle documents while preserving the original translation granularity for
future dubbing.

## Scope

This work includes:

- multilingual weighted caption-length measurement;
- source-aware splitting at word and punctuation boundaries;
- LLM alignment of translated text to the final source parts;
- deterministic allocation of timestamps to every split part;
- separate display and audio-oriented translation segments;
- source, translated, and bilingual SRT/VTT generation;
- post-processing for both contextual and Sarvam translations;
- web timeline construction from final display segments; and
- tests for backend contracts, processing behavior, API integration, and web
  timeline behavior.

This work does not include:

- TTS or dubbed-audio generation;
- burning subtitles into exported video;
- persistent subtitle files on the ai-backend filesystem;
- automatic deletion of existing media, audio stems, tracks, or artifacts;
- a new user-facing button; or
- moving translation responsibilities into whisper-service.

## Reference Behavior

VideoLingo stage 5 splits a source/translation pair when either side exceeds a
display-length policy. It semantically divides the source, asks an LLM to align
the translation to those source parts, and retains both display-split and
remerged representations.

VideoLingo stage 6 recovers timestamps for the final source boundaries, closes
small positive gaps, and emits source, translated, and bilingual subtitle
files.

OpenCut AI will preserve these responsibilities while adapting them to an
in-memory API and an editable timeline:

- timestamps come directly from the word-level transcript whenever possible;
- subtitle documents are returned in the response rather than written to
  server storage;
- display segments become individual timeline text elements; and
- the original translation granularity remains available for future dubbing.

## Architecture

### Service ownership

The ai-backend owns stages 5 and 6.

This service already owns contextual translation and access to the configured
LLM backend. Translation-to-source alignment therefore remains adjacent to the
translation operation. Deterministic subtitle serialization also remains in
ai-backend through the existing subtitle service.

The whisper-service remains responsible for media preparation, ASR, alignment,
and source-language segmentation. It will not depend on translation or
subtitle-generation behavior.

The web app remains responsible for invoking user actions, storing transcript
and translation state, and creating editable timeline tracks. React components
continue to use `useEditor()`, and the existing `translate-captions` action
continues to be the user-triggered entry point.

### Processing units

The implementation will use focused units:

1. A subtitle-length module measures weighted multilingual text length.
2. A source splitter creates parts and assigns word-derived timestamps.
3. A translation aligner asks the LLM to map translation text to exact source
   parts and validates the result.
4. A display post-processor recursively applies splitting and gap adjustment.
5. A subtitle serializer emits monolingual and bilingual text documents.
6. The contextual translation service orchestrates translation followed by
   post-processing.
7. The web translation workflow consumes display segments and creates one
   timeline element for each.

These units expose typed contracts so their internals can be tested and changed
without coupling callers to implementation details.

## API Contract

### Request

`POST /api/translations/contextual` retains its current fields and extends each
input segment with optional word timings:

```json
{
  "source_language": "en",
  "target_language": "vi",
  "segments": [
    {
      "id": 0,
      "text": "A long source sentence that needs to be divided.",
      "start": 1.2,
      "end": 5.8,
      "words": [
        {
          "word": "A",
          "start": 1.2,
          "end": 1.35
        }
      ]
    }
  ],
  "custom_terms": []
}
```

Words are ordered, use absolute media timestamps, and must fall within their
parent segment. The `words` field defaults to an empty list for backward
compatibility.

### Response

The response retains the existing `segments` field unchanged and adds:

```json
{
  "segments": [],
  "display_segments": [
    {
      "id": 0,
      "parent_id": 0,
      "part_index": 0,
      "source": "A long source sentence",
      "translation": "Một câu nguồn dài",
      "start": 1.2,
      "end": 3.1
    }
  ],
  "audio_segments": [
    {
      "id": 0,
      "source": "A long source sentence that needs to be divided.",
      "translation": "Một câu nguồn dài cần được chia nhỏ.",
      "start": 1.2,
      "end": 5.8
    }
  ],
  "subtitles": {
    "source": {
      "srt": "...",
      "vtt": "..."
    },
    "translation": {
      "srt": "...",
      "vtt": "..."
    },
    "source_translation": {
      "srt": "...",
      "vtt": "..."
    },
    "translation_source": {
      "srt": "...",
      "vtt": "..."
    }
  }
}
```

`segments` and `audio_segments` use the original translated segment
granularity. `display_segments` uses the final split granularity. Keeping
`segments` prevents breaking current API clients; `audio_segments` makes the
dubbing intent explicit.

Subtitle documents are response values only. No server-side subtitle artifact
is created or deleted.

### Sarvam post-processing endpoint

`POST /api/translations/captions/post-process` accepts already translated
source/target pairs with the same optional source word timings. It returns
`display_segments`, `audio_segments`, and `subtitles` using the same models as
the contextual translation response.

The contextual translation service calls the shared post-processor directly
after translation. The web calls this endpoint only after Sarvam returns its
original-granularity translations. This keeps provider selection independent
from caption splitting while ensuring both providers produce identical display
contracts.

## Configuration

The ai-backend will define:

```text
CONTEXT_TRANSLATION_MAX_CAPTION_CHARS=32
CONTEXT_TRANSLATION_TARGET_LENGTH_MULTIPLIER=1.0
CONTEXT_TRANSLATION_SPLIT_PASSES=3
CONTEXT_TRANSLATION_MAX_SPLIT_PASSES=8
CONTEXT_TRANSLATION_GAP_CLOSE_SECONDS=1.0
```

The maximum length matches the web's
`DEFAULT_MAX_CHARS_PER_LINE = 32`. The backend value controls translated
caption processing; the web value controls original-language local caption
construction.

The target multiplier remains explicit so deployments can compensate for
visual differences between source and target scripts without changing the
weighted-length algorithm.

## Weighted Length

Length is measured per Unicode character:

| Character group | Weight |
| --- | ---: |
| CJK ideographs and Japanese kana | 1.75 |
| Korean Hangul | 1.5 |
| Thai | 1.0 |
| Full-width forms | 1.75 |
| Other characters, including Vietnamese Latin characters | 1.0 |

The source triggers splitting when its normal character count exceeds the
configured maximum.

The target triggers splitting when:

```text
weighted_length(translation) * target_multiplier > max_caption_chars
```

Whitespace is included consistently in the measured string. Vietnamese text
uses normal word-boundary splitting and retains diacritics.

## Source Splitting

### Preferred boundaries

The deterministic splitter prefers, in order:

1. sentence-ending punctuation near the balanced midpoint;
2. commas, semicolons, colons, dashes, and other phrase punctuation;
3. whitespace boundaries nearest the balanced midpoint; and
4. character boundaries only when a single token exceeds the limit.

The splitter does not rewrite, remove, duplicate, or reorder source text.
Joining the parts with the language-appropriate spacing rule must reconstruct
the normalized input.

### Recursive passes

Every oversized pair is divided into two parts. The result is checked again and
can be divided during the next pass. Processing uses three normal passes and
can adaptively continue up to eight total passes when target-language expansion
still exceeds the policy.

If a part still exceeds the limit after the eighth pass, or cannot be split into
two non-empty source parts, the workflow fails with a validation error. It does
not return an oversized partial result.

### Word-derived timestamps

When word timings are present, a source part starts at its first word's start
and ends at its last word's end.

Punctuation attached to a word stays with that word. A split cannot reorder or
reuse a timed word.

When an individual word is longer than the configured limit, it is divided by
character count and its duration is distributed proportionally across the
pieces.

### Timing fallback

If word timings are missing, incomplete, invalid, or cannot reconstruct the
source text, the segment duration is divided proportionally by the normalized
character length of each source part.

Fallback timing must:

- remain within the original segment;
- preserve part order;
- produce finite timestamps;
- ensure every part has `end > start`; and
- prevent overlap between adjacent parts.

## Translation Alignment

For every split parent segment, the LLM receives:

- source and target languages;
- the original source;
- the original translation;
- the exact ordered source parts; and
- stable part IDs.

It returns one non-empty translation for each part ID. It must not add, remove,
merge, reorder, or rename IDs.

Validation checks:

- response is strict JSON;
- the part list exists;
- IDs exactly match the requested order;
- every translation is a non-empty string;
- part count equals source part count; and
- rejoining the translated parts produces a non-empty display translation.

The aligner receives two correction retries after the initial attempt. Each
retry includes the previous validation error. Provider failures and exhausted
validation retries fail the whole translation request.

The original translation is retained unchanged in `segments` and
`audio_segments`; rejoining display translations is not used to overwrite it.

## Gap Adjustment

After all display segments are in source order, a positive gap smaller than one
second is closed by extending the preceding segment's end to the following
segment's start.

The algorithm does not:

- change the next segment's start;
- modify zero or negative gaps;
- close gaps of one second or more; or
- move a timestamp outside its parent source segment.

Because parent boundaries take precedence, gap closing only applies when the
extended end remains within the preceding parent segment's allowed end.

## Subtitle Generation

The subtitle serializer accepts final display segments and emits:

- source SRT;
- translated SRT;
- source-first bilingual SRT;
- translation-first bilingual SRT;
- source WebVTT;
- translated WebVTT;
- source-first bilingual WebVTT; and
- translation-first bilingual WebVTT.

Every display segment becomes one cue. Subtitle serialization does not perform
another visual line wrap because the display post-processor has already
enforced the 32-character policy.

SRT uses `HH:MM:SS,mmm`. WebVTT uses `HH:MM:SS.mmm`. Rounding carries into the
next second when necessary so a value such as `1.9996` does not produce an
invalid `...,1000` millisecond component.

Bilingual cues contain exactly two text lines in their selected language
order.

## Web Integration

### Contextual translation

The web request includes transcript word timings. After a successful response,
the translation workflow:

1. stores the original-granularity translated transcript;
2. converts every `display_segment` into a caption source segment;
3. creates one text element per display segment;
4. records the resulting subtitle track; and
5. completes the existing translation background task.

The workflow remains atomic. Store and timeline mutation happen only after the
backend returns a fully valid response.

### Sarvam translation

Sarvam continues to provide the translation itself. Its translated
original-granularity segments then pass through the same subtitle
post-processing contract so the displayed result follows the same length and
timing rules.

The web must not implement a second multilingual alignment algorithm. It sends
Sarvam results to `POST /api/translations/captions/post-process`; contextual
translation invokes the same service internally.

### Timeline behavior

`createSubtitleTrack` continues to create the track and text elements. Its input
changes from original translated segments to final display segments.

Each split part becomes a separate element with its own:

- content;
- start time;
- duration;
- language label; and
- existing caption style.

No new UI button is introduced. The existing **Translate & add** button invokes
the existing `translate-captions` action. The original **Add subtitles** flow
continues to use local word-aware splitting with the same 32-character default.

## Error Handling

Expected client errors return HTTP 422:

- structurally invalid word timestamps, including non-finite values, reversed
  ranges, or words outside their parent segment;
- duplicate or unordered IDs;
- impossible time ranges;
- request limit violations; and
- content that cannot satisfy the split policy.

Missing word timings and incomplete but structurally valid word coverage use
the proportional timing fallback and do not fail the request.

LLM alignment validation exhaustion returns HTTP 502. An unavailable configured
provider returns HTTP 503. Error responses do not include private provider
details or prompt contents.

On any post-processing failure:

- no translated timeline track is created;
- no translation or track is persisted in the web store;
- the background task becomes `error`; and
- existing transcript, tracks, stems, and artifacts remain unchanged.

## Testing Strategy

### ai-backend unit tests

Tests will cover:

- weighted CJK, Japanese, Korean, Thai, full-width, Latin, and Vietnamese text;
- source text that fits exactly at 32 characters;
- punctuation-preferred and whitespace fallback boundaries;
- Vietnamese splitting at word boundaries while retaining diacritics;
- recursive splitting across three normal and up to eight adaptive passes;
- single-token character splitting;
- exact word-derived timestamps;
- proportional timestamp fallback;
- ordered, finite, non-overlapping output;
- short-gap closing and preservation of larger gaps;
- malformed alignment JSON;
- missing, duplicate, reordered, and empty alignment parts;
- two correction retries followed by success or exhaustion;
- preservation of original audio-oriented translations;
- SRT and WebVTT timestamp formatting;
- source, translated, and both bilingual layouts; and
- millisecond rounding at second boundaries.

### ai-backend route tests

Tests will verify:

- optional request words remain backward compatible;
- contextual translation returns all new fields;
- Sarvam post-processing uses the same response contract;
- validation, provider, and alignment errors map to the intended status codes;
  and
- no server artifact is required for subtitle generation.

### web tests

Tests will verify:

- TypeScript request and response contracts include word and display segments;
- the API client sends words and receives enriched translation results;
- `translate-captions` uses `display_segments` for track construction;
- the original-granularity translation is stored separately;
- one timeline element is created per display segment;
- Sarvam results pass through ai-backend post-processing;
- action failure produces no partial store or timeline mutation; and
- the existing 32-character original-caption behavior remains intact.

### Verification

Completion requires:

- the complete ai-backend test suite;
- the complete whisper-service test suite, because the shared transcription
  contract is extended;
- the complete web test suite;
- `bunx tsc --noEmit`;
- Python bytecode compilation for modified backend modules; and
- `git diff --check`.

## Compatibility and Migration

Existing contextual translation consumers can continue reading `segments`.
Request words are optional, and all new response fields are additive.

The existing `/api/transcribe/subtitles` endpoint remains available. Its
serializer will reuse corrected timestamp formatting where practical, but its
current monolingual request contract does not need to change.

No stored transcript migration is required. New translated tracks created after
this feature will use display-split elements; existing project tracks remain
unchanged.
