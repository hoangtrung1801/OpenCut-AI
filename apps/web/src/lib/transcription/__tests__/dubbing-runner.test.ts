import { describe, expect, mock, test } from "bun:test";
import {
	buildDubbingRequest,
	buildDubbingVoice,
	ensureTargetTranslation,
} from "@/lib/transcription/dubbing-runner";

describe("ensureTargetTranslation", () => {
	test("includes reference text when using a cloned voice", () => {
		expect(
			buildDubbingVoice({
				targetLanguage: "vi",
				voiceClonePath: "generated/voices/alice.wav",
				voiceCloneReferenceText: " Hello from Alice. ",
			}),
		).toEqual({
			mode: "clone",
			speaker_wav: "generated/voices/alice.wav",
			reference_text: "Hello from Alice.",
		});
	});

	test("creates target caption rows when the selected language is not persisted", async () => {
		const translate = mock(async () => ({
			source_language: "zh",
			target_language: "vi",
			theme: "Travel",
			terminology: [],
			segments: [{ id: 1, source: "你好", translation: "Xin chào", start: 0, end: 1 }],
			display_segments: [{
				id: 1,
				parent_id: 1,
				part_index: 0,
				source: "你好",
				translation: "Xin chào",
				start: 0,
				end: 1,
			}],
			audio_segments: [{ id: 1, source: "你好", translation: "Xin chào", start: 0, end: 1 }],
			subtitles: {
				source: { srt: "", vtt: "" },
				translation: { srt: "", vtt: "" },
				source_translation: { srt: "", vtt: "" },
				translation_source: { srt: "", vtt: "" },
			},
		}));

		const result = await ensureTargetTranslation({
			transcript: {
				language: "zh",
				segments: [{ id: 1, text: "你好", start: 0, end: 1, words: [] }],
				translations: [],
			},
			targetLanguage: "vi",
			translate,
		});

		expect(result.languageCode).toBe("vi");
		expect(result.segments[0]?.text).toBe("Xin chào");
		expect(result.displaySegments?.[0]?.translation).toBe("Xin chào");
		expect(translate).toHaveBeenCalledTimes(1);
	});

	test("uses review edits for the parent sentence without changing display rows", () => {
		const request = buildDubbingRequest(
			{
				targetLanguage: "vi",
				sentenceOverrides: { 1: "Được chỉnh sửa cho giọng đọc." },
			},
			{
				language: "zh",
				segments: [{ id: 1, text: "原句", start: 0, end: 2, words: [] }],
				translations: [{
					languageCode: "vi",
					languageName: "Vietnamese",
					segments: [{ id: 1, text: "Câu gốc", start: 0, end: 2, words: [] }],
					displaySegments: [
						{
							id: 10,
							parent_id: 1,
							part_index: 0,
							source: "原",
							translation: "Câu",
							start: 0,
							end: 1,
						},
						{
							id: 11,
							parent_id: 1,
							part_index: 1,
							source: "句",
							translation: "gốc",
							start: 1,
							end: 2,
						},
					],
				}],
			},
		);

		expect(request.audio_segments[0]?.translation).toBe("Được chỉnh sửa cho giọng đọc.");
		expect(request.display_segments.map((segment) => segment.translation)).toEqual(["Câu", "gốc"]);
	});
});
