import { describe, expect, test } from "bun:test";
import { shouldUseSarvamTranslation } from "@/lib/transcription/translation-provider";

describe("shouldUseSarvamTranslation", () => {
	test("uses Sarvam for English and Indian language pairs", () => {
		expect(shouldUseSarvamTranslation("en", "hi")).toBe(true);
	});

	test("uses Sarvam for two supported Indian languages", () => {
		expect(shouldUseSarvamTranslation("hi", "ta")).toBe(true);
	});

	test("uses contextual local translation for global language pairs", () => {
		expect(shouldUseSarvamTranslation("vi", "en")).toBe(false);
	});
});
