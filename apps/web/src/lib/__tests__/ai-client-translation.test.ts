import { afterEach, describe, expect, mock, test } from "bun:test";
import { aiClient } from "@/lib/ai-client";

const originalFetch = globalThis.fetch;

afterEach(() => {
	globalThis.fetch = originalFetch;
	mock.restore();
});

describe("AIClient.translateTranscript", () => {
	test("posts the structured transcript to the contextual endpoint", async () => {
		const fetchMock = mock(
			async (_url: string | URL | Request, _init?: RequestInit) =>
				new Response(
					JSON.stringify({
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
					}),
					{ status: 200, headers: { "Content-Type": "application/json" } },
				),
		);
		globalThis.fetch = fetchMock as unknown as typeof fetch;

		const result = await aiClient.translateTranscript({
			source_language: "vi",
			target_language: "en",
			segments: [{ id: 4, text: "Xin chào.", start: 1, end: 2 }],
			custom_terms: [],
		});

		expect(result.segments[0].translation).toBe("Hello.");
		expect(fetchMock).toHaveBeenCalledTimes(1);
		const [url, init] = fetchMock.mock.calls[0];
		expect(String(url)).toEndWith("/api/translations/contextual");
		expect(JSON.parse(String(init?.body))).toEqual({
			source_language: "vi",
			target_language: "en",
			segments: [{ id: 4, text: "Xin chào.", start: 1, end: 2 }],
			custom_terms: [],
		});
	});
});
