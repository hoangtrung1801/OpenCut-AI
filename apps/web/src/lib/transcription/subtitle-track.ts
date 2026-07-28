import type { EditorCore } from "@/core";
import { DEFAULT_TEXT_ELEMENT } from "@/constants/text-constants";
import type { TextElement } from "@/types/timeline";
import type { CaptionSourceSegment } from "@/lib/transcription/caption";

export interface SubtitleTrackInput {
	segments: CaptionSourceSegment[];
	languageLabel: string;
	yOffset: number;
}

export function buildCaptionTrackElement({
	languageLabel,
	index,
	subtitleY,
	segment,
}: {
	languageLabel: string;
	index: number;
	subtitleY: number;
	segment: CaptionSourceSegment;
}): Omit<TextElement, "id"> {
	const wordTimings = segment.words?.map((word) => ({
		word: word.word,
		start: word.start - segment.start,
		end: word.end - segment.start,
	}));

	return {
		...DEFAULT_TEXT_ELEMENT,
		name: `${languageLabel} ${index + 1}`,
		content: segment.text,
		duration: segment.end - segment.start,
		startTime: segment.start,
		fontSize: 4,
		fontWeight: "bold",
		color: "#ffffff",
		highlightColor: "#FACC15",
		...(wordTimings && wordTimings.length > 0 ? { wordTimings } : {}),
		textAlign: "center",
		background: {
			enabled: true,
			color: "#000000",
			cornerRadius: 4,
			paddingX: 12,
			paddingY: 6,
			offsetX: 0,
			offsetY: 0,
		},
		opacity: 0.95,
		transform: {
			scale: 1,
			position: { x: 0, y: subtitleY },
			rotate: 0,
		},
	};
}

export function createSubtitleTrack(
	editor: EditorCore,
	{ segments, languageLabel, yOffset }: SubtitleTrackInput,
): string {
	const trackId = editor.timeline.addTrack({ type: "text", index: 0 });
	editor.timeline.renameTrack({
		trackId,
		name: `Subs: ${languageLabel}`,
	});
	const canvasSize = editor.project.getActive().settings.canvasSize;
	const subtitleY = canvasSize.height * yOffset;

	for (let index = 0; index < segments.length; index += 1) {
		const segment = segments[index];
		editor.timeline.insertElement({
			placement: { mode: "explicit", trackId },
			element: buildCaptionTrackElement({
				languageLabel,
				index,
				subtitleY,
				segment,
			}),
		});
	}

	return trackId;
}
