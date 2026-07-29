import { afterEach, describe, expect, mock, test } from "bun:test";
import { aiClient } from "@/lib/ai-client";

const originalFetch = globalThis.fetch;

afterEach(() => {
	globalThis.fetch = originalFetch;
	mock.restore();
});

describe("AIClient dubbing jobs", () => {
	test("creates a queued job with the selected voice mode", async () => {
		const fetchMock = mock(async () =>
			new Response(JSON.stringify({ job_id: "job-1", status: "queued" }), {
				status: 202,
				headers: { "Content-Type": "application/json" },
			}),
		);
		globalThis.fetch = fetchMock as unknown as typeof fetch;

		const result = await aiClient.createDubbingJob({
			source_language: "en",
			target_language: "vi",
			audio_segments: [],
			display_segments: [],
			voice: { mode: "clone", speaker_wav: "generated/voices/alice.wav" },
		});

		expect(result.status).toBe("queued");
		const [url, init] = (fetchMock.mock.calls as unknown as [RequestInfo, RequestInit][])[0];
		expect(String(url)).toEndWith("/api/dubbing/jobs");
		expect(JSON.parse(String(init?.body)).voice).toEqual({
			mode: "clone",
			speaker_wav: "generated/voices/alice.wav",
		});
	});

	test("gets a job snapshot", async () => {
		globalThis.fetch = mock(async () =>
			new Response(JSON.stringify({ job_id: "job-1", status: "completed" }), {
				status: 200,
				headers: { "Content-Type": "application/json" },
			}),
		) as unknown as typeof fetch;

		const result = await aiClient.getDubbingJob("job-1");
		expect(result.status).toBe("completed");
		const calls = (globalThis.fetch as unknown as ReturnType<typeof mock>).mock.calls as unknown as [RequestInfo, RequestInit][];
		expect(String(calls[0][0]))
			.toEndWith("/api/dubbing/jobs/job-1");
	});
});
