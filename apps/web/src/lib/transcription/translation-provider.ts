import {
	SARVAM_LANGUAGE_MAP,
	SARVAM_SUPPORTED_CODES,
} from "@/constants/sarvam-constants";

export function shouldUseSarvamTranslation(
	sourceLanguage: string,
	targetLanguage: string,
): boolean {
	const sourceIsSarvam = SARVAM_SUPPORTED_CODES.has(sourceLanguage);
	const targetIsSarvam = SARVAM_SUPPORTED_CODES.has(targetLanguage);
	const sourceIsIndian = sourceIsSarvam && sourceLanguage !== "en";
	const targetIsIndian = targetIsSarvam && targetLanguage !== "en";
	return (
		(sourceIsIndian || targetIsIndian) && sourceIsSarvam && targetIsSarvam
	);
}

export function sarvamLanguageCode(language: string): string {
	return SARVAM_LANGUAGE_MAP[language] || `${language}-IN`;
}
