import { afterEach, describe, expect, mock, test } from "bun:test";
import { aiClient } from "@/lib/ai-client";

const originalFetch = globalThis.fetch;

afterEach(() => {
	globalThis.fetch = originalFetch;
	mock.restore();
});

const result = {
	source_language: "vi",
	target_language: "en",
	theme: "Greeting.",
	terminology: [],
	segments: [
		{
			id: 4,
			source: "Xin chào.",
			translation: "Hello.",
			start: 1,
			end: 2,
		},
	],
	display_segments: [
		{
			id: 0,
			parent_id: 4,
			part_index: 0,
			source: "Xin chào.",
			translation: "Hello.",
			start: 1,
			end: 2,
		},
	],
	audio_segments: [
		{
			id: 4,
			source: "Xin chào.",
			translation: "Hello.",
			start: 1,
			end: 2,
		},
	],
	subtitles: {
		source: { srt: "", vtt: "WEBVTT" },
		translation: { srt: "", vtt: "WEBVTT" },
		source_translation: { srt: "", vtt: "WEBVTT" },
		translation_source: { srt: "", vtt: "WEBVTT" },
	},
};

describe("AIClient caption endpoints", () => {
		test("posts source word timings to contextual translation", async () => {
		const fetchMock = mock(
			async (_url: string | URL | Request, _init?: RequestInit) =>
				new Response(JSON.stringify(result), {
					status: 200,
					headers: { "Content-Type": "application/json" },
				}),
		);
		globalThis.fetch = fetchMock as unknown as typeof fetch;

		await aiClient.translateTranscript({
			source_language: "vi",
			target_language: "en",
			segments: [
				{
					id: 4,
					text: "Xin chào.",
					start: 1,
					end: 2,
					words: [{ word: "Xin", start: 1, end: 1.4 }],
				},
			],
			custom_terms: [],
		});

		const [, init] = fetchMock.mock.calls[0];
		expect(JSON.parse(String(init?.body)).segments[0].words).toEqual([
			{ word: "Xin", start: 1, end: 1.4 },
		]);
	});

	test("posts already translated pairs to caption post-processing", async () => {
		const fetchMock = mock(
			async (_url: string | URL | Request, _init?: RequestInit) =>
				new Response(JSON.stringify(result), {
					status: 200,
					headers: { "Content-Type": "application/json" },
				}),
		);
		globalThis.fetch = fetchMock as unknown as typeof fetch;

		await aiClient.postProcessCaptions({
			source_language: "vi",
			target_language: "en",
			segments: [
				{
					id: 4,
					source: "Xin chào.",
					translation: "Hello.",
					start: 1,
					end: 2,
					words: [],
				},
			],
		});

		expect(String(fetchMock.mock.calls[0][0])).toEndWith(
			"/api/translations/captions/post-process",
		);
	});
});
