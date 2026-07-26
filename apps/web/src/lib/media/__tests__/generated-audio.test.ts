import { describe, expect, test } from "bun:test";
import type { MediaAsset } from "@/types/assets";
import type { InsertElementParams } from "@/lib/commands/timeline/element/insert-element";
import { insertGeneratedAudioElement } from "@/lib/media/generated-audio";

describe("insertGeneratedAudioElement", () => {
	test("persists generated audio before inserting an upload element", async () => {
		const assets = new Map<string, MediaAsset>();
		let insertion: InsertElementParams | undefined;
		const editor = {
			media: {
				async addMediaAsset({
					asset,
				}: {
					projectId: string;
					asset: Omit<MediaAsset, "id">;
				}) {
					const id = "generated-media-id";
					assets.set(id, { ...asset, id });
					return id;
				},
				getAssetById(id: string) {
					return assets.get(id);
				},
			},
			timeline: {
				insertElement(args: InsertElementParams) {
					insertion = args;
				},
			},
		};

		await insertGeneratedAudioElement({
			editor,
			projectId: "project-id",
			trackId: "track-id",
			file: new File(["audio"], "voiceover.wav", { type: "audio/wav" }),
			name: "Voiceover",
			startTime: 2,
			duration: 3,
		});

		expect(assets.get("generated-media-id")?.type).toBe("audio");
		expect(insertion?.element).toMatchObject({
			type: "audio",
			sourceType: "upload",
			mediaId: "generated-media-id",
			name: "Voiceover",
			startTime: 2,
			duration: 3,
			trimStart: 0,
			trimEnd: 0,
			volume: 1,
		});
		expect(insertion?.placement).toEqual({
			mode: "explicit",
			trackId: "track-id",
		});
	});

	test("does not insert an element when media persistence rolls back", async () => {
		let inserted = false;
		const editor = {
			media: {
				async addMediaAsset() {
					return "rolled-back-media-id";
				},
				getAssetById() {
					return undefined;
				},
			},
			timeline: {
				insertElement() {
					inserted = true;
				},
			},
		};

		await expect(
			insertGeneratedAudioElement({
				editor,
				projectId: "project-id",
				trackId: "track-id",
				file: new File(["audio"], "voiceover.wav", { type: "audio/wav" }),
				name: "Voiceover",
				startTime: 0,
				duration: 1,
			}),
		).rejects.toThrow("Failed to persist generated audio");
		expect(inserted).toBe(false);
	});

	test("persists generated MP3 files as audio assets", async () => {
		let savedAsset: Omit<MediaAsset, "id"> | undefined;
		const editor = {
			media: {
				async addMediaAsset({
					asset,
				}: {
					projectId: string;
					asset: Omit<MediaAsset, "id">;
				}) {
					savedAsset = asset;
					return "generated-mp3-id";
				},
				getAssetById(id: string) {
					return id === "generated-mp3-id"
						? ({ ...savedAsset, id } as MediaAsset)
						: undefined;
				},
			},
			timeline: {
				insertElement() {},
			},
		};

		await insertGeneratedAudioElement({
			editor,
			projectId: "project-id",
			trackId: "track-id",
			file: new File(["audio"], "voiceover.mp3", { type: "audio/mpeg" }),
			name: "Voiceover",
			startTime: 0,
			duration: 2,
		});

		expect(savedAsset).toMatchObject({
			name: "voiceover.mp3",
			type: "audio",
			duration: 2,
		});
	});
});
