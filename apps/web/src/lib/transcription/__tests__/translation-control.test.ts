import { describe, expect, test } from "bun:test";
import {
	getTranslationControlState,
	getTranslationDisplaySegments,
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

	test("uses split display captions so the transcript matches the timeline", () => {
		expect(
			getTranslationDisplaySegments({
				segments: [{ id: 7, text: "Full sentence", start: 10, end: 14, words: [] }],
				displaySegments: [
					{
						id: 20,
						parent_id: 7,
						part_index: 0,
						source: "Full",
						translation: "Một phần",
						start: 10,
						end: 12,
					},
					{
						id: 21,
						parent_id: 7,
						part_index: 1,
						source: "sentence",
						translation: "còn lại",
						start: 12,
						end: 14,
					},
				],
			}),
		).toHaveLength(2);
	});

	test("falls back to translated parent segments when no display split exists", () => {
		expect(
			getTranslationDisplaySegments({
				segments: [{ id: 1, text: "Hello", start: 0, end: 1, words: [] }],
			}),
		).toEqual([
			{
				id: 1,
				parent_id: 1,
				part_index: 0,
				source: "Hello",
				translation: "Hello",
				start: 0,
				end: 1,
			},
		]);
	});
});
