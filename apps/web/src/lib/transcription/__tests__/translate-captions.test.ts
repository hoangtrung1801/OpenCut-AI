import { describe, expect, mock, test } from "bun:test";
import type {
	CaptionPostProcessResult,
	ContextualTranslationResult,
	TranscriptionSegment,
} from "@/types/ai";
import {
	translateAndAddCaptions,
	type CaptionTranslationDependencies,
} from "@/lib/transcription/translate-captions";
import type { CaptionSourceSegment } from "@/lib/transcription/caption";

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
	display_segments: [
		{
			id: 0,
			parent_id: 0,
			part_index: 0,
			source: "Xin",
			translation: "Hel",
			start: 0,
			end: 0.5,
		},
		{
			id: 1,
			parent_id: 0,
			part_index: 1,
			source: "chào.",
			translation: "lo.",
			start: 0.5,
			end: 1,
		},
	],
	audio_segments: [
		{
			id: 0,
			source: "Xin chào.",
			translation: "Hello.",
			start: 0,
			end: 1,
		},
	],
	subtitles: {
		source: { srt: "", vtt: "WEBVTT" },
		translation: { srt: "", vtt: "WEBVTT" },
		source_translation: { srt: "", vtt: "WEBVTT" },
		translation_source: { srt: "", vtt: "WEBVTT" },
	},
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
		postProcessCaptions: async () => contextualResult,
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
		let createdSegments: CaptionSourceSegment[] = [];
		const result = await translateAndAddCaptions(
			{ targetLanguage: "en", targetLanguageName: "English" },
			dependencies({
				addTask: () => calls.push("task"),
				updateTask: (_id, update) => calls.push(String(update.status ?? update.progress)),
				storeTranslation: () => calls.push("translation"),
				createTrack: ({ segments }) => {
					calls.push("track");
					createdSegments = segments;
					return "track-1";
				},
				storeTrack: () => calls.push("track-state"),
			}),
		);

		expect(result).toBe("track-1");
		expect(calls.indexOf("translation")).toBeLessThan(calls.indexOf("track"));
		expect(calls.indexOf("track")).toBeLessThan(calls.indexOf("track-state"));
		expect(createdSegments).toEqual([
			{ text: "Hel", start: 0, end: 0.5, words: [] },
			{ text: "lo.", start: 0.5, end: 1, words: [] },
		]);
	});

	test("sends transcript word timings to contextual translation", async () => {
		let requestWords: unknown;
		await translateAndAddCaptions(
			{ targetLanguage: "en", targetLanguageName: "English" },
			dependencies({
				getTranscript: () => ({
					language: "vi",
					segments: [{
						...sourceSegments[0],
						words: [{ word: "Xin", start: 0, end: 0.4, confidence: 0.9 }],
					}],
				}),
				translateContextual: async (request) => {
					requestWords = request.segments[0]?.words;
					return contextualResult;
				},
			}),
		);
		expect(requestWords).toEqual([{ word: "Xin", start: 0, end: 0.4 }]);
	});

	test("post-processes Sarvam translations before creating the track", async () => {
		let postProcessCalls = 0;
		const sarvamResult: CaptionPostProcessResult = {
			source_language: "en",
			target_language: "hi",
			display_segments: [{
				id: 0,
				parent_id: 0,
				part_index: 0,
				source: "Hello.",
				translation: "नमस्ते।",
				start: 0,
				end: 1,
			}],
			audio_segments: [{
				id: 0,
				source: "Hello.",
				translation: "नमस्ते।",
				start: 0,
				end: 1,
			}],
			subtitles: {
				source: { srt: "", vtt: "" },
				translation: { srt: "", vtt: "" },
				source_translation: { srt: "", vtt: "" },
				translation_source: { srt: "", vtt: "" },
			},
		};
		await translateAndAddCaptions(
			{ targetLanguage: "hi", targetLanguageName: "Hindi" },
			dependencies({
				getTranscript: () => ({ language: "en", segments: [{ ...sourceSegments[0], text: "Hello." }] }),
				translateSarvam: async () => [{ id: 0, source: "Hello.", translation: "नमस्ते।", start: 0, end: 1 }],
				postProcessCaptions: async (request) => {
					postProcessCalls += 1;
					expect(request.segments[0]?.translation).toBe("नमस्ते।");
					return sarvamResult;
				},
			}),
		);
		expect(postProcessCalls).toBe(1);
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
