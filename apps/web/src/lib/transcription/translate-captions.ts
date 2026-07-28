import type {
	BackgroundTask,
} from "@/stores/background-tasks-store";
import type {
	ContextualTranslationRequest,
	ContextualTranslationResult,
	ContextualTranslatedSegment,
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
		})),
		custom_terms: [],
	};
}

function translatedSegments(
	segments: ContextualTranslatedSegment[],
): CaptionSourceSegment[] {
	return segments.map((segment) => ({
		text: segment.translation,
		start: segment.start,
		end: segment.end,
		words: [],
	}));
}

function transcriptTranslation(
	targetLanguage: string,
	targetLanguageName: string,
	segments: CaptionSourceSegment[],
): TranslatedTranscript {
	return {
		languageCode: targetLanguage,
		languageName: targetLanguageName,
		segments: segments.map((segment, index) => ({
			id: index,
			text: segment.text,
			start: segment.start,
			end: segment.end,
			words: [],
		})),
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
		let translated: CaptionSourceSegment[];
		if (shouldUseSarvamTranslation(snapshot.language, args.targetLanguage)) {
			dependencies.updateTask(taskId, {
				progress: `Translating to ${args.targetLanguageName} via Sarvam...`,
			});
			translated = translatedSegments(
				await dependencies.translateSarvam(
					snapshot.segments,
					snapshot.language,
					args.targetLanguage,
				),
			);
		} else {
			dependencies.updateTask(taskId, {
				progress: "Translating with video context…",
			});
			const result = await dependencies.translateContextual(
				contextualRequest(snapshot, args.targetLanguage),
			);
			translated = translatedSegments(result.segments);
		}

		dependencies.updateTask(taskId, { progress: "Adding subtitle track…" });
		dependencies.storeTranslation(
			transcriptTranslation(
				args.targetLanguage,
				args.targetLanguageName,
				translated,
			),
		);
		const trackId = dependencies.createTrack({
			segments: translated,
			languageLabel: args.targetLanguageName,
			yOffset: dependencies.hasExistingSubtitleTrack?.() ? 0.28 : 0.38,
		});
		dependencies.storeTrack({
			trackId,
			language: args.targetLanguage,
		});
		dependencies.updateTask(taskId, {
			status: "completed",
			progress: `${translated.length} segments`,
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
