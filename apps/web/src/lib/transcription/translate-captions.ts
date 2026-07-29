import type {
	BackgroundTask,
} from "@/stores/background-tasks-store";
import type {
	CaptionPostProcessRequest,
	CaptionPostProcessResult,
	ContextualTranslationRequest,
	ContextualTranslationResult,
	ContextualTranslatedSegment,
	DisplayCaptionSegment,
	TranscriptionSegment,
} from "@/types/ai";
import type { CaptionSourceSegment } from "@/lib/transcription/caption";
import type { TranslatedTranscript } from "@/stores/transcript-store";
import { shouldUseSarvamTranslation } from "@/lib/transcription/translation-provider";

export interface TranslateCaptionsArgs {
	targetLanguage: string;
	targetLanguageName: string;
}

interface TranscriptSnapshot {
	language: string;
	segments: TranscriptionSegment[];
}

export interface CaptionTranslationDependencies {
	getTranscript: () => TranscriptSnapshot;
	translateContextual: (
		request: ContextualTranslationRequest,
	) => Promise<ContextualTranslationResult>;
	translateSarvam: (
		segments: TranscriptionSegment[],
		sourceLanguage: string,
		targetLanguage: string,
	) => Promise<ContextualTranslatedSegment[]>;
	postProcessCaptions: (
		request: CaptionPostProcessRequest,
	) => Promise<CaptionPostProcessResult>;
	addTask: (task: Omit<BackgroundTask, "startedAt" | "status">) => void;
	updateTask: (
		id: string,
		updates: Partial<Pick<BackgroundTask, "progress" | "status" | "error" | "completedAt">>,
	) => void;
	storeTranslation: (translation: TranslatedTranscript) => void;
	createTrack: (input: {
		segments: CaptionSourceSegment[];
		languageLabel: string;
		yOffset: number;
	}) => string;
	storeTrack: (track: { trackId: string; language: string }) => void;
	hasExistingSubtitleTrack?: () => boolean;
	now?: () => number;
}

function contextualRequest(
	snapshot: TranscriptSnapshot,
	targetLanguage: string,
): ContextualTranslationRequest {
	return {
		source_language: snapshot.language,
		target_language: targetLanguage,
		segments: snapshot.segments.map((segment) => ({
			id: segment.id,
			text: segment.text,
			start: segment.start,
			end: segment.end,
			words: segment.words.map(({ word, start, end }) => ({ word, start, end })),
		})),
		custom_terms: [],
	};
}

function displaySegments(
	segments: DisplayCaptionSegment[],
): CaptionSourceSegment[] {
	return segments.map((segment) => ({
		text: segment.translation,
		start: segment.start,
		end: segment.end,
		words: [],
	}));
}

function postProcessRequest(
	snapshot: TranscriptSnapshot,
	targetLanguage: string,
	segments: ContextualTranslatedSegment[],
): CaptionPostProcessRequest {
	const sourceById = new Map(snapshot.segments.map((segment) => [segment.id, segment]));
	return {
		source_language: snapshot.language,
		target_language: targetLanguage,
		segments: segments.map((segment) => ({
			id: segment.id,
			source: segment.source,
			translation: segment.translation,
			start: segment.start,
			end: segment.end,
			words: (sourceById.get(segment.id)?.words ?? []).map(({ word, start, end }) => ({
				word,
				start,
				end,
			})),
		})),
	};
}

function transcriptTranslation(
	targetLanguage: string,
	targetLanguageName: string,
	segments: ContextualTranslatedSegment[],
	display: DisplayCaptionSegment[],
): TranslatedTranscript {
	return {
		languageCode: targetLanguage,
		languageName: targetLanguageName,
		segments: segments.map((segment) => ({
			id: segment.id,
			text: segment.translation,
			start: segment.start,
			end: segment.end,
			words: [],
		})),
		displaySegments: display,
	};
}

export async function translateAndAddCaptions(
	args: TranslateCaptionsArgs,
	dependencies: CaptionTranslationDependencies,
): Promise<string> {
	const snapshot = dependencies.getTranscript();
	if (snapshot.segments.length === 0) {
		throw new Error("No transcript segments to translate.");
	}
	if (snapshot.language.toLowerCase() === args.targetLanguage.toLowerCase()) {
		throw new Error("Choose a language different from the transcript language.");
	}

	const taskId = `translation-${args.targetLanguage}-${dependencies.now?.() ?? Date.now()}`;
	dependencies.addTask({
		id: taskId,
		type: "translation",
		label: `${args.targetLanguageName} translation`,
		progress: "Starting...",
	});

	try {
		let display: CaptionSourceSegment[];
		let processedDisplaySegments: DisplayCaptionSegment[];
		let audio: ContextualTranslatedSegment[];
		if (shouldUseSarvamTranslation(snapshot.language, args.targetLanguage)) {
			dependencies.updateTask(taskId, {
				progress: `Translating to ${args.targetLanguageName} via Sarvam...`,
			});
			const originalTranslation = await dependencies.translateSarvam(
					snapshot.segments,
					snapshot.language,
					args.targetLanguage,
			);
			dependencies.updateTask(taskId, { progress: "Splitting captions…" });
			const processed = await dependencies.postProcessCaptions(
				postProcessRequest(snapshot, args.targetLanguage, originalTranslation),
			);
			processedDisplaySegments = processed.display_segments;
			display = displaySegments(processedDisplaySegments);
			audio = processed.audio_segments;
		} else {
			dependencies.updateTask(taskId, {
				progress: "Translating with video context…",
			});
			const result = await dependencies.translateContextual(
				contextualRequest(snapshot, args.targetLanguage),
			);
			processedDisplaySegments = result.display_segments;
			display = displaySegments(processedDisplaySegments);
			audio = result.audio_segments;
		}

		dependencies.updateTask(taskId, { progress: "Adding subtitle track…" });
		dependencies.storeTranslation(
			transcriptTranslation(
				args.targetLanguage,
				args.targetLanguageName,
				audio,
				processedDisplaySegments,
			),
		);
		const trackId = dependencies.createTrack({
			segments: display,
			languageLabel: args.targetLanguageName,
			yOffset: dependencies.hasExistingSubtitleTrack?.() ? 0.28 : 0.38,
		});
		dependencies.storeTrack({
			trackId,
			language: args.targetLanguage,
		});
		dependencies.updateTask(taskId, {
			status: "completed",
			progress: `${display.length} segments`,
			completedAt: Date.now(),
		});
		return trackId;
	} catch (error) {
		const message = error instanceof Error ? error.message : "Translation failed.";
		dependencies.updateTask(taskId, {
			status: "error",
			error: message,
			completedAt: Date.now(),
		});
		throw error;
	}
}
