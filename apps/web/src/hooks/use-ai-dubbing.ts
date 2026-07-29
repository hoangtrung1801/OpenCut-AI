import { useCallback } from "react";
import { useEditor } from "@/hooks/use-editor";
import { useTranscriptStore } from "@/stores/transcript-store";
import { useBackgroundTasksStore } from "@/stores/background-tasks-store";
import { invokeAction } from "@/lib/actions";
import type { TTSRequest } from "@/types/ai";

export type DubbingEngine = "local";

export interface DubbingOptions {
	targetLanguage: string;
	engine?: DubbingEngine;
	voiceId?: string;
	voiceDesign?: string;
	voiceClonePath?: string;
	pace?: number;
	segmentIndices?: number[];
}

export interface DubbingProgress {
	currentSegment: number;
	totalSegments: number;
	currentText: string;
	phase: "queued" | "preparing" | "generating" | "fitting" | "placing" | "done" | "error";
}

export function buildLocalTTSRequest(
	text: string,
	language: string,
	voiceDesign?: string,
	voiceClonePath?: string,
): TTSRequest {
	const request: TTSRequest = { text, language };
	if (voiceClonePath) {
		request.speakerWav = voiceClonePath;
		return request;
	}
	const speaker = voiceDesign?.trim();
	if (speaker) request.speaker = speaker;
	return request;
}

function parseProgress(value: string): Pick<DubbingProgress, "currentSegment" | "totalSegments" | "phase"> {
	const match = value.match(/(\d+)\/(\d+)/);
	const currentSegment = match ? Number(match[1]) : 0;
	const totalSegments = match ? Number(match[2]) : 0;
	const phase = value.toLowerCase().includes("placing") ? "placing" :
		value.toLowerCase().includes("generating") ? "generating" :
		value.toLowerCase().includes("fitting") ? "fitting" :
		value.toLowerCase().includes("preparing") ? "preparing" : "queued";
	return { currentSegment, totalSegments, phase };
}

export function useAIDubbing() {
	const editor = useEditor();
	const segments = useTranscriptStore((s) => s.segments);
	const task = useBackgroundTasksStore((s) => [...s.tasks].reverse().find((item) => item.type === "dubbing"));

	const runDubbing = useCallback((options: DubbingOptions) => {
		if (segments.length === 0) return;
		invokeAction("generate-dubbing", {
			targetLanguage: options.targetLanguage,
			voiceDesign: options.voiceDesign,
			voiceClonePath: options.voiceClonePath,
			pace: options.pace,
			segmentIndices: options.segmentIndices,
		});
	}, [segments.length]);

	const parsed = task ? parseProgress(task.progress) : {
		currentSegment: 0,
		totalSegments: 0,
		phase: "queued" as const,
	};
	return {
		runDubbing,
		isDubbing: task?.status === "running",
		progress: task
			? {
				...parsed,
				currentText: task.progress,
				phase: task.status === "completed" ? "done" : task.status === "error" ? "error" : parsed.phase,
			}
			: null,
		editor,
	};
}
