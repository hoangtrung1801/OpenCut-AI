# Transcript Translation Auto-Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically show the latest translated transcript while preserving the original transcript for later access.

**Architecture:** Keep the existing `segments` and `translations` store structure. Add one pure helper that identifies the newest translated language on addition or replacement, then have `TextEditingPanel` select it when the translations collection changes. A removal does not select another translation, allowing the existing validity check to fall back to the original.

**Tech Stack:** TypeScript, React 19, Zustand, Bun test

## Global Constraints

- Preserve `useTranscriptStore.segments` as the original transcript.
- Render translated text through the existing `TranslationView`.
- Keep the original-language tab available.
- Do not add dependencies or backend/schema changes.
- Follow the existing `useEditor()` rule in React components.

---

### Task 1: Select the Latest Translation in the Transcript Panel

**Files:**
- Modify: `apps/web/src/lib/transcription/translation-control.ts`
- Modify: `apps/web/src/lib/transcription/__tests__/translation-control.test.ts`
- Modify: `apps/web/src/components/editor/ai/text-editing-panel.tsx`

**Interfaces:**
- Consumes: `TranslatedTranscript.languageCode` from `useTranscriptStore.translations`
- Produces: `getTranslationTabAfterChange(previousCount: number, translations: readonly { languageCode: string }[]): string | null`

- [ ] **Step 1: Write the failing tab-selection test**

Add this import and test cases to
`apps/web/src/lib/transcription/__tests__/translation-control.test.ts`:

```typescript
import {
	getTranslationTabAfterChange,
	getTranslationControlState,
} from "@/lib/transcription/translation-control";

test("selects the most recently added translation language", () => {
	expect(
		getTranslationTabAfterChange(1, [
			{ languageCode: "fr" },
			{ languageCode: "vi" },
		]),
	).toBe("vi");
});

test("selects a replacement translation for the same language", () => {
	expect(
		getTranslationTabAfterChange(1, [{ languageCode: "vi" }]),
	).toBe("vi");
});

test("does not select another translation when one is removed", () => {
	expect(
		getTranslationTabAfterChange(2, [{ languageCode: "fr" }]),
	).toBeNull();
	expect(getTranslationTabAfterChange(0, [])).toBeNull();
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd apps/web
bun test src/lib/transcription/__tests__/translation-control.test.ts
```

Expected: FAIL because `getTranslationTabAfterChange` is not exported.

- [ ] **Step 3: Add the minimal selection helper**

Append to `apps/web/src/lib/transcription/translation-control.ts`:

```typescript
export function getTranslationTabAfterChange(
	previousCount: number,
	translations: readonly { languageCode: string }[],
): string | null {
	if (translations.length < previousCount) return null;
	return translations.at(-1)?.languageCode ?? null;
}
```

- [ ] **Step 4: Connect translation changes to the active tab**

Import the helper in
`apps/web/src/components/editor/ai/text-editing-panel.tsx`:

```typescript
import { getTranslationTabAfterChange } from "@/lib/transcription/translation-control";
```

After reading `translations` from `useTranscriptStore`, add:

```typescript
const previousTranslationCount = useRef(0);

useEffect(() => {
	const latestLanguage = getTranslationTabAfterChange(
		previousTranslationCount.current,
		translations,
	);
	previousTranslationCount.current = translations.length;
	if (latestLanguage) setActiveTab(latestLanguage);
}, [translations]);
```

This effect runs for both a newly appended language and replacement of an
existing language because `addTranslation` creates a new translations array.
It ignores removals and does not mutate `storeSegments`.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
cd apps/web
bun test src/lib/transcription/__tests__/translation-control.test.ts
```

Expected: all translation-control tests pass.

- [ ] **Step 6: Run web regression verification**

Run:

```bash
cd apps/web
bun test
bunx tsc --noEmit
```

Expected: the complete web suite passes and TypeScript exits with code 0.

- [ ] **Step 7: Review the scoped diff**

Run:

```bash
git diff --check -- apps/web/src/lib/transcription/translation-control.ts apps/web/src/lib/transcription/__tests__/translation-control.test.ts apps/web/src/components/editor/ai/text-editing-panel.tsx
git diff -- apps/web/src/lib/transcription/translation-control.ts apps/web/src/lib/transcription/__tests__/translation-control.test.ts apps/web/src/components/editor/ai/text-editing-panel.tsx
```

Expected: only the helper, its regression tests, and the panel effect changed.

- [ ] **Step 8: Commit the implementation**

```bash
git add apps/web/src/lib/transcription/translation-control.ts apps/web/src/lib/transcription/__tests__/translation-control.test.ts apps/web/src/components/editor/ai/text-editing-panel.tsx
git commit -m "fix: show translated transcript after translation"
```
