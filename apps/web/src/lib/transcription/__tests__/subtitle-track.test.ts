import { describe, expect, test } from "bun:test";
import { buildCaptionTrackElement } from "@/lib/transcription/subtitle-track";

describe("buildCaptionTrackElement", () => {
	test("keeps segment timing and converts word timing to local time", () => {
		const element = buildCaptionTrackElement({
			languageLabel: "English",
			index: 0,
			subtitleY: 320,
			segment: {
				text: "Hello.",
				start: 2,
				end: 3.5,
				words: [{ word: "Hello.", start: 2.1, end: 2.8 }],
			},
		});

		expect(element.name).toBe("English 1");
		expect(element.content).toBe("Hello.");
		expect(element.startTime).toBe(2);
		expect(element.duration).toBe(1.5);
		expect(element.wordTimings?.[0]?.word).toBe("Hello.");
		expect(element.wordTimings?.[0]?.start).toBeCloseTo(0.1);
		expect(element.wordTimings?.[0]?.end).toBeCloseTo(0.8);
		expect(element.transform.position).toEqual({ x: 0, y: 320 });
	});
});
