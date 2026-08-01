export interface TranslationControlInput {
	segmentCount: number;
	targetLanguage: string;
	activeLanguages: string[];
	translating: boolean;
}

export interface TranslationControlState {
	visible: boolean;
	disabled: boolean;
}

export function getTranslationControlState({
	segmentCount,
	targetLanguage,
	activeLanguages,
	translating,
}: TranslationControlInput): TranslationControlState {
	const visible = segmentCount > 0;
	const disabled =
		!visible ||
		translating ||
		!targetLanguage ||
		activeLanguages.includes(targetLanguage);
	return { visible, disabled };
}

export function getTranslationTabAfterChange(
	previousCount: number,
	translations: readonly { languageCode: string }[],
): string | null {
	if (translations.length < previousCount) return null;
	return translations.at(-1)?.languageCode ?? null;
}

export function getTranslationDisplaySegments({
	segments,
	displaySegments,
}: {
	segments: TranscriptionSegment[];
	displaySegments?: DisplayCaptionSegment[];
}): DisplayCaptionSegment[] {
	if (displaySegments && displaySegments.length > 0) return displaySegments;

	return segments.map((segment) => ({
		id: segment.id,
		parent_id: segment.id,
		part_index: 0,
		source: segment.text,
		translation: segment.text,
		start: segment.start,
		end: segment.end,
	}));
}
import type { DisplayCaptionSegment, TranscriptionSegment } from "@/types/ai";
