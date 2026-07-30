import { describe, expect, test } from "bun:test";
import {
	getTranslationControlState,
	getTranslationTabAfterChange,
} from "@/lib/transcription/translation-control";

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
});
