import { buildUploadAudioElement } from "@/lib/timeline/element-utils";
import type { InsertElementParams } from "@/lib/commands/timeline/element/insert-element";
import type { MediaAsset } from "@/types/assets";

interface GeneratedAudioMediaManager {
	addMediaAsset({
		projectId,
		asset,
	}: {
		projectId: string;
		asset: Omit<MediaAsset, "id">;
	}): Promise<string>;
	getAssetById(id: string): MediaAsset | undefined;
}

interface GeneratedAudioEditor {
	media: GeneratedAudioMediaManager;
	timeline: {
		insertElement(params: InsertElementParams): void;
	};
}

export interface GeneratedAudioInsertionParams {
	editor: GeneratedAudioEditor;
	projectId: string;
	trackId: string;
	file: File;
	name: string;
	startTime: number;
	duration: number;
	trimStart?: number;
	trimEnd?: number;
	volume?: number;
	muted?: boolean;
}

export async function insertGeneratedAudioElement({
	editor,
	projectId,
	trackId,
	file,
	name,
	startTime,
	duration,
	trimStart = 0,
	trimEnd = 0,
	volume = 1,
	muted = false,
}: GeneratedAudioInsertionParams): Promise<{ mediaId: string }> {
	const url = URL.createObjectURL(file);
	let mediaId: string;

	try {
		mediaId = await editor.media.addMediaAsset({
			projectId,
			asset: {
				name: file.name,
				type: "audio",
				file,
				url,
				duration,
			},
		});
	} catch (error) {
		URL.revokeObjectURL(url);
		throw error;
	}

	if (!editor.media.getAssetById(mediaId)) {
		URL.revokeObjectURL(url);
		throw new Error("Failed to persist generated audio");
	}

	const element = buildUploadAudioElement({
		mediaId,
		name,
		duration,
		startTime,
	});
	element.trimStart = trimStart;
	element.trimEnd = trimEnd;
	element.volume = volume;
	element.muted = muted;

	editor.timeline.insertElement({
		placement: { mode: "explicit", trackId },
		element,
	});

	return { mediaId };
}
