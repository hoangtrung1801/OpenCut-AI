import type {
	Chapter,
	EmotionSegment,
	FillerWord,
	SeparatedAudio,
	SilenceRegion,
	TranscriptionSegment,
} from "@/types/ai";
import type { DisplayCaptionSegment } from "@/types/ai";

export interface TranslatedTranscriptData {
	languageCode: string;
	languageName: string;
	segments: TranscriptionSegment[];
	displaySegments?: DisplayCaptionSegment[];
}

export interface SubtitleTrackData {
	trackId: string;
	language: string;
}

/** Transcript data that is safe to restore for a specific project. */
export interface PersistedTranscript {
	segments: TranscriptionSegment[];
	language: string;
	duration: number;
	sourceMediaId: string | null;
	separatedAudio: SeparatedAudio | null;
	fillers: FillerWord[];
	silences: SilenceRegion[];
	chapters: Chapter[];
	translations: TranslatedTranscriptData[];
	subtitleTracks: SubtitleTrackData[];
	speakerNames: Record<string, string>;
	speakerPositions: Record<string, "left" | "right" | "center">;
	emotions: EmotionSegment[];
}
