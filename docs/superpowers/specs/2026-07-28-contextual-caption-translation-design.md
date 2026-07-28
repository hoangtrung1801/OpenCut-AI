---
title: Contextual Caption Translation
description: Apply VideoLingo-style theme, terminology, and contextual translation to timestamped Whisper segments.
---

# Contextual caption translation design

## Goal

Replace the Captions panel's generic five-segment LLM translation with a
backend-owned workflow based on VideoLingo Steps 4.1 and 4.2:

1. infer the video's theme and target-language terminology from the completed
   source transcript;
2. translate semantic source segments with neighboring context and matching
   terminology; and
3. return the translated text with the original segment identity and timing.

The user initiates this workflow after transcription by selecting a target
language and choosing **Translate & add**. Transcription remains independently
usable when translation or its LLM provider is unavailable.

## Service boundaries

### Whisper service

`services/whisper-service` remains responsible for:

- Demucs vocal/background separation;
- ASR;
- WhisperX alignment with faster-whisper timestamp fallback;
- spaCy sentence segmentation; and
- semantic boundary refinement.

It returns the final source-language segments with stable `id`, `start`, `end`,
and word timestamps. It does not accept a target language and does not perform
theme extraction or translation.

### AI backend

`services/ai-backend` owns contextual translation because it already owns LLM
provider selection and application-level AI workflows. Add:

- `app/models/translation.py` for request and response models;
- `app/services/contextual_translation.py` for the Step 4.1 and Step 4.2
  orchestration; and
- `app/routes/translation.py` for the public API.

Register the translation router in `app/main.py`.

The existing internal transcription-refinement route remains narrowly focused
on sentence boundaries. Contextual translation must not be added to it.

### Web application

`apps/web` supplies the transcript and selected target language, shows
translation progress, stores the translated transcript, and adds the resulting
subtitle track to the editor timeline.

The UI must not build LLM prompts, infer terminology, or reconstruct response
lines from unstructured text.

## API contract

### Endpoint

`POST /api/translations/contextual`

### Request

```json
{
  "source_language": "vi",
  "target_language": "en",
  "segments": [
    {
      "id": 0,
      "text": "Xin chào mọi người.",
      "start": 1.25,
      "end": 3.4
    }
  ],
  "custom_terms": [
    {
      "source": "OpenCut",
      "target": "OpenCut",
      "note": "Product name; do not translate."
    }
  ]
}
```

Constraints:

- source and target languages are required and must differ;
- at least one non-empty segment is required;
- segment IDs must be unique and preserve source order;
- timestamps must be finite, non-negative, and `end >= start`;
- custom terms are optional; and
- request-size limits must reject unexpectedly large inputs before prompting
  the LLM.

### Response

```json
{
  "source_language": "vi",
  "target_language": "en",
  "theme": "An introduction to the OpenCut video editor.",
  "terminology": [
    {
      "source": "OpenCut",
      "target": "OpenCut",
      "note": "Product name; do not translate."
    }
  ],
  "segments": [
    {
      "id": 0,
      "source": "Xin chào mọi người.",
      "translation": "Hello everyone.",
      "start": 1.25,
      "end": 3.4
    }
  ]
}
```

The backend copies IDs and timestamps from the validated request. The LLM is
never trusted to generate timing or segment identity.

## Backend workflow

### Step 4.1: context extraction

Join the semantic source segment text in order and use a bounded prefix as the
LLM input. Ask for strict JSON containing:

- a concise video theme; and
- terminology entries with `source`, `target`, and `note`.

Merge optional custom terms after inferred terms. A custom term with the same
case-insensitive source text overrides the inferred entry.

Validate the complete structure. An invalid response is retried with the
validation error included in the correction prompt. Exhausted retries fail the
request; translation must not silently continue without required context.

### Step 4.2: contextual translation

Group semantic segments into bounded batches using both a character limit and a
maximum segment count. Each batch prompt includes:

- the extracted theme;
- the previous batch's final source segments;
- the following batch's first source segments;
- only terminology that occurs in the current batch; and
- numbered current segments.

Ask the LLM for strict JSON records containing the input segment ID and its
translation. Translate independent batches concurrently within a small bounded
limit, then restore original order.

For every batch, validate:

- response IDs exactly match the requested IDs;
- there are no missing, duplicate, or additional records;
- every translation is non-empty; and
- source order is unchanged after assembly.

An invalid batch receives bounded correction retries. If any batch ultimately
fails, the endpoint returns an error and no partial translation result.

The initial feature performs faithful, natural subtitle translation in one
pass. VideoLingo's optional reflective second pass and speech-duration
shortening are deliberately excluded. Speech-duration shortening belongs to a
future dubbing-specific workflow because shortening ordinary subtitles can
unnecessarily remove meaning.

### LLM ownership and privacy

Use `app.services.model_backend.llm_backend`, preserving its existing
Ollama/TurboQuant selection and fallback behavior. Do not add another provider
client inside the translation service.

The service does not persist transcripts, themes, terminology, or prompts to
new files. The web project's existing transcript state owns the returned
translation. Server-side persistent caching is outside this feature so that
private transcript text is not retained unexpectedly.

Translation limits are centralized in `app/config.py`. The initial defaults
use the VideoLingo batching behavior: at most 600 characters or ten segments
per translation batch, two concurrent batches, and two correction attempts
after the initial response. The context-extraction sample and total request
size also receive explicit configurable bounds. Tests use injected small
limits rather than depending on production defaults.

The existing Sarvam translation path remains available for supported Indian
language pairs. This first contextual endpoint replaces the generic local-LLM
translation path; it does not wrap or change Sarvam provider behavior.

## Web workflow

### Client

Add typed `translateTranscript()` support to `apps/web/src/lib/ai-client.ts`.
It sends the structured request to `/api/translations/contextual` and returns
the structured response. No response parsing based on line prefixes is allowed.

Add matching translation request, context, terminology, and translated-segment
types to the existing AI/transcription type modules.

### Action

Add a `translate-captions` AI action whose arguments include the target language
code and display name. The Captions button invokes this action instead of
calling editor managers directly.

The action handler:

1. reads source segments and detected language from the transcript store;
2. starts and updates an existing background task;
3. chooses the existing Sarvam path for supported Indian-language pairs or the
   contextual endpoint otherwise;
4. writes the translated transcript to the transcript store;
5. builds display chunks from translated timestamped segments; and
6. creates the translated subtitle track through internal editor/domain logic.

The action reports failures through the background task and toast systems.
Failed translation must leave the source transcript and existing subtitle
tracks unchanged.

### Button placement

Keep the control in **Captions → Add language**, below the current subtitle
track list:

```text
[ Target language                         ▾ ] [ Translate & add ]
```

The control is visible only when a non-empty transcript exists. Disable it
while translation is active or when no eligible target language is selected.
Languages already represented by an active subtitle track remain excluded from
the selector.

Show compact, truthful progress below the row. Because the initial API is one
non-streaming request, the local-LLM path has two client-observable phases:

- `Translating with video context…`
- `Adding subtitle track…`

For Sarvam, retain provider-specific progress text rather than claiming that
theme extraction is running. Detailed server-side phases or per-batch progress
would require a later streaming/job API and are outside this feature.

## Error behavior

- `400`/`422`: malformed language, segment, timestamp, or custom-term input;
- `503`: no usable LLM backend;
- `502`: provider inference failed or returned unusable output after retries;
- no fallback to source text when contextual translation fails;
- no partial translated track; and
- existing transcript, audio artifacts, and subtitle tracks are never deleted
  by a translation failure.

The web UI presents a concise error and leaves **Translate & add** available for
retry.

## Verification

Backend tests cover:

- context and custom-term merging;
- terminology filtering per batch;
- neighbor context construction;
- strict ID/count/order validation;
- out-of-order concurrent completion restored to source order;
- correction retries and exhausted-retry failure;
- preservation of request timestamps; and
- route status codes for validation, unavailable LLM, and provider failure.

Web tests cover:

- the structured API request and response types;
- button visibility and disabled state;
- action invocation with the selected language;
- progress and failure presentation;
- translated transcript-store updates;
- track creation only after a complete successful response; and
- retention of the existing Sarvam branch.

## Non-goals

- changing Whisper, WhisperX, Demucs, or semantic segmentation;
- translating automatically as part of `/transcribe`;
- persistent transcript or prompt caching;
- subtitle display-length algorithm changes;
- reflective translation passes;
- translation shortening for TTS;
- generating dubbed audio; and
- changing the existing Sarvam translation API.
