import { insertGeneratedAudioElement } from "@/lib/media/generated-audio";
import type { DubbingClipResult, DubbingJobSnapshot } from "@/types/ai";

interface DubbingWorkflowEditor {
	media: {
		addMediaAsset: (args: {
			projectId: string;
			asset: { name: string; type: "audio"; file: File; url: string; duration: number };
		}) => Promise<string>;
		getAssetById: (id: string) => any;
	};
	timeline: {
		getTracks: () => Array<{ id: string; type: string; elements: Array<Record<string, unknown>> }>;
		addTrack: (args: { type: "audio" }) => string;
		insertElement: (args: { placement: { mode: "explicit"; trackId: string }; element: unknown }) => void;
		updateTracks: (tracks: unknown[]) => void;
	};
}

export interface InsertDubbingResultArgs {
	editor: DubbingWorkflowEditor;
	projectId: string;
	baseUrl: string;
	result: NonNullable<DubbingJobSnapshot["result"]>;
	backgroundAudioUrl?: string;
	backgroundDuration?: number;
	sourceMediaId?: string | null;
}

function absoluteUrl(baseUrl: string, url: string): string {
	return /^https?:\/\//i.test(url) ? url : `${baseUrl.replace(/\/$/, "")}/${url.replace(/^\//, "")}`;
}

async function fetchAudioFile(baseUrl: string, url: string, filename: string): Promise<File> {
	const response = await fetch(absoluteUrl(baseUrl, url));
	if (!response.ok) throw new Error(`Dubbing audio download failed (${response.status}).`);
	const blob = await response.blob();
	if (blob.size === 0) throw new Error("Dubbing audio download was empty.");
	return new File([blob], filename, { type: blob.type || "audio/wav" });
}

function muteSourceMedia(editor: DubbingWorkflowEditor, sourceMediaId?: string | null): void {
	if (!sourceMediaId) return;
	let changed = false;
	const tracks = editor.timeline.getTracks();
	const updated = tracks.map((track) => ({
		...track,
		elements: track.elements.map((element) => {
			if (element.mediaId === sourceMediaId && element.muted !== true) {
				changed = true;
				return { ...element, muted: true };
			}
			return element;
		}),
	}));
	if (changed) editor.timeline.updateTracks(updated);
}

export async function insertDubbingResult({
	editor,
	projectId,
	baseUrl,
	result,
	backgroundAudioUrl,
	backgroundDuration,
	sourceMediaId,
}: InsertDubbingResultArgs): Promise<{ audioTrackId: string; backgroundTrackId?: string }> {
	const audioTrackId = editor.timeline.addTrack({ type: "audio" });
	for (const clip of result.clips) {
		const file = await fetchAudioFile(baseUrl, clip.audio_url, `dubbing-${clip.id}.wav`);
		await insertGeneratedAudioElement({
			editor: editor as any,
			projectId,
			trackId: audioTrackId,
			file,
			name: `Dub: ${clip.text}`,
			startTime: clip.start,
			duration: clip.duration,
	});
	}

	let backgroundTrackId: string | undefined;
	if (backgroundAudioUrl && backgroundDuration && backgroundDuration > 0) {
		backgroundTrackId = editor.timeline.addTrack({ type: "audio" });
		const file = await fetchAudioFile(baseUrl, backgroundAudioUrl, "original-background.wav");
		await insertGeneratedAudioElement({
			editor: editor as any,
			projectId,
			trackId: backgroundTrackId,
			file,
			name: "Original background",
			startTime: 0,
			duration: backgroundDuration,
		});
	}

	muteSourceMedia(editor, sourceMediaId);
	return { audioTrackId, backgroundTrackId };
}

export type { DubbingClipResult };
