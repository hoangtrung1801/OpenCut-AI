import { Button } from "@/components/ui/button";
import { PanelView } from "@/components/editor/panels/assets/views/base-view";
import {
	Select,
	SelectContent,
	SelectGroup,
	SelectItem,
	SelectLabel,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { useState, useRef } from "react";
import { useEditor } from "@/hooks/use-editor";
import { WHISPER_LANGUAGES } from "@/constants/transcription-constants";
import { LANGUAGES } from "@/constants/language-constants";
import {
	SARVAM_STT_LANGUAGES,
	SARVAM_LANGUAGE_MAP,
	SARVAM_SUPPORTED_CODES,
	isSarvamSTTSupported,
} from "@/constants/sarvam-constants";
import { SMALLEST_STT_LANGUAGES } from "@/constants/smallest-constants";
import type { TranscriptionLanguage, TranscriptionEngine } from "@/types/transcription";

import { Spinner } from "@/components/ui/spinner";
import { Label } from "@/components/ui/label";
import { useTranscriptStore } from "@/stores/transcript-store";
import { buildCaptionChunks } from "@/lib/transcription/caption";
import { createSubtitleTrack } from "@/lib/transcription/subtitle-track";
import { getTranslationControlState } from "@/lib/transcription/translation-control";
import { shouldUseSarvamTranslation } from "@/lib/transcription/translation-provider";
import { invokeAction } from "@/lib/actions";
import { getElementsAtTime, hasMediaId } from "@/lib/timeline";
import { toast } from "sonner";
import { aiClient } from "@/lib/ai-client";
import type { TimelineElement } from "@/types/timeline";
import { useBackgroundTasksStore } from "@/stores/background-tasks-store";

export function Captions() {
	const [selectedEngine, setSelectedEngine] = useState<TranscriptionEngine>("whisper");
	const [selectedLanguage, setSelectedLanguage] =
		useState<TranscriptionLanguage>("auto");
	const [isProcessing, setIsProcessing] = useState(false);
	const [processingStep, setProcessingStep] = useState("");
	const [error, setError] = useState<string | null>(null);
	const [translateLanguage, setTranslateLanguage] = useState("es");
	const containerRef = useRef<HTMLDivElement>(null);
	const segments = useTranscriptStore((s) => s.segments);
	const subtitleTracks = useTranscriptStore((s) => s.subtitleTracks);
	const setSubtitleTracks = useTranscriptStore((s) => s.setSubtitleTracks);
	const addSubtitleTrackState = useTranscriptStore((s) => s.addSubtitleTrack);
	const removeSubtitleTrackState = useTranscriptStore((s) => s.removeSubtitleTrack);
	const backgroundTasks = useBackgroundTasksStore((s) => s.tasks);
	const editor = useEditor();
	const translationTask = [...backgroundTasks]
		.reverse()
		.find((task) => task.type === "translation" && task.status === "running");
	const isTranslating = translationTask !== undefined;
	const translatingStep = translationTask?.progress ?? "";

	// Determine which languages to show based on engine
	const availableLanguages = selectedEngine === "sarvam"
		? SARVAM_STT_LANGUAGES
		: selectedEngine === "smallest"
			? SMALLEST_STT_LANGUAGES
			: WHISPER_LANGUAGES;

	// Filter out tracks that no longer exist on the timeline (user may have deleted them)
	const timelineTracks = editor.timeline.getTracks();
	const timelineTrackIds = new Set(timelineTracks.map((t) => t.id));
	const activeSubtitleTracks = subtitleTracks.filter((t) =>
		timelineTrackIds.has(t.trackId),
	);
	const translationControl = getTranslationControlState({
		segmentCount: segments.length,
		targetLanguage: translateLanguage,
		activeLanguages: activeSubtitleTracks.map((track) => track.language),
		translating: isTranslating,
	});

	// Sync state if tracks were removed externally
	if (activeSubtitleTracks.length !== subtitleTracks.length) {
		// Use a microtask to avoid setState during render
		queueMicrotask(() => setSubtitleTracks(activeSubtitleTracks));
	}

	/** Determine the effective engine for a given language code */
	const getEffectiveEngine = (langCode: string): TranscriptionEngine => {
		if (selectedEngine === "sarvam") return "sarvam";
		if (selectedEngine === "smallest") return "smallest";
		// Auto-switch to Sarvam if an Indian language is explicitly selected with Whisper
		if (langCode !== "auto" && isSarvamSTTSupported(langCode) && !WHISPER_LANGUAGES.some(l => l.code === langCode)) {
			return "sarvam";
		}
		return "whisper";
	};

	const handleGenerateTranscript = async () => {
		const taskId = `transcription-${Date.now()}`;
		const bgTasks = useBackgroundTasksStore.getState();

		try {
			setIsProcessing(true);
			setError(null);

			const engine = getEffectiveEngine(selectedLanguage);
			const engineLabel = engine === "sarvam" ? "Sarvam AI" : engine === "smallest" ? "Smallest AI" : "Whisper";

			bgTasks.addTask({
				id: taskId,
				type: "transcription",
				label: `Transcription (${engineLabel})`,
				progress: "Starting...",
			});

			// Remove existing subtitle tracks before re-transcribing
			for (const track of activeSubtitleTracks) {
				try {
					editor.timeline.removeTrack({ trackId: track.trackId });
				} catch {
					// Track may already be gone
				}
			}
			setSubtitleTracks([]);

			// Find the media file from the timeline
			setProcessingStep("Finding media...");
			bgTasks.updateTask(taskId, { progress: "Finding media..." });
			const tracks = editor.timeline.getTracks();
			let foundMediaId: string | null = null;

			for (const track of tracks) {
				for (const element of track.elements) {
					if (
						(track.type === "video" || track.type === "audio") &&
						hasMediaId(element as TimelineElement)
					) {
						foundMediaId = (element as TimelineElement & { mediaId: string }).mediaId;
						break;
					}
				}
				if (foundMediaId) break;
			}

			if (!foundMediaId) {
				setError("No video or audio found on the timeline. Import a file first.");
				return;
			}

			const mediaAsset = editor.media
				.getAssets()
				.find((asset) => asset.id === foundMediaId);

			if (!mediaAsset?.file) {
				setError("Cannot access the media file for transcription.");
				return;
			}

			// Send to appropriate transcription service
			setProcessingStep(`Transcribing via ${engineLabel}...`);
			bgTasks.updateTask(taskId, { progress: `Transcribing via ${engineLabel}...` });

			// Ensure the file has a proper extension — the backend rejects files without one
			const mimeToExt: Record<string, string> = {
				"video/mp4": ".mp4",
				"video/webm": ".webm",
				"video/quicktime": ".mov",
				"video/x-matroska": ".mkv",
				"video/avi": ".avi",
				"audio/mpeg": ".mp3",
				"audio/wav": ".wav",
				"audio/x-wav": ".wav",
				"audio/ogg": ".ogg",
				"audio/flac": ".flac",
				"audio/aac": ".aac",
				"audio/mp4": ".m4a",
			};

			let file = mediaAsset.file;
			const fileName = file.name || "";
			const hasExtension = fileName.includes(".") && fileName.split(".").pop()!.length > 0;

			if (!hasExtension) {
				const ext = mimeToExt[file.type] || ".mp4";
				const newName = fileName ? `${fileName}${ext}` : `media${ext}`;
				file = new File([file], newName, { type: file.type || "video/mp4" });
			}

			let result;
			if (engine === "sarvam") {
				// Use Sarvam AI for Indian languages
				const sarvamLangCode = selectedLanguage === "auto"
					? undefined
					: SARVAM_LANGUAGE_MAP[selectedLanguage] || undefined;
				result = await aiClient.sarvamTranscribe(file, sarvamLangCode);
			} else if (engine === "smallest") {
				// Use Smallest AI Pulse for multilingual STT
				const language = selectedLanguage === "auto" ? "en" : selectedLanguage;
				result = await aiClient.smallestTranscribe(file, language);
			} else {
				// Use Whisper (local)
				const language = selectedLanguage === "auto" ? undefined : selectedLanguage;
				result = await aiClient.transcribe(file, language);
			}

			setProcessingStep("Processing segments...");
			bgTasks.updateTask(taskId, { progress: "Processing segments..." });

			const timelineDuration = editor.timeline.getTotalDuration();

			// Filter out hallucinated segments beyond the actual duration
			// For Sarvam results, also allow Indic Unicode ranges through
			const validSegments = result.segments.filter((seg) => {
				if (seg.start >= timelineDuration) return false;
				// Keep Latin, Cyrillic, CJK, Kana, Devanagari, Bengali, Gurmukhi, Gujarati,
			// Oriya, Tamil, Telugu, Kannada, Malayalam, Sinhala, Arabic/Nastaliq (Urdu),
			// Meitei (Manipuri), Ol Chiki (Santali)
			const cleanText = seg.text.replace(/[^a-zA-Z0-9\u00C0-\u024F\u0400-\u04FF\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF\u0900-\u097F\u0980-\u09FF\u0A00-\u0A7F\u0A80-\u0AFF\u0B00-\u0B7F\u0B80-\u0BFF\u0C00-\u0C7F\u0C80-\u0CFF\u0D00-\u0D7F\u0D80-\u0DFF\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF\uABC0-\uABFF\u1C50-\u1C7F]/g, "").trim();
				if (cleanText.length === 0) return false;
				if (seg.end <= seg.start) return false;
				return true;
			}).map((seg) => ({
				...seg,
				end: Math.min(seg.end, timelineDuration),
			}));

			if (validSegments.length === 0) {
				setError("No speech detected in the video. Try a different language or check that the video has audio.");
				return;
			}

			// Populate transcript store — segments already have word-level detail from backend
			const transcriptSegments = validSegments.map((seg, index) => ({
				id: index,
				text: seg.text,
				start: seg.start,
				end: seg.end,
				words: seg.words && seg.words.length > 0
					? seg.words.map((w) => ({
						word: w.word,
						start: w.start,
						end: w.end,
						confidence: w.confidence,
					}))
					: seg.text.trim().split(/\s+/).map((word, wordIndex, arr) => {
						const segDuration = seg.end - seg.start;
						const wordDuration = segDuration / arr.length;
						return {
							word,
							start: seg.start + wordIndex * wordDuration,
							end: seg.start + (wordIndex + 1) * wordDuration,
							confidence: 0.9,
						};
					}),
			}));

			useTranscriptStore.getState().setSegments(transcriptSegments);
			useTranscriptStore.getState().setLanguage(result.language ?? "en");

			// ── Auto Speaker Diarization + Emotion Detection ──
			// Run both in parallel: speaker labels and emotion annotations.
			let speakerChangeTimes: number[] = [];
			setProcessingStep("Detecting speakers & emotions...");
			bgTasks.updateTask(taskId, { progress: "Detecting speakers & emotions..." });

			const speakerPromise = aiClient.analyzeSpeakers(file).catch((err) => {
				console.warn("Speaker diarization failed:", err);
				return null;
			});
			const emotionPromise = aiClient.analyzeEmotions(file).catch((err) => {
				console.warn("Emotion detection failed:", err);
				return null;
			});

			const [speakerResult, emotionResult] = await Promise.all([speakerPromise, emotionPromise]);

			if (speakerResult && speakerResult.segments.length > 0) {
				useTranscriptStore.getState().applySpeakerDiarization(speakerResult.segments);

				// Collect speaker change boundaries for auto-cuts
				for (let i = 1; i < speakerResult.segments.length; i++) {
					const prev = speakerResult.segments[i - 1];
					const curr = speakerResult.segments[i];
					if (prev.speaker !== curr.speaker) {
						const boundary = curr.start;
						if (boundary > 0 && boundary < timelineDuration) {
							speakerChangeTimes.push(boundary);
						}
					}
				}

				const numSpeakers = speakerResult.num_speakers;
				if (numSpeakers > 1) {
					toast.success(`Detected ${numSpeakers} speakers`, {
						description: `Method: ${speakerResult.method}. Click speaker names in the transcript to rename them.`,
					});
				}
			}

			if (emotionResult && emotionResult.emotions.length > 0) {
				useTranscriptStore.getState().setEmotions(emotionResult.emotions);
			}

			// Split video at segment boundaries AND speaker change points
			if (validSegments.length > 1) {
				try {
					const allTimes = new Set<number>();
					for (const seg of validSegments) {
						if (seg.start > 0 && seg.start < timelineDuration) {
							allTimes.add(seg.start);
						}
						if (seg.end > 0 && seg.end < timelineDuration) {
							allTimes.add(seg.end);
						}
					}
					// Add speaker change boundaries
					for (const t of speakerChangeTimes) {
						allTimes.add(t);
					}

					let splitCount = 0;
					const reversed = [...allTimes].sort((a, b) => b - a);
					for (const time of reversed) {
						const elementsAtTime = getElementsAtTime({
							tracks: editor.timeline.getTracks(),
							time,
						});
						if (elementsAtTime.length > 0) {
							editor.timeline.splitElements({
								elements: elementsAtTime,
								splitTime: time,
							});
							splitCount++;
						}
					}

					if (splitCount > 0) {
						toast.success(`Video split into ${splitCount + 1} segments`, {
							description: "Delete or reorder segments in the transcript panel to edit the video.",
						});
					}
				} catch (splitError) {
					console.error("Failed to split video:", splitError);
				}
			}

			// Auto-separate audio from video so it appears as its own track
			const tracksAfterSplit = editor.timeline.getTracks();
			for (const track of tracksAfterSplit) {
				if (track.type !== "video") continue;
				for (const el of track.elements) {
					const videoEl = el as TimelineElement & { mediaId?: string; muted?: boolean };
					if (!videoEl.mediaId || videoEl.muted) continue;

					// Mute the video element and create a matching audio element
					editor.timeline.updateElements({
						updates: [{
							trackId: track.id,
							elementId: el.id,
							updates: { muted: true },
						}],
					});

					editor.timeline.insertElement({
						element: {
							type: "audio",
							sourceType: "upload",
							mediaId: videoEl.mediaId,
							name: `${el.name} (audio)`,
							startTime: el.startTime,
							duration: el.duration,
							trimStart: el.trimStart,
							trimEnd: el.trimEnd,
							sourceDuration: el.sourceDuration,
							volume: 1,
						},
						placement: { mode: "auto" },
					});
				}
			}

			setSubtitleTracks([]);

			toast.success(`Transcription complete (${engineLabel})`, {
				description: `${validSegments.length} segments detected`,
			});

			bgTasks.updateTask(taskId, {
				status: "completed",
				progress: `${validSegments.length} segments`,
				completedAt: Date.now(),
			});
		} catch (err) {
			console.error("Transcription failed:", err);
			const message = err instanceof Error ? err.message : "An unexpected error occurred";
			if (message.includes("Cannot connect") || message.includes("connection_refused")) {
				setError("Cannot connect to AI backend. Make sure it is running (docker compose up -d).");
			} else if (message.includes("Sarvam API key")) {
				setError("Sarvam API key is not configured. Add OPENCUTAI_SARVAM_API_KEY to your environment.");
			} else if (message.includes("Smallest AI API key")) {
				setError("Smallest AI API key is not configured. Add it in Settings > API Keys, or set OPENCUTAI_SMALLEST_API_KEY in your environment.");
			} else {
				setError(message);
			}
			bgTasks.updateTask(taskId, {
				status: "error",
				error: message,
				completedAt: Date.now(),
			});
		} finally {
			setIsProcessing(false);
			setProcessingStep("");
		}
	};

	const handleAddSubtitles = () => {
		const currentSegments = useTranscriptStore.getState().segments;
		if (currentSegments.length === 0) return;

		const chunks = buildCaptionChunks({
			segments: currentSegments.map((seg) => ({
				text: seg.text,
				start: seg.start,
				end: seg.end,
				words: seg.words,
			})),
		});

		const trackId = createSubtitleTrack(editor, {
			segments: chunks.map((chunk) => ({
				text: chunk.text,
				start: chunk.startTime,
				end: chunk.startTime + chunk.duration,
				words: chunk.words,
			})),
			languageLabel: "Subtitle",
			yOffset: 0.38,
		});

		addSubtitleTrackState({ trackId, language: "original" });
		toast.success("Subtitles added with word highlighting");
	};


	const handleTranslateAndAdd = () => {
		const targetLang = LANGUAGES.find((language) => language.code === translateLanguage);
		if (!targetLang) return;
		setError(null);
		invokeAction(
			"translate-captions",
			{
				targetLanguage: targetLang.code,
				targetLanguageName: targetLang.name,
			},
			"mouseclick",
		);
	};

	const handleRemoveSubtitles = () => {
		for (const track of subtitleTracks) {
			try {
				editor.timeline.removeTrack({ trackId: track.trackId });
			} catch {
				// Track may already have been removed manually
			}
		}
		setSubtitleTracks([]);
		toast.success("All subtitle tracks removed");
	};

	const handleRemoveSingleTrack = (trackId: string) => {
		try {
			editor.timeline.removeTrack({ trackId });
		} catch {
			// Already removed
		}
		removeSubtitleTrackState(trackId);
		toast.success("Subtitle track removed");
	};

	const handleLanguageChange = ({ value }: { value: string }) => {
		if (value === "auto") {
			setSelectedLanguage("auto");
			return;
		}
		setSelectedLanguage(value as TranscriptionLanguage);
	};

	const handleEngineChange = (value: string) => {
		const engine = value as TranscriptionEngine;
		setSelectedEngine(engine);
		// Reset language to auto when switching engines
		setSelectedLanguage("auto");
	};

	return (
		<PanelView title="Transcript" ref={containerRef}>
			<div className="flex flex-col gap-5">
				<p className="text-xs text-muted-foreground leading-relaxed">
					Transcribe your video to edit it like a document. Delete sections, remove filler words, or reorder segments.
				</p>

				{/* ── Engine Selector ── */}
				<div className="flex flex-col gap-2">
					<Label className="text-xs">Transcription engine</Label>
					<Select value={selectedEngine} onValueChange={handleEngineChange}>
						<SelectTrigger>
							<SelectValue />
						</SelectTrigger>
						<SelectContent>
							<SelectItem value="whisper">
								Whisper (Local)
							</SelectItem>
							<SelectItem value="sarvam">
								Sarvam AI (Indian Languages)
							</SelectItem>
							<SelectItem value="smallest">
								Smallest AI Pulse (39 Languages)
							</SelectItem>
						</SelectContent>
					</Select>
					<p className="text-[10px] text-muted-foreground">
						{selectedEngine === "sarvam"
							? "Cloud-based, optimized for 22 Indian regional languages"
							: selectedEngine === "smallest"
								? "Cloud-based, 39 languages with speaker diarization & emotion detection"
								: "On-device, best for global languages (English, Spanish, French, etc.)"}
					</p>
				</div>

				{/* ── Language Selector ── */}
				<div className="flex flex-col gap-2">
					<Label className="text-xs">Language</Label>
					<Select
						value={selectedLanguage}
						onValueChange={(value) => handleLanguageChange({ value })}
					>
						<SelectTrigger>
							<SelectValue placeholder="Select a language" />
						</SelectTrigger>
						<SelectContent>
							<SelectItem value="auto">Auto detect</SelectItem>
							{selectedEngine === "sarvam" ? (
								<>
									<SelectGroup>
										<SelectLabel className="text-[10px] text-muted-foreground px-2">
											Indian Regional Languages
										</SelectLabel>
										{SARVAM_STT_LANGUAGES.filter(l => l.code !== "en").map((language) => (
											<SelectItem key={language.code} value={language.code}>
												{language.name}
											</SelectItem>
										))}
									</SelectGroup>
									<SelectGroup>
										<SelectLabel className="text-[10px] text-muted-foreground px-2">
											English
										</SelectLabel>
										<SelectItem value="en">
											English (Indian)
										</SelectItem>
									</SelectGroup>
								</>
							) : (
								availableLanguages.map((language) => (
									<SelectItem key={language.code} value={language.code}>
										{language.name}
									</SelectItem>
								))
							)}
						</SelectContent>
					</Select>
				</div>

				{error && (
					<div className="bg-destructive/10 border-destructive/20 rounded-md border p-3">
						<p className="text-destructive text-sm">{error}</p>
					</div>
				)}

				{segments.length > 0 && activeSubtitleTracks.length === 0 && (
					<p className="text-[11px] text-muted-foreground leading-relaxed rounded-md bg-muted/50 px-3 py-2">
						Transcript is ready. Add subtitles below, or re-transcribe if the video changed.
					</p>
				)}

				<Button
					className="w-full"
					variant={segments.length > 0 ? "outline" : "default"}
					onClick={handleGenerateTranscript}
					disabled={isProcessing}
				>
					{isProcessing && <Spinner className="mr-1" />}
					{isProcessing
						? processingStep
						: segments.length > 0
							? "Re-transcribe"
							: "Generate transcript"}
				</Button>

				{segments.length > 0 && (
					<>
						{/* ── Subtitle Tracks ── */}
						<div className="border-t pt-4 flex flex-col gap-3">
							<div className="flex items-center justify-between">
								<Label className="text-xs">Subtitle tracks</Label>
								{activeSubtitleTracks.length > 0 && (
									<span className="text-[10px] text-muted-foreground tabular-nums">
										{activeSubtitleTracks.length} active
									</span>
								)}
							</div>

							{activeSubtitleTracks.length > 0 ? (
								<div className="flex flex-col gap-1.5">
									{activeSubtitleTracks.map((track) => {
										const langName =
											track.language === "original"
												? "Original"
												: LANGUAGES.find((l) => l.code === track.language)
														?.name ?? track.language;
										return (
											<div
												key={track.trackId}
												className="flex items-center justify-between rounded-md border px-3 py-2"
											>
												<div className="flex items-center gap-2">
													<span className="bg-primary size-1.5 rounded-full shrink-0" />
													<span className="text-sm font-medium">
														{langName}
													</span>
												</div>
												<Button
													variant="ghost"
													size="sm"
													className="h-6 px-2 text-xs text-muted-foreground hover:text-destructive"
													onClick={() =>
														handleRemoveSingleTrack(track.trackId)
													}
												>
													Remove
												</Button>
											</div>
										);
									})}
									<Button
										variant="outline"
										size="sm"
										className="w-full text-destructive hover:text-destructive"
										onClick={handleRemoveSubtitles}
									>
										Remove all
									</Button>
								</div>
							) : (
								<Button
									variant="outline"
									className="w-full"
									onClick={handleAddSubtitles}
								>
									Add subtitles
								</Button>
							)}
						</div>

						{/* ── Add Language ── */}
						<div className="border-t pt-4 flex flex-col gap-3">
							<Label className="text-xs">Add language</Label>
							<p className="text-[11px] text-muted-foreground leading-relaxed">
								{shouldUseSarvamTranslation(
									useTranscriptStore.getState().language,
									translateLanguage,
								)
									? "Translate using Sarvam AI and add as a new subtitle track."
									: "Translate using the local LLM and add as a new subtitle track."}
							</p>
							<div className="flex gap-2">
								<Select
									value={translateLanguage}
									onValueChange={setTranslateLanguage}
								>
									<SelectTrigger className="flex-1">
										<SelectValue />
									</SelectTrigger>
									<SelectContent>
										<SelectGroup>
											<SelectLabel className="text-[10px] text-muted-foreground px-2">
												Global Languages
											</SelectLabel>
											{LANGUAGES.filter(
												(lang) =>
													!SARVAM_SUPPORTED_CODES.has(lang.code) &&
													!activeSubtitleTracks.some(
														(t) => t.language === lang.code,
													),
											).map((lang) => (
												<SelectItem key={lang.code} value={lang.code}>
													{lang.name}
												</SelectItem>
											))}
										</SelectGroup>
										<SelectGroup>
											<SelectLabel className="text-[10px] text-muted-foreground px-2">
												Indian Languages (via Sarvam AI)
											</SelectLabel>
											{LANGUAGES.filter(
												(lang) =>
													SARVAM_SUPPORTED_CODES.has(lang.code) &&
													lang.code !== "en" &&
													!activeSubtitleTracks.some(
														(t) => t.language === lang.code,
													),
											).map((lang) => (
												<SelectItem key={lang.code} value={lang.code}>
													{lang.name}
												</SelectItem>
											))}
										</SelectGroup>
									</SelectContent>
								</Select>
								<Button
									onClick={handleTranslateAndAdd}
									disabled={translationControl.disabled}
									className="shrink-0"
								>
									{isTranslating && <Spinner className="mr-1" />}
									{isTranslating ? "Translating…" : "Translate & add"}
								</Button>
							</div>
							{isTranslating && translatingStep && (
								<p className="text-[11px] text-muted-foreground animate-pulse">
									{translatingStep}
								</p>
							)}
						</div>
					</>
				)}
			</div>
		</PanelView>
	);
}
