import { describe, expect, mock, test } from "bun:test";
import type {
	ContextualTranslationResult,
	TranscriptionSegment,
} from "@/types/ai";
import {
	translateAndAddCaptions,
	type CaptionTranslationDependencies,
} from "@/lib/transcription/translate-captions";

const sourceSegments: TranscriptionSegment[] = [
	{
		id: 0,
		text: "Xin chào.",
		start: 0,
		end: 1,
		words: [],
	},
];

const contextualResult: ContextualTranslationResult = {
	source_language: "vi",
	target_language: "en",
	theme: "Greeting.",
	terminology: [],
	segments: [
		{
			id: 0,
			source: "Xin chào.",
			translation: "Hello.",
			start: 0,
			end: 1,
		},
	],
};

function dependencies(
	overrides: Partial<CaptionTranslationDependencies> = {},
): CaptionTranslationDependencies {
	return {
		getTranscript: () => ({ language: "vi", segments: sourceSegments }),
		translateContextual: async () => contextualResult,
		translateSarvam: async () => [
			{ id: 0, source: "Xin chào.", translation: "Hello.", start: 0, end: 1 },
		],
		addTask: mock(() => {}),
		updateTask: mock(() => {}),
		storeTranslation: mock(() => {}),
		createTrack: mock(() => "track-1"),
		storeTrack: mock(() => {}),
		now: () => 100,
		...overrides,
	};
}

describe("translateAndAddCaptions", () => {
	test("commits translation and track only after contextual success", async () => {
		const calls: string[] = [];
		const result = await translateAndAddCaptions(
			{ targetLanguage: "en", targetLanguageName: "English" },
			dependencies({
				addTask: () => calls.push("task"),
				updateTask: (_id, update) => calls.push(String(update.status ?? update.progress)),
				storeTranslation: () => calls.push("translation"),
				createTrack: () => {
					calls.push("track");
					return "track-1";
				},
				storeTrack: () => calls.push("track-state"),
			}),
		);

		expect(result).toBe("track-1");
		expect(calls.indexOf("translation")).toBeLessThan(calls.indexOf("track"));
		expect(calls.indexOf("track")).toBeLessThan(calls.indexOf("track-state"));
	});

	test("does not mutate transcript or timeline when translation fails", async () => {
		const storeTranslation = mock(() => {});
		const createTrack = mock(() => "track-1");
		const failureDependencies = dependencies({
			translateContextual: async () => {
				throw new Error("provider failed");
			},
			storeTranslation,
			createTrack,
		});

		await expect(
			translateAndAddCaptions(
				{ targetLanguage: "en", targetLanguageName: "English" },
				failureDependencies,
			),
		).rejects.toThrow("provider failed");
		expect(storeTranslation).not.toHaveBeenCalled();
		expect(createTrack).not.toHaveBeenCalled();
	});
});
