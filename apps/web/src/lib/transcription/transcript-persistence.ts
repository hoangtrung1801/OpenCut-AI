import type { PersistedTranscript } from "@/types/transcript";

export function createTranscriptSnapshot(
	state: PersistedTranscript,
): PersistedTranscript {
	return structuredClone({
		segments: state.segments,
		language: state.language,
		duration: state.duration,
		sourceMediaId: state.sourceMediaId,
		separatedAudio: state.separatedAudio,
		fillers: state.fillers,
		silences: state.silences,
		chapters: state.chapters,
		translations: state.translations,
		subtitleTracks: state.subtitleTracks,
		speakerNames: state.speakerNames,
		speakerPositions: state.speakerPositions,
		emotions: state.emotions,
	});
}

export function normalizeTranscriptSnapshot(
	value: unknown,
): PersistedTranscript | null {
	if (!value || typeof value !== "object") {
		return null;
	}

	const snapshot = value as Partial<PersistedTranscript>;
	if (!Array.isArray(snapshot.segments)) return null;

	return {
		segments: snapshot.segments,
		language: snapshot.language ?? "auto",
		duration: snapshot.duration ?? 0,
		sourceMediaId: snapshot.sourceMediaId ?? null,
		separatedAudio: snapshot.separatedAudio ?? null,
		fillers: snapshot.fillers ?? [],
		silences: snapshot.silences ?? [],
		chapters: snapshot.chapters ?? [],
		translations: snapshot.translations ?? [],
		subtitleTracks: snapshot.subtitleTracks ?? [],
		speakerNames: snapshot.speakerNames ?? {},
		speakerPositions: snapshot.speakerPositions ?? {},
		emotions: snapshot.emotions ?? [],
	};
}
