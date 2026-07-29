import { aiClient } from "@/lib/ai-client";
import { useTranscriptStore } from "@/stores/transcript-store";
import { useBackgroundTasksStore } from "@/stores/background-tasks-store";
import { insertDubbingResult } from "@/lib/transcription/dubbing-workflow";
import type { DubbingJobRequest, DubbingVoice, TranscriptionSegment } from "@/types/ai";
import type { EditorCore } from "@/core";

export interface DubbingRunOptions {
	targetLanguage: string;
	voiceDesign?: string;
	voiceClonePath?: string;
	pace?: number;
	segmentIndices?: number[];
}

function voiceFor(options: DubbingRunOptions): DubbingVoice {
	if (options.voiceClonePath) return { mode: "clone", speaker_wav: options.voiceClonePath };
	if (options.voiceDesign?.trim()) return { mode: "design", speaker: options.voiceDesign.trim() };
	return { mode: "auto" };
}

function buildRequest(
	options: DubbingRunOptions,
	transcript: ReturnType<typeof useTranscriptStore.getState>,
): DubbingJobRequest {
	const translation = transcript.translations.find((item) => item.languageCode === options.targetLanguage);
	if (!translation) {
		throw new Error("Translate captions to the target language before dubbing.");
	}
	const sourceById = new Map(transcript.segments.map((segment) => [segment.id, segment]));
	const selected = options.segmentIndices
		?.map((index) => transcript.segments[index])
		.filter((segment): segment is TranscriptionSegment => Boolean(segment));
	const selectedIds = selected ? new Set(selected.map((segment) => segment.id)) : null;
	const parents = translation.segments
		.filter((segment) => !selectedIds || selectedIds.has(segment.id))
		.map((segment) => {
			const source = sourceById.get(segment.id);
			return {
				id: segment.id,
				source: source?.text ?? segment.text,
				translation: segment.text,
				start: segment.start,
				end: segment.end,
			};
		});
	const displays = (translation.displaySegments ?? translation.segments.map((segment) => ({
			id: segment.id,
			parent_id: segment.id,
			part_index: 0,
			source: sourceById.get(segment.id)?.text ?? segment.text,
			translation: segment.text,
			start: segment.start,
			end: segment.end,
		}))).filter((segment) => !selectedIds || selectedIds.has(segment.parent_id));
	return {
		source_language: transcript.language,
		target_language: options.targetLanguage,
		audio_segments: parents,
		display_segments: displays,
		voice: voiceFor(options),
		pace: options.pace ?? 1,
	};
}

export async function runDubbingJob({
	editor,
	options,
}: {
	editor: EditorCore;
	options: DubbingRunOptions;
}): Promise<void> {
	const transcript = useTranscriptStore.getState();
	const activeProject = editor.project.getActive();
	if (!activeProject) throw new Error("No active project.");
	const request = buildRequest(options, transcript);
	if (request.audio_segments.length === 0 || request.display_segments.length === 0) {
		throw new Error("No transcript segments available for dubbing.");
	}
	const taskId = `dubbing-${Date.now()}`;
	const { addTask, updateTask } = useBackgroundTasksStore.getState();
	addTask({ id: taskId, type: "dubbing", label: `Dubbing to ${options.targetLanguage}`, progress: "Queued…" });
	try {
		const accepted = await aiClient.createDubbingJob(request);
		let snapshot = await aiClient.getDubbingJob(accepted.job_id);
		while (snapshot.status !== "completed" && snapshot.status !== "failed") {
			updateTask(taskId, { progress: `${snapshot.status} (${snapshot.completed_clips}/${snapshot.total_clips})` });
			await new Promise((resolve) => setTimeout(resolve, 250));
			snapshot = await aiClient.getDubbingJob(accepted.job_id);
		}
		if (snapshot.status === "failed" || !snapshot.result) {
			throw new Error(snapshot.error?.message ?? "Dubbing failed.");
		}
		updateTask(taskId, { progress: "Placing audio clips…" });
		await insertDubbingResult({
			editor: editor as any,
			projectId: activeProject.metadata.id,
			baseUrl: aiClient.getBaseUrl(),
			result: snapshot.result,
			backgroundAudioUrl: transcript.separatedAudio?.background_url,
			backgroundDuration: transcript.duration,
			sourceMediaId: transcript.sourceMediaId,
		});
		updateTask(taskId, { status: "completed", progress: `${snapshot.result.clips.length} clips`, completedAt: Date.now() });
	} catch (error) {
		const message = error instanceof Error ? error.message : "Dubbing failed.";
		updateTask(taskId, { status: "error", error: message, completedAt: Date.now() });
		throw error;
	}
}

export { buildRequest as buildDubbingRequest, voiceFor as buildDubbingVoice };
