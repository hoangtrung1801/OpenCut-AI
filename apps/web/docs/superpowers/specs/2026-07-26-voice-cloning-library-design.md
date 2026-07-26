# Voice cloning library for AI Dubbing (and Voiceover)

## Problem

The Dubbing panel (`ai-dubbing.tsx`) only offers a free-text "voice design" prompt for OmniVoice — no way to clone a reference voice from an audio sample. The Voiceover panel already has a clone-upload flow, but it's neither persistent (state resets on remount) nor functional: it sends `speakerWav` (camelCase) to the TTS service, which only reads `speaker_wav` (snake_case, no alias configured), so the reference audio is silently ignored server-side today.

## Goals

- Let the user clone a voice from an uploaded audio sample in the Dubbing panel.
- Persist cloned voices as a named library (localStorage, via Zustand `persist`) so they're selectable in future sessions, not just the current one.
- Share the library and its picker UI between the Dubbing and Voiceover panels rather than duplicating cloning logic.
- Fix the `speaker_wav` serialization bug so cloning actually reaches OmniVoice.

## Non-goals

- Server-side voice storage/listing (`/voices` endpoint) — out of scope; library is client-side only.
- Deleting the underlying reference audio file on the backend when a voice is removed from the library — no delete endpoint exists.
- Handling backend redeploys that wipe `VOICES_DIR` — a stale path just fails generation with a normal error toast.

## Data model

New store: `apps/web/src/stores/voice-library-store.ts`

```ts
export interface ClonedVoice {
  id: string;      // generateUUID()
  name: string;     // user-provided, defaults to filename minus extension
  path: string;      // path returned by POST /api/tts/clone-voice, used as speaker_wav
  createdAt: number;
}

interface VoiceLibraryState {
  voices: ClonedVoice[];
  addVoice: (voice: ClonedVoice) => void;
  removeVoice: (id: string) => void;
}
```

Wrapped in `persist` (pattern matches `stickers-store.ts`), persisted key `"voice-library"`.

`addVoice` semantics: if an existing voice has the same `name` (case-sensitive exact match), replace that entry's `path`/`createdAt` in place rather than appending a duplicate — this also matches backend behavior, since `POST /clone-voice` overwrites the file at the same sanitized-name path when re-uploaded under an identical name.

## Backend contract (unchanged, already exists)

- `POST /api/tts/clone-voice` (form: `name`, `file`) → `{ status, name, path }`. Already wired via `aiClient.cloneVoice()`.
- `POST /api/tts/generate` accepts `speaker_wav` (reference audio path, triggers `ref_audio` / voice cloning) or `speaker` (free-text, triggers `instruct` / voice design) — mutually exclusive; `speaker_wav` takes precedence if both were ever sent, but the UI never sends both.

## Client fix: `speaker_wav` serialization

`TTSRequest.speakerWav` (client, camelCase) currently gets `JSON.stringify`'d as-is, so it lands on the wire as `speakerWav`, which the backend's `TTSGenerateRequest` Pydantic model doesn't recognize and silently drops.

Fix in `apps/web/src/lib/ai-client.ts`, `generateSpeech()` and `generateSpeechBlob()`: build the request body explicitly instead of passing `request` straight through:

```ts
body: JSON.stringify({
  text: request.text,
  language: request.language,
  speaker_wav: request.speakerWav,
  speaker: request.speaker,
}),
```

## Shared component: `VoiceLibraryPicker`

New file: `apps/web/src/components/editor/ai/voice-library-picker.tsx`

Props:
```ts
interface VoiceLibraryPickerProps {
  selectedVoice: ClonedVoice | null;
  onSelect: (voice: ClonedVoice | null) => void;
}
```

Behavior:
- Reads `voices` from `useVoiceLibraryStore`.
- Renders a `Select` with a "None" option plus each saved voice's name; choosing one calls `onSelect(voice)`.
- Each saved voice has an inline remove ("x") control that calls `removeVoice(id)`; if the removed voice was selected, calls `onSelect(null)`.
- Below the select, a "Clone new voice" affordance (collapsed by default if the library is non-empty, expanded if empty): a `Input` for the voice name (defaults to the picked file's name minus extension, editable before upload) and a file picker (`.wav,.mp3,.flac,.ogg,.m4a`, matching the backend's accepted formats). On file pick, immediately calls `aiClient.cloneVoice(file, name)`, shows a spinner, then `addVoice()` + `onSelect(newVoice)` on success, or a `toast.error` on failure.

This mirrors the existing upload UX in `voiceover.tsx` (button + hidden file input) but adds the name field and persistence.

## Dubbing panel changes (`ai-dubbing.tsx`)

- Add local state `const [clonedVoice, setClonedVoice] = useState<ClonedVoice | null>(null)`.
- Render `<VoiceLibraryPicker selectedVoice={clonedVoice} onSelect={setClonedVoice} />` directly below the existing "Voice design" `Input`.
- Mutual exclusion: when `clonedVoice` is set, disable the "Voice design" `Input` (grey out, keep value but don't send it) and show a short note ("Voice design is overridden by the cloned voice above"), matching the existing Voiceover pattern. Clearing the cloned voice (select "None") re-enables it.
- `handleDub` passes `voiceClonePath: clonedVoice?.path` into `runDubbing(...)` alongside the existing `voiceDesign`.

## `use-ai-dubbing.ts` changes

- `DubbingOptions` gains `voiceClonePath?: string`.
- `buildLocalTTSRequest(text, language, voiceDesign?, voiceClonePath?)`: if `voiceClonePath` is set, use it for `request.speakerWav` and skip `speaker`; otherwise fall back to today's `voiceDesign` → `speaker` behavior.
- In `runDubbing`'s local-engine branch, call `buildLocalTTSRequest(translatedText, options.targetLanguage, options.voiceDesign, options.voiceClonePath)` (dropping the current `options.voiceDesign ?? options.voiceId` fallback, since `voiceId` is only meaningful for the Sarvam/Smallest engines and mixing it in here was accidental).

## Voiceover panel changes (`voiceover.tsx`)

- Remove `clonedVoicePath`, `clonedVoiceName`, `isUploading`, `fileInputRef`, `handleUploadVoice`, and the associated JSX block.
- Add `const [clonedVoice, setClonedVoice] = useState<ClonedVoice | null>(null)`; render `<VoiceLibraryPicker selectedVoice={clonedVoice} onSelect={setClonedVoice} />` in place of the removed block.
- `generateSpeech()`'s local branch: `speakerWav: clonedVoice?.path ?? undefined, speaker: clonedVoice ? undefined : voiceGender`.
- The existing "Auto-select cloning model when voice is uploaded" `useEffect` now triggers off `clonedVoice` instead of `clonedVoicePath`.
- The "Voice type is overridden by the cloned voice below" note now conditions on `clonedVoice`.

## Testing

- `apps/web/src/stores/__tests__/voice-library-store.test.ts`: add appends, add with duplicate name replaces in place, remove deletes by id.
- Update/extend `use-ai-dubbing` tests (if present) or add coverage for `buildLocalTTSRequest` with `voiceClonePath` set vs. unset vs. both `voiceDesign` and `voiceClonePath` unset.
- Manual verification against the running `tts-service`: clone a voice from the Dubbing panel, confirm it appears after a page reload, run a dub with it selected, confirm the generated audio uses the cloned reference (`speaker_wav` reaches `/generate`, not dropped).
