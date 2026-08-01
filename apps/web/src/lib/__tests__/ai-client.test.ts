import { describe, expect, test } from "bun:test";
import { buildTTSRequestBody } from "@/lib/ai-client";

describe("buildTTSRequestBody", () => {
	test("maps speakerWav to snake_case speaker_wav", () => {
		expect(
			buildTTSRequestBody({
				text: "Hello",
				language: "en",
				speakerWav: "generated/voices/alice.wav",
			}),
		).toEqual({
			text: "Hello",
			language: "en",
			speaker_wav: "generated/voices/alice.wav",
			reference_text: undefined,
			speaker: undefined,
			speed: undefined,
		});
	});

	test("maps cloned voice reference text for OmniVoice", () => {
		expect(
			buildTTSRequestBody({
				text: "Bonjour",
				language: "fr",
				speakerWav: "generated/voices/alice.wav",
				referenceText: "Bonjour, je suis Alice.",
			}),
		).toMatchObject({
			speaker_wav: "generated/voices/alice.wav",
			reference_text: "Bonjour, je suis Alice.",
		});
	});

	test("passes through speaker for voice design", () => {
		expect(
			buildTTSRequestBody({
				text: "Hello",
				language: "en",
				speaker: "female, young adult",
			}),
		).toEqual({
			text: "Hello",
			language: "en",
			speaker_wav: undefined,
			reference_text: undefined,
			speaker: "female, young adult",
			speed: undefined,
		});
	});

	test("passes through speed", () => {
		expect(
			buildTTSRequestBody({ text: "Hello", language: "en", speed: 1.5 }),
		).toEqual({
			text: "Hello",
			language: "en",
			speaker_wav: undefined,
			reference_text: undefined,
			speaker: undefined,
			speed: 1.5,
		});
	});

	test("omits all optional fields when unset", () => {
		expect(
			buildTTSRequestBody({ text: "Hello", language: "en" }),
		).toEqual({
			text: "Hello",
			language: "en",
			speaker_wav: undefined,
			reference_text: undefined,
			speaker: undefined,
			speed: undefined,
		});
	});
});
