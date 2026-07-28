import { describe, expect, test } from "bun:test";
import { getTranslationControlState } from "@/lib/transcription/translation-control";

describe("getTranslationControlState", () => {
	test("hides the control until a transcript exists", () => {
		expect(
			getTranslationControlState({
				segmentCount: 0,
				targetLanguage: "es",
				activeLanguages: [],
				translating: false,
			}),
		).toEqual({ visible: false, disabled: true });
	});

	test("disables an active or already-added language", () => {
		expect(
			getTranslationControlState({
				segmentCount: 2,
				targetLanguage: "es",
				activeLanguages: ["es"],
				translating: false,
			}).disabled,
		).toBe(true);
		expect(
			getTranslationControlState({
				segmentCount: 2,
				targetLanguage: "fr",
				activeLanguages: [],
				translating: true,
			}).disabled,
		).toBe(true);
	});

	test("enables an eligible target", () => {
		expect(
			getTranslationControlState({
				segmentCount: 2,
				targetLanguage: "es",
				activeLanguages: [],
				translating: false,
			}),
		).toEqual({ visible: true, disabled: false });
	});
});
