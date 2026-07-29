import { describe, expect, mock, test } from "bun:test";
import { ensureTargetTranslation } from "@/lib/transcription/dubbing-runner";

describe("ensureTargetTranslation", () => {
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
});
