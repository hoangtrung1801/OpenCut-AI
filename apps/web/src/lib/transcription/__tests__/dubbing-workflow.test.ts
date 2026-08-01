import { afterEach, describe, expect, mock, test } from "bun:test";
import {
	insertDubbingResult,
	insertSeparatedAudioStems,
} from "@/lib/transcription/dubbing-workflow";

const originalFetch = globalThis.fetch;

afterEach(() => {
	globalThis.fetch = originalFetch;
	mock.restore();
});

function fakeEditor() {
	const tracks = [{
		id: "source-track",
		type: "video" as const,
		isMain: true,
		muted: false,
		hidden: false,
		elements: [{
			id: "source-element",
			type: "video" as const,
			mediaId: "source-media",
			name: "source",
			startTime: 0,
			duration: 2,
			trimStart: 0,
			trimEnd: 0,
		}],
	}];
	const inserted: unknown[] = [];
	const addedAssets: unknown[] = [];
	return {
		project: { getActive: () => ({ id: "project-1" }) },
		media: {
			async addMediaAsset({ asset }: { projectId: string; asset: unknown }) {
				addedAssets.push(asset);
				return `media-${addedAssets.length}`;
			},
			getAssetById: (id: string) => ({ id }),
		},
		timeline: {
			getTracks: () => tracks,
			addTrack: mock(() => "dub-track"),
			insertElement: ({ element }: { element: unknown }) => inserted.push(element),
			updateTracks: (next: unknown) => {
				tracks.splice(0, tracks.length, ...(next as typeof tracks));
			},
		},
		inserted,
		addedAssets,
	};
}

describe("insertDubbingResult", () => {
	test("inserts each caption clip, reuses background stem, and mutes source", async () => {
		const editor = fakeEditor();
		globalThis.fetch = mock(async (url: string) =>
			new Response(new Uint8Array([1, 2, 3]), {
				status: 200,
				headers: { "Content-Type": "audio/wav" },
			}),
		) as unknown as typeof fetch;

		await insertDubbingResult({
			editor,
			projectId: "project-1",
			baseUrl: "http://localhost:8420",
			sourceMediaId: "source-media",
			backgroundAudioUrl: "/api/transcribe/artifacts/a/background",
			backgroundDuration: 2,
			result: {
				clips: [
					{ id: 10, parent_id: 1, part_index: 0, text: "Xin", start: 0, end: 0.5, duration: 0.5, audio_url: "/generated/10.wav" },
					{ id: 11, parent_id: 1, part_index: 1, text: "chào", start: 0.5, end: 1, duration: 0.5, audio_url: "/generated/11.wav" },
				],
				captions: [],
				srt: "",
			},
		});

		expect(editor.timeline.addTrack).toHaveBeenCalledTimes(2);
		expect(editor.inserted).toHaveLength(3);
		expect((editor.timeline.getTracks()[0]?.elements?.[0] as { muted?: boolean })?.muted).toBe(true);
		expect(editor.addedAssets).toHaveLength(3);
	});

	test("inserts returned vocal and background stems as separate tracks", async () => {
		const editor = fakeEditor();
		let trackNumber = 0;
		editor.timeline.addTrack = mock(() => `stem-track-${++trackNumber}`);
		const fetchedUrls: string[] = [];
		globalThis.fetch = mock(async (url: string) => {
			fetchedUrls.push(url);
			return new Response(new Uint8Array([1, 2, 3]), {
				status: 200,
				headers: { "Content-Type": "audio/mpeg" },
			});
		}) as unknown as typeof fetch;

		await insertSeparatedAudioStems({
			editor,
			projectId: "project-1",
			baseUrl: "http://localhost:8420",
			duration: 2,
			separatedAudio: {
				vocals_url: "/api/transcribe/artifacts/a/vocals",
				background_url: "/api/transcribe/artifacts/a/background",
			},
		});

		expect(editor.timeline.addTrack).toHaveBeenCalledTimes(2);
		expect(editor.inserted).toHaveLength(2);
		expect(fetchedUrls).toEqual([
			"http://localhost:8420/api/transcribe/artifacts/a/vocals",
			"http://localhost:8420/api/transcribe/artifacts/a/background",
		]);
		expect(editor.addedAssets).toHaveLength(2);
	});

	test("reuses a background stem already inserted during transcription", async () => {
		const editor = fakeEditor();
		editor.timeline.getTracks().push({
			id: "background-track",
			type: "audio",
			isMain: false,
			muted: false,
			hidden: false,
			elements: [{
				id: "background-element",
				type: "audio",
				name: "Separated background",
				startTime: 0,
				duration: 2,
			}],
		} as any);
		globalThis.fetch = mock(async () => new Response(new Uint8Array([1, 2, 3]), {
			status: 200,
			headers: { "Content-Type": "audio/wav" },
		})) as unknown as typeof fetch;

		await insertDubbingResult({
			editor,
			projectId: "project-1",
			baseUrl: "http://localhost:8420",
			backgroundAudioUrl: "/api/transcribe/artifacts/a/background",
			backgroundDuration: 2,
			result: {
				clips: [{ id: 10, parent_id: 1, part_index: 0, text: "Xin", start: 0, end: 0.5, duration: 0.5, audio_url: "/generated/10.wav" }],
				captions: [],
				srt: "",
			},
		});

		expect(editor.timeline.addTrack).toHaveBeenCalledTimes(1);
		expect(editor.inserted).toHaveLength(1);
	});
});
