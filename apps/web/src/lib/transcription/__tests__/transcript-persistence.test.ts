import { describe, expect, test } from "bun:test";
import {
	createTranscriptSnapshot,
	normalizeTranscriptSnapshot,
} from "@/lib/transcription/transcript-persistence";
import type { PersistedTranscript } from "@/types/transcript";

describe("transcript persistence", () => {
	test("round-trips the original transcript and translations", () => {
		const transcript: PersistedTranscript = {
			segments: [{ id: 1, text: "Original", start: 0, end: 1, words: [] }],
			language: "zh",
			duration: 1,
			sourceMediaId: "media-1",
			separatedAudio: null,
			fillers: [],
			silences: [],
			chapters: [],
			translations: [
				{
					languageCode: "vi",
					languageName: "Vietnamese",
					segments: [{ id: 1, text: "Bản dịch", start: 0, end: 1, words: [] }],
				},
			],
			subtitleTracks: [],
			speakerNames: {},
			speakerPositions: {},
			emotions: [],
		};

		const restored = normalizeTranscriptSnapshot(
			createTranscriptSnapshot(
				{ ...transcript, transient: () => undefined } as unknown as PersistedTranscript,
			),
		);

		expect(restored).toEqual(transcript);
	});

	test("fills missing optional collections from older snapshots", () => {
		const restored = normalizeTranscriptSnapshot({
			segments: [],
			language: "en",
			duration: 0,
			sourceMediaId: null,
			separatedAudio: null,
		});

		expect(restored?.translations).toEqual([]);
		expect(restored?.speakerNames).toEqual({});
	});
});
