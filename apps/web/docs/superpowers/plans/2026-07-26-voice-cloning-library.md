# Voice Cloning Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users clone a voice from an uploaded audio sample in the Dubbing panel, persist cloned voices as a named library across sessions (localStorage), and share that library with the Voiceover panel — while fixing a bug where cloned-voice reference audio was silently dropped by the backend.

**Architecture:** A new Zustand store (`voice-library-store.ts`, using the `persist` middleware) holds `{id, name, path, createdAt}` entries. A new shared component (`VoiceLibraryPicker`) renders a select of saved voices plus an inline upload-and-name form, calling the existing `aiClient.cloneVoice()` and writing into the store. Both `ai-dubbing.tsx` and `voiceover.tsx` render this component and thread the selected voice's `path` through to `aiClient.generateSpeechBlob()` as `speaker_wav`. A small serialization bug in `ai-client.ts` (camelCase `speakerWav` sent instead of the backend's expected `speaker_wav`) is fixed via a new pure `buildTTSRequestBody` helper.

**Tech Stack:** Next.js/React (TypeScript), Zustand (`persist` middleware), `bun:test` for unit tests, existing `sonner` toast conventions, existing `@/components/ui/*` primitives (Select, Input, Button, Badge, Spinner, Label).

## Global Constraints

- No React component tests exist in this repo (`bun:test` is used only for pure-logic files) — new UI (`VoiceLibraryPicker`, panel wiring) is verified manually against the running app, not via automated component tests. Pure logic (store reducers, `buildLocalTTSRequest`, `buildTTSRequestBody`) must have `bun:test` coverage, matching `src/hooks/__tests__/use-ai-dubbing.test.ts`.
- Tests run with `bun test <path>` from `apps/web/`.
- Follow existing code style: tabs for indentation, double quotes, no semicolons omitted (match surrounding file), `cn()` from `@/utils/ui` for conditional classNames.
- The backend's `/generate` endpoint treats `speaker_wav` (voice clone) and `speaker` (voice design text) as mutually exclusive — `speaker_wav` wins if a caller ever sent both, but the UI must never send both.
- Accepted clone upload formats (matches backend): `.wav`, `.mp3`, `.flac`, `.ogg` (existing Voiceover UI also allows `.m4a` client-side even though the backend's extension whitelist doesn't include it — preserve that existing behavior, do not tighten it).

---

### Task 1: Fix `speaker_wav` serialization bug in `ai-client.ts`

**Files:**
- Modify: `apps/web/src/lib/ai-client.ts:578-615`
- Test: `apps/web/src/lib/__tests__/ai-client.test.ts` (new)

**Interfaces:**
- Produces: `buildTTSRequestBody(request: TTSRequest): { text: string; language: string; speaker_wav?: string; speaker?: string }` — exported pure function, used by later tasks' understanding of what `generateSpeech`/`generateSpeechBlob` send on the wire.

- [ ] **Step 1: Write the failing test**

Create `apps/web/src/lib/__tests__/ai-client.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { buildTTSRequestBody } from "@/lib/ai-client";

describe("buildTTSRequestBody", () => {
	test("maps speakerWav to snake_case speaker_wav", () => {
		expect(
			buildTTSRequestBody({
				text: "Hello",
				language: "en",
				speakerWav: "generated/voices/alice.wav",
			}),
		).toEqual({
			text: "Hello",
			language: "en",
			speaker_wav: "generated/voices/alice.wav",
			speaker: undefined,
		});
	});

	test("passes through speaker for voice design", () => {
		expect(
			buildTTSRequestBody({
				text: "Hello",
				language: "en",
				speaker: "female, young adult",
			}),
		).toEqual({
			text: "Hello",
			language: "en",
			speaker_wav: undefined,
			speaker: "female, young adult",
		});
	});

	test("omits both when neither is set", () => {
		expect(
			buildTTSRequestBody({ text: "Hello", language: "en" }),
		).toEqual({
			text: "Hello",
			language: "en",
			speaker_wav: undefined,
			speaker: undefined,
		});
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && bun test src/lib/__tests__/ai-client.test.ts`
Expected: FAIL — `buildTTSRequestBody` is not exported from `@/lib/ai-client`.

- [ ] **Step 3: Add `buildTTSRequestBody` and use it in `generateSpeech`/`generateSpeechBlob`**

In `apps/web/src/lib/ai-client.ts`, add this exported function above the `AIClient`/service class definition (near the top-level helpers, e.g. right after `classifyError`):

```ts
export function buildTTSRequestBody(request: TTSRequest) {
	return {
		text: request.text,
		language: request.language,
		speaker_wav: request.speakerWav,
		speaker: request.speaker,
	};
}
```

Then replace lines 578-583 and 585-615 (`generateSpeech` and `generateSpeechBlob`) so both serialize via this helper instead of `JSON.stringify(request)`:

```ts
	async generateSpeech(request: TTSRequest): Promise<TTSResult> {
		return this.request<TTSResult>("/api/tts/generate", {
			method: "POST",
			body: JSON.stringify(buildTTSRequestBody(request)),
		});
	}

	async generateSpeechBlob(request: TTSRequest): Promise<Blob> {
		const url = `${this.baseUrl}/api/tts/generate`;
		const controller = new AbortController();
		const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

		try {
			const response = await fetch(url, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(buildTTSRequestBody(request)),
				signal: controller.signal,
			});

			if (!response.ok) {
				const errorBody = await response.text().catch(() => "Unknown error");
				throw new AIClientError(
					`TTS error (${response.status}): ${errorBody}`,
					response.status >= 500 ? "backend_error" : "network_error",
					response.status,
				);
			}

			return await response.blob();
		} catch (error) {
			if (error instanceof AIClientError) throw error;
			const classified = classifyError(error);
			throw new AIClientError(classified.message, classified.errorType);
		} finally {
			clearTimeout(timeoutId);
		}
	}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && bun test src/lib/__tests__/ai-client.test.ts`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/ai-client.ts apps/web/src/lib/__tests__/ai-client.test.ts
git commit -m "fix: serialize speaker_wav correctly for TTS voice cloning"
```

---

### Task 2: Voice library store

**Files:**
- Create: `apps/web/src/stores/voice-library-store.ts`
- Test: `apps/web/src/stores/__tests__/voice-library-store.test.ts` (new)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  ```ts
  export interface ClonedVoice { id: string; name: string; path: string; createdAt: number }
  export const useVoiceLibraryStore: UseBoundStore<...> // zustand hook
  // state shape: { voices: ClonedVoice[]; addVoice: (voice: ClonedVoice) => void; removeVoice: (id: string) => void }
  ```
  Later tasks (3, 4) call `useVoiceLibraryStore((s) => s.voices)`, `useVoiceLibraryStore((s) => s.addVoice)`, `useVoiceLibraryStore((s) => s.removeVoice)`.

- [ ] **Step 1: Write the failing test**

Create `apps/web/src/stores/__tests__/voice-library-store.test.ts`:

```ts
import { describe, expect, test, beforeEach } from "bun:test";
import { useVoiceLibraryStore } from "@/stores/voice-library-store";

function resetStore() {
	useVoiceLibraryStore.setState({ voices: [] });
}

describe("useVoiceLibraryStore", () => {
	beforeEach(resetStore);

	test("addVoice appends a new voice", () => {
		useVoiceLibraryStore.getState().addVoice({
			id: "1",
			name: "Alice",
			path: "generated/voices/alice.wav",
			createdAt: 1000,
		});

		expect(useVoiceLibraryStore.getState().voices).toEqual([
			{ id: "1", name: "Alice", path: "generated/voices/alice.wav", createdAt: 1000 },
		]);
	});

	test("addVoice with a duplicate name replaces the existing entry in place", () => {
		useVoiceLibraryStore.getState().addVoice({
			id: "1",
			name: "Alice",
			path: "generated/voices/alice.wav",
			createdAt: 1000,
		});
		useVoiceLibraryStore.getState().addVoice({
			id: "2",
			name: "Alice",
			path: "generated/voices/alice-v2.wav",
			createdAt: 2000,
		});

		const voices = useVoiceLibraryStore.getState().voices;
		expect(voices).toHaveLength(1);
		expect(voices[0]).toEqual({
			id: "2",
			name: "Alice",
			path: "generated/voices/alice-v2.wav",
			createdAt: 2000,
		});
	});

	test("removeVoice deletes by id", () => {
		useVoiceLibraryStore.getState().addVoice({
			id: "1",
			name: "Alice",
			path: "generated/voices/alice.wav",
			createdAt: 1000,
		});
		useVoiceLibraryStore.getState().addVoice({
			id: "2",
			name: "Bob",
			path: "generated/voices/bob.wav",
			createdAt: 2000,
		});

		useVoiceLibraryStore.getState().removeVoice("1");

		expect(useVoiceLibraryStore.getState().voices).toEqual([
			{ id: "2", name: "Bob", path: "generated/voices/bob.wav", createdAt: 2000 },
		]);
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && bun test src/stores/__tests__/voice-library-store.test.ts`
Expected: FAIL — cannot find module `@/stores/voice-library-store`.

- [ ] **Step 3: Implement the store**

Create `apps/web/src/stores/voice-library-store.ts`:

```ts
import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface ClonedVoice {
	id: string;
	name: string;
	path: string;
	createdAt: number;
}

interface VoiceLibraryState {
	voices: ClonedVoice[];
	addVoice: (voice: ClonedVoice) => void;
	removeVoice: (id: string) => void;
}

export const useVoiceLibraryStore = create<VoiceLibraryState>()(
	persist(
		(set) => ({
			voices: [],

			addVoice: (voice) =>
				set((state) => {
					const withoutSameName = state.voices.filter(
						(v) => v.name !== voice.name,
					);
					return { voices: [...withoutSameName, voice] };
				}),

			removeVoice: (id) =>
				set((state) => ({
					voices: state.voices.filter((v) => v.id !== id),
				})),
		}),
		{
			name: "voice-library",
		},
	),
);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && bun test src/stores/__tests__/voice-library-store.test.ts`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/stores/voice-library-store.ts apps/web/src/stores/__tests__/voice-library-store.test.ts
git commit -m "feat: add persisted voice library store"
```

---

### Task 3: Extend `use-ai-dubbing.ts` for cloned-voice support

**Files:**
- Modify: `apps/web/src/hooks/use-ai-dubbing.ts:15-42` (types + `buildLocalTTSRequest`), `:164-172` (local-engine call site)
- Test: `apps/web/src/hooks/__tests__/use-ai-dubbing.test.ts` (extend existing file)

**Interfaces:**
- Consumes: `TTSRequest` from `@/types/ai` (unchanged shape: `{ text, language, speakerWav?, speaker? }`).
- Produces:
  ```ts
  export interface DubbingOptions {
    targetLanguage: string;
    engine: DubbingEngine;
    voiceId?: string;
    voiceDesign?: string;
    voiceClonePath?: string;   // NEW
    pace?: number;
    segmentIndices?: number[];
  }
  export function buildLocalTTSRequest(
    text: string,
    language: string,
    voiceDesign?: string,
    voiceClonePath?: string,   // NEW 4th param
  ): TTSRequest
  ```
  Task 5 (`ai-dubbing.tsx`) passes `voiceClonePath` into `runDubbing(...)`.

- [ ] **Step 1: Write the failing test**

Append to `apps/web/src/hooks/__tests__/use-ai-dubbing.test.ts` (after the existing `describe` block, same file):

```ts
describe("buildLocalTTSRequest with voice cloning", () => {
	test("uses speakerWav and skips voice design when a clone path is given", () => {
		expect(
			buildLocalTTSRequest(
				"Hello",
				"en",
				"female, young adult",
				"generated/voices/alice.wav",
			),
		).toEqual({
			text: "Hello",
			language: "en",
			speakerWav: "generated/voices/alice.wav",
		});
	});

	test("falls back to voice design when no clone path is given", () => {
		expect(
			buildLocalTTSRequest("Hello", "en", "female, young adult", undefined),
		).toEqual({
			text: "Hello",
			language: "en",
			speaker: "female, young adult",
		});
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && bun test src/hooks/__tests__/use-ai-dubbing.test.ts`
Expected: FAIL — `buildLocalTTSRequest("Hello", "en", "female, young adult", "generated/voices/alice.wav")` currently returns `{ text: "Hello", language: "en", speaker: "female, young adult" }` (4th arg ignored), not matching the expected `speakerWav` result.

- [ ] **Step 3: Implement**

In `apps/web/src/hooks/use-ai-dubbing.ts`, replace lines 17-24 (`DubbingOptions`):

```ts
export interface DubbingOptions {
	targetLanguage: string;
	engine: DubbingEngine;
	voiceId?: string;
	voiceDesign?: string;
	voiceClonePath?: string;
	pace?: number;
	segmentIndices?: number[];
}
```

Replace lines 33-42 (`buildLocalTTSRequest`):

```ts
export function buildLocalTTSRequest(
	text: string,
	language: string,
	voiceDesign?: string,
	voiceClonePath?: string,
): TTSRequest {
	const request: TTSRequest = { text, language };
	if (voiceClonePath) {
		request.speakerWav = voiceClonePath;
		return request;
	}
	const speaker = voiceDesign?.trim();
	if (speaker) request.speaker = speaker;
	return request;
}
```

Replace lines 164-172 (the local-engine branch in `runDubbing`):

```ts
					} else {
						audioBlob = await aiClient.generateSpeechBlob(
							buildLocalTTSRequest(
								translatedText,
								options.targetLanguage,
								options.voiceDesign,
								options.voiceClonePath,
							),
						);
					}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && bun test src/hooks/__tests__/use-ai-dubbing.test.ts`
Expected: PASS (all tests in the file, including the 2 pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/hooks/use-ai-dubbing.ts apps/web/src/hooks/__tests__/use-ai-dubbing.test.ts
git commit -m "feat: support cloned voice path in local dubbing requests"
```

---

### Task 4: `VoiceLibraryPicker` shared component

**Files:**
- Create: `apps/web/src/components/editor/ai/voice-library-picker.tsx`

**Interfaces:**
- Consumes: `useVoiceLibraryStore` (Task 2), `aiClient.cloneVoice(file, name)` (existing, `apps/web/src/lib/ai-client.ts:617`).
- Produces:
  ```ts
  export interface VoiceLibraryPickerProps {
    selectedVoice: ClonedVoice | null;
    onSelect: (voice: ClonedVoice | null) => void;
  }
  export function VoiceLibraryPicker(props: VoiceLibraryPickerProps): JSX.Element
  ```
  Tasks 5 and 6 render `<VoiceLibraryPicker selectedVoice={...} onSelect={...} />`.

No automated test for this task (per Global Constraints — no component test infra in this repo). Verified manually in Task 7.

- [ ] **Step 1: Implement the component**

Create `apps/web/src/components/editor/ai/voice-library-picker.tsx`:

```tsx
"use client";

import { useRef, useState } from "react";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { aiClient } from "@/lib/ai-client";
import { useVoiceLibraryStore, type ClonedVoice } from "@/stores/voice-library-store";
import { generateUUID } from "@/utils/id";
import { toast } from "sonner";

const NONE_VALUE = "__none__";

export interface VoiceLibraryPickerProps {
	selectedVoice: ClonedVoice | null;
	onSelect: (voice: ClonedVoice | null) => void;
}

export function VoiceLibraryPicker({
	selectedVoice,
	onSelect,
}: VoiceLibraryPickerProps) {
	const voices = useVoiceLibraryStore((s) => s.voices);
	const addVoice = useVoiceLibraryStore((s) => s.addVoice);
	const removeVoice = useVoiceLibraryStore((s) => s.removeVoice);

	const [isCloning, setIsCloning] = useState(voices.length === 0);
	const [isUploading, setIsUploading] = useState(false);
	const [draftName, setDraftName] = useState("");
	const fileInputRef = useRef<HTMLInputElement>(null);

	const handleSelectChange = (value: string) => {
		if (value === NONE_VALUE) {
			onSelect(null);
			return;
		}
		const voice = voices.find((v) => v.id === value);
		onSelect(voice ?? null);
	};

	const handleRemove = (id: string) => {
		removeVoice(id);
		if (selectedVoice?.id === id) onSelect(null);
	};

	const handleFilePicked = async (file: File) => {
		const name = draftName.trim() || file.name.replace(/\.[^.]+$/, "");
		setIsUploading(true);
		try {
			const result = await aiClient.cloneVoice(file, name);
			const voice: ClonedVoice = {
				id: generateUUID(),
				name: result.name,
				path: result.path,
				createdAt: Date.now(),
			};
			addVoice(voice);
			onSelect(voice);
			setDraftName("");
			setIsCloning(false);
			toast.success(`Voice "${voice.name}" saved to your library`);
		} catch (err) {
			toast.error("Voice cloning failed", {
				description: err instanceof Error ? err.message : "Unknown error",
			});
		} finally {
			setIsUploading(false);
		}
	};

	return (
		<div className="flex flex-col gap-1.5">
			<Label className="text-[10px]">Cloned voice (optional)</Label>

			{voices.length > 0 && (
				<div className="flex flex-col gap-1">
					<Select
						value={selectedVoice?.id ?? NONE_VALUE}
						onValueChange={handleSelectChange}
					>
						<SelectTrigger className="w-full">
							<SelectValue />
						</SelectTrigger>
						<SelectContent>
							<SelectItem value={NONE_VALUE}>None</SelectItem>
							{voices.map((voice) => (
								<SelectItem key={voice.id} value={voice.id}>
									{voice.name}
								</SelectItem>
							))}
						</SelectContent>
					</Select>
					<div className="flex flex-wrap gap-1">
						{voices.map((voice) => (
							<span
								key={voice.id}
								className="flex items-center gap-1 rounded-full border border-border px-1.5 py-0.5 text-[9px] text-muted-foreground"
							>
								{voice.name}
								<button
									type="button"
									className="text-destructive hover:text-destructive/80"
									onClick={() => handleRemove(voice.id)}
									aria-label={`Remove ${voice.name}`}
								>
									×
								</button>
							</span>
						))}
					</div>
				</div>
			)}

			{isCloning ? (
				<div className="flex flex-col gap-1.5 rounded-md border border-border p-2">
					<Input
						size="sm"
						value={draftName}
						onChange={(e) => setDraftName(e.target.value)}
						placeholder="Voice name (e.g. Alice)"
						className="text-[10px]"
					/>
					<div className="flex gap-1.5">
						<Button
							variant="outline"
							size="sm"
							className="flex-1 text-[10px] h-7"
							disabled={isUploading}
							onClick={() => fileInputRef.current?.click()}
						>
							{isUploading ? (
								<>
									<Spinner className="size-3 mr-1" />
									Uploading...
								</>
							) : (
								"Upload voice sample"
							)}
						</Button>
						{voices.length > 0 && (
							<Button
								variant="ghost"
								size="sm"
								className="text-[10px] h-7"
								disabled={isUploading}
								onClick={() => setIsCloning(false)}
							>
								Cancel
							</Button>
						)}
					</div>
					<p className="text-[9px] text-muted-foreground">
						Upload 10-30s audio to clone a specific voice.
					</p>
					<input
						ref={fileInputRef}
						type="file"
						accept=".wav,.mp3,.flac,.ogg,.m4a"
						className="hidden"
						onChange={(e) => {
							const file = e.target.files?.[0];
							if (file) handleFilePicked(file);
							e.target.value = "";
						}}
					/>
				</div>
			) : (
				<Button
					variant="outline"
					size="sm"
					className="text-[10px] h-7 self-start"
					onClick={() => setIsCloning(true)}
				>
					+ Clone new voice
				</Button>
			)}
		</div>
	);
}
```

- [ ] **Step 2: Typecheck**

Run: `cd apps/web && bunx tsc --noEmit -p tsconfig.json` (or the project's existing typecheck script if one exists — check `package.json`; if none, `bunx tsc --noEmit` from `apps/web/`)
Expected: no new type errors attributable to `voice-library-picker.tsx`.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/editor/ai/voice-library-picker.tsx
git commit -m "feat: add shared VoiceLibraryPicker component"
```

---

### Task 5: Wire cloning into the Dubbing panel

**Files:**
- Modify: `apps/web/src/components/editor/panels/assets/views/ai-dubbing.tsx`

**Interfaces:**
- Consumes: `VoiceLibraryPicker` (Task 4), `ClonedVoice` type (Task 2), `DubbingOptions.voiceClonePath` (Task 3).

- [ ] **Step 1: Add import and state**

In `apps/web/src/components/editor/panels/assets/views/ai-dubbing.tsx`, add to the import block (after line 18's `toast` import):

```ts
import { VoiceLibraryPicker } from "@/components/editor/ai/voice-library-picker";
import type { ClonedVoice } from "@/stores/voice-library-store";
```

Replace line 65 (`const [voiceDesign, setVoiceDesign] = useState("");`) with:

```ts
	const [voiceDesign, setVoiceDesign] = useState("");
	const [clonedVoice, setClonedVoice] = useState<ClonedVoice | null>(null);
```

- [ ] **Step 2: Pass `voiceClonePath` into `runDubbing`**

Replace lines 67-81 (`handleDub`):

```ts
	const handleDub = useCallback(() => {
		if (segments.length === 0) {
			toast.error("No transcript available. Transcribe first.");
			return;
		}
		if (language === targetLanguage) {
			toast.error("Target language is same as source.");
			return;
		}
		runDubbing({
			targetLanguage,
			engine,
			voiceDesign,
			voiceClonePath: clonedVoice?.path,
		});
	}, [segments, language, targetLanguage, engine, voiceDesign, clonedVoice, runDubbing]);
```

- [ ] **Step 3: Render the picker and disable voice design when a clone is selected**

Replace lines 167-183 (the "Voice design (optional)" block) with:

```tsx
			<div className="flex flex-col gap-1.5">
				<Label htmlFor="ai-dubbing-voice-design" className="text-[10px]">
					Voice design (optional)
				</Label>
				<Input
					id="ai-dubbing-voice-design"
					size="sm"
					value={voiceDesign}
					onChange={(event) => setVoiceDesign(event.target.value)}
					placeholder="female, young adult, high pitch, british accent"
					className="text-[10px]"
					disabled={!!clonedVoice}
				/>
				<p className="text-[9px] text-muted-foreground leading-relaxed">
					{clonedVoice
						? "Voice design is overridden by the cloned voice below."
						: "Leave blank for Auto voice. You can describe gender, age, pitch, whisper style, accents, or Chinese dialects such as 四川话."}
				</p>
			</div>

			<VoiceLibraryPicker selectedVoice={clonedVoice} onSelect={setClonedVoice} />
```

- [ ] **Step 4: Manual verification**

Run: `cd apps/web && bun run dev`, open the editor, load a transcript, open the AI Dubbing panel, upload a short voice sample under a name, confirm it appears selected, run a dub, confirm no console errors and audio is placed on the timeline. This is covered more thoroughly in Task 7.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/editor/panels/assets/views/ai-dubbing.tsx
git commit -m "feat: add voice cloning to the AI Dubbing panel"
```

---

### Task 6: Migrate the Voiceover panel to the shared library

**Files:**
- Modify: `apps/web/src/components/editor/panels/assets/views/voiceover.tsx`

**Interfaces:**
- Consumes: `VoiceLibraryPicker` (Task 4), `ClonedVoice` type (Task 2).

- [ ] **Step 1: Update imports and remove obsolete local state**

Add to the import block (after line 22's `insertGeneratedAudioElement` import):

```ts
import { VoiceLibraryPicker } from "@/components/editor/ai/voice-library-picker";
import type { ClonedVoice } from "@/stores/voice-library-store";
```

Replace lines 97-103:

```ts
	// Local engine state
	const [selectedModel, setSelectedModel] = useState("xtts_v2");
	const [voiceGender, setVoiceGender] = useState<"male" | "female">("male");
	const [clonedVoice, setClonedVoice] = useState<ClonedVoice | null>(null);
```

(This drops `clonedVoicePath`, `clonedVoiceName`, `isUploading`, and `fileInputRef` — all superseded by `VoiceLibraryPicker`'s own internal state.)

- [ ] **Step 2: Update the auto-select-model effect**

Replace lines 129-135:

```ts
	// Auto-select cloning model when a voice is selected
	useEffect(() => {
		if (clonedVoice) {
			const cloningModel = TTS_MODELS.find((m) => m.supportsCloning && m.installed);
			if (cloningModel) setSelectedModel(cloningModel.id);
		}
	}, [clonedVoice]);
```

- [ ] **Step 3: Update `generateSpeech`**

Replace lines 174-188:

```ts
	// Generate speech using the selected engine
	const generateSpeech = useCallback(async (text: string): Promise<Blob> => {
		if (engine === "sarvam") {
			const sarvamCode = SARVAM_LANGUAGE_MAP[language] || `${language}-IN`;
			return aiClient.sarvamTTS(text, sarvamCode, sarvamSpeaker);
		}
		if (engine === "smallest") {
			return aiClient.smallestTTS(text, smallestVoice, language, smallestSpeed);
		}
		return aiClient.generateSpeechBlob({
			text,
			language,
			speakerWav: clonedVoice?.path,
			speaker: clonedVoice ? undefined : voiceGender,
		});
	}, [engine, language, sarvamSpeaker, smallestVoice, smallestSpeed, clonedVoice, voiceGender]);
```

- [ ] **Step 4: Remove `handleUploadVoice`**

Delete lines 328-342 (the entire `handleUploadVoice` `useCallback` block, including its preceding `// Upload voice sample for cloning (local engine only)` comment).

- [ ] **Step 5: Update the "Voice type" note and replace the "Voice cloning" JSX block**

Replace line 607-611 (`{clonedVoiceName && (...)}`):

```tsx
							{clonedVoice && (
								<p className="text-[9px] text-muted-foreground">
									Voice type is overridden by the cloned voice below.
								</p>
							)}
```

Replace the entire "Local: Voice cloning" block, lines 614-663:

```tsx
						{/* Local: Voice cloning */}
						<VoiceLibraryPicker selectedVoice={clonedVoice} onSelect={setClonedVoice} />
```

- [ ] **Step 6: Typecheck**

Run: `cd apps/web && bunx tsc --noEmit`
Expected: no errors — confirms no leftover references to `clonedVoicePath`, `clonedVoiceName`, `isUploading`, or `fileInputRef` remain in the file.

Run: `grep -n "clonedVoicePath\|clonedVoiceName\|fileInputRef\|isUploading" apps/web/src/components/editor/panels/assets/views/voiceover.tsx`
Expected: no matches.

- [ ] **Step 7: Run the full existing hook/store test suite to confirm nothing regressed**

Run: `cd apps/web && bun test src/hooks/__tests__/use-ai-dubbing.test.ts src/stores/__tests__/voice-library-store.test.ts src/lib/__tests__/ai-client.test.ts`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/components/editor/panels/assets/views/voiceover.tsx
git commit -m "refactor: migrate Voiceover panel to the shared voice library"
```

---

### Task 7: End-to-end manual verification

**Files:** none (verification only)

- [ ] **Step 1: Start the TTS backend**

```bash
cd services/tts-service && source .venv/bin/activate && python app.py
```

Confirm it logs listening on port 8422 and `GET http://localhost:8422/health` returns `{"status": "ok", ...}` (or equivalent) via `curl http://localhost:8422/health`.

- [ ] **Step 2: Start the web app**

```bash
cd apps/web && bun run dev
```

- [ ] **Step 3: Verify Dubbing panel clone + persist + reuse**

1. Open the editor with a project that has a transcript (or transcribe a short clip first).
2. Open the AI Dubbing panel, expand "+ Clone new voice", name it "Test Voice", upload a short WAV/MP3 sample.
3. Confirm a toast confirms the save and the voice becomes selected, and the "Voice design" input becomes disabled.
4. Reload the page. Confirm "Test Voice" still appears in the dropdown (proves localStorage persistence).
5. Select "Test Voice", set a target language different from the source, click "Start Dubbing".
6. Confirm dubbing completes without errors and a new audio track/clip appears on the timeline.
7. Open the browser Network tab, inspect the `POST /api/tts/generate` request body, confirm it contains `"speaker_wav": "generated/voices/..."` (snake_case) rather than `speakerWav` — this confirms Task 1's fix reached the wire.

- [ ] **Step 4: Verify Voiceover panel reuse**

1. Open the Voiceover panel (local engine). Confirm "Test Voice" is available in the same picker (proves the shared library works across panels) and can be selected/deselected.
2. Generate a voiceover with "Test Voice" selected; confirm it completes and the "Voice type" buttons show the override note.

- [ ] **Step 5: Verify voice removal**

1. In either panel, remove "Test Voice" from the library via its "×" chip.
2. Confirm it disappears from both panels' pickers (shared store) and, if it was selected, the "Voice design"/"Voice type" controls re-enable.

No commit for this task (verification only, unless a bug is found — in which case fix it in the relevant earlier task's files and re-run that task's tests before re-verifying).
