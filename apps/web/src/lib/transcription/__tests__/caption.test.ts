import { describe, expect, test } from "bun:test";
import { buildCaptionChunks } from "@/lib/transcription/caption";

describe("buildCaptionChunks", () => {
	test("short segment with word timings produces a single unchanged chunk", () => {
		const chunks = buildCaptionChunks({
			segments: [
				{
					text: "Hi there",
					start: 0,
					end: 1,
					words: [
						{ word: "Hi", start: 0, end: 0.4 },
						{ word: "there", start: 0.4, end: 1 },
					],
				},
			],
		});

		expect(chunks).toEqual([
			{
				text: "Hi there",
				startTime: 0,
				duration: 1,
				words: [
					{ word: "Hi", start: 0, end: 0.4 },
					{ word: "there", start: 0.4, end: 1 },
				],
			},
		]);
	});

	test("long sentence with word timings splits into multiple chunks at real timestamps, no gaps or overlaps", () => {
		const words = [
			{ word: "The", start: 0, end: 0.3 },
			{ word: "quick", start: 0.3, end: 0.7 },
			{ word: "brown", start: 0.7, end: 1.1 },
			{ word: "fox", start: 1.1, end: 1.4 },
			{ word: "jumps", start: 1.4, end: 1.9 },
			{ word: "over", start: 1.9, end: 2.2 },
			{ word: "the", start: 2.2, end: 2.4 },
			{ word: "lazy", start: 2.4, end: 2.8 },
			{ word: "dog", start: 2.8, end: 3.2 },
			{ word: "again", start: 3.2, end: 3.7 },
			{ word: "and", start: 3.7, end: 3.9 },
			{ word: "again", start: 3.9, end: 4.4 },
		];
		const text = words.map((w) => w.word).join(" ");

		const chunks = buildCaptionChunks({
			segments: [{ text, start: 0, end: 4.4, words }],
			maxCharsPerLine: 20,
		});

		expect(chunks.length).toBeGreaterThan(1);
		for (const chunk of chunks) {
			expect(chunk.text.length).toBeLessThanOrEqual(20);
		}
		// No gaps or overlaps between consecutive chunks.
		for (let i = 1; i < chunks.length; i++) {
			expect(chunks[i].startTime).toBeGreaterThanOrEqual(
				chunks[i - 1].startTime + chunks[i - 1].duration,
			);
		}
		// Text is preserved in order.
		expect(chunks.map((c) => c.text).join(" ")).toBe(text);
	});

	test("segment without word timings falls back to proportional duration split covering the full span", () => {
		const chunks = buildCaptionChunks({
			segments: [
				{
					text: "This translated sentence has no per word timing data at all",
					start: 10,
					end: 16,
				},
			],
			maxCharsPerLine: 20,
		});

		expect(chunks.length).toBeGreaterThan(1);
		expect(chunks[0].startTime).toBe(10);
		// The last chunk's end is >= the segment's natural end (16) — a short trailing
		// chunk can push past it once minDuration (0.8s) is enforced, but never short of it.
		const last = chunks[chunks.length - 1];
		expect(last.startTime + last.duration).toBeGreaterThanOrEqual(16);
		for (let i = 1; i < chunks.length; i++) {
			expect(chunks[i].startTime).toBeCloseTo(
				chunks[i - 1].startTime + chunks[i - 1].duration,
				5,
			);
		}
	});

	test("chunk shorter than minDuration is extended without overlapping the next chunk", () => {
		const chunks = buildCaptionChunks({
			segments: [
				{
					text: "Hi there",
					start: 0,
					end: 1,
					words: [
						{ word: "Hi", start: 0, end: 0.1 },
						{ word: "there", start: 0.1, end: 1.0 },
					],
				},
			],
			maxCharsPerLine: 5, // "Hi there" (8 chars) can't fit together, but neither word needs splitting
			minDuration: 0.5,
		});

		expect(chunks).toEqual([
			{ text: "Hi", startTime: 0, duration: 0.5, words: [{ word: "Hi", start: 0, end: 0.1 }] },
			{
				text: "there",
				startTime: 0.5,
				duration: 0.5,
				words: [{ word: "there", start: 0.1, end: 1.0 }],
			},
		]);
	});

	test("long no-space token without word timings is sliced by character count", () => {
		const longToken = "a".repeat(90); // simulates a CJK-style single unbroken token
		// Duration chosen so every chunk's proportional share clears minDuration (0.8s),
		// so the assertions below aren't perturbed by the minDuration clamp.
		const chunks = buildCaptionChunks({
			segments: [{ text: longToken, start: 0, end: 13.5 }],
			maxCharsPerLine: 42,
		});

		expect(chunks.length).toBe(3); // 90 chars / 42 -> 42 + 42 + 6
		for (const chunk of chunks) {
			expect(chunk.text.length).toBeLessThanOrEqual(42);
		}
		expect(chunks.map((c) => c.text).join("")).toBe(longToken);
		expect(chunks[0].startTime).toBe(0);
		const last = chunks[chunks.length - 1];
		expect(last.startTime + last.duration).toBeCloseTo(13.5, 5);
	});
});
