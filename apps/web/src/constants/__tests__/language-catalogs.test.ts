import { describe, expect, test } from "bun:test";
import { LANGUAGES } from "@/constants/language-constants";
import {
	TRANSCRIPTION_LANGUAGES,
	WHISPER_LANGUAGES,
} from "@/constants/transcription-constants";

describe("Vietnamese language catalogs", () => {
	test("includes Vietnamese in the shared language catalog", () => {
		expect(LANGUAGES).toContainEqual({ code: "vi", name: "Vietnamese" });
	});

	test("includes Vietnamese in transcription catalogs", () => {
		expect(TRANSCRIPTION_LANGUAGES).toContainEqual({
			code: "vi",
			name: "Vietnamese",
		});
		expect(WHISPER_LANGUAGES).toContainEqual({
			code: "vi",
			name: "Vietnamese",
		});
	});
});
