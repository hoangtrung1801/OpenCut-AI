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
