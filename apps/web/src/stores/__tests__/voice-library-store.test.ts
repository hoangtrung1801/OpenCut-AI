import { describe, expect, test, beforeEach } from "bun:test";
import { useVoiceLibraryStore } from "@/stores/voice-library-store";

function resetStore() {
	useVoiceLibraryStore.setState({ voices: [] });
}

describe("useVoiceLibraryStore", () => {
	beforeEach(resetStore);

	test("addVoice appends a new voice", () => {
		useVoiceLibraryStore.getState().addVoice({
			id: "1",
			name: "Alice",
			path: "generated/voices/alice.wav",
			createdAt: 1000,
		});

		expect(useVoiceLibraryStore.getState().voices).toEqual([
			{ id: "1", name: "Alice", path: "generated/voices/alice.wav", createdAt: 1000 },
		]);
	});

	test("addVoice with a duplicate name replaces the existing entry in place", () => {
		useVoiceLibraryStore.getState().addVoice({
			id: "1",
			name: "Alice",
			path: "generated/voices/alice.wav",
			createdAt: 1000,
		});
		useVoiceLibraryStore.getState().addVoice({
			id: "2",
			name: "Alice",
			path: "generated/voices/alice-v2.wav",
			createdAt: 2000,
		});

		const voices = useVoiceLibraryStore.getState().voices;
		expect(voices).toHaveLength(1);
		expect(voices[0]).toEqual({
			id: "2",
			name: "Alice",
			path: "generated/voices/alice-v2.wav",
			createdAt: 2000,
		});
	});

	test("removeVoice deletes by id", () => {
		useVoiceLibraryStore.getState().addVoice({
			id: "1",
			name: "Alice",
			path: "generated/voices/alice.wav",
			createdAt: 1000,
		});
		useVoiceLibraryStore.getState().addVoice({
			id: "2",
			name: "Bob",
			path: "generated/voices/bob.wav",
			createdAt: 2000,
		});

		useVoiceLibraryStore.getState().removeVoice("1");

		expect(useVoiceLibraryStore.getState().voices).toEqual([
			{ id: "2", name: "Bob", path: "generated/voices/bob.wav", createdAt: 2000 },
		]);
	});
});
