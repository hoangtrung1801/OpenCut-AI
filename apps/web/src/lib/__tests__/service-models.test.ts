import { describe, expect, test } from "bun:test";
import {
	TTS_MODELS,
	loadedWhisperModel,
} from "@/lib/ai/service-models";

describe("local service model catalog", () => {
	test("offers only the OmniVoice model supported by tts-service", () => {
		expect(TTS_MODELS.map((model) => model.name)).toEqual(["omnivoice"]);
	});

	test("does not mark Whisper's configured model as active before it is loaded", () => {
		expect(loadedWhisperModel({ loaded: false, model_size: "large-v3" })).toBe("");
		expect(loadedWhisperModel({ loaded: true, model_size: "large-v3" })).toBe("large-v3");
	});
});
