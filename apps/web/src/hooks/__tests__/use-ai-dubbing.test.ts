import { describe, expect, test } from "bun:test";
import { buildLocalTTSRequest } from "@/hooks/use-ai-dubbing";

describe("buildLocalTTSRequest", () => {
	test("omits speaker for an empty voice design", () => {
		expect(buildLocalTTSRequest("Hello", "en", "   ")).toEqual({
			text: "Hello",
			language: "en",
		});
	});

	test("trims and sends a voice design as speaker", () => {
		expect(
			buildLocalTTSRequest(
				"Hello",
				"en",
				" female, young adult, high pitch, british accent ",
			),
		).toEqual({
			text: "Hello",
			language: "en",
			speaker: "female, young adult, high pitch, british accent",
		});
	});
});
