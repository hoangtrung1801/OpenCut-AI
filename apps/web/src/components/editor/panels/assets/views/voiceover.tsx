"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { PanelView } from "./base-view";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { useEditor } from "@/hooks/use-editor";
import { useTranscriptStore } from "@/stores/transcript-store";
import { aiClient } from "@/lib/ai-client";
import { useBackgroundTasksStore } from "@/stores/background-tasks-store";
import { cn } from "@/utils/ui";
import { toast } from "sonner";
import { insertGeneratedAudioElement } from "@/lib/media/generated-audio";
import { VoiceLibraryPicker } from "@/components/editor/ai/voice-library-picker";
import type { ClonedVoice } from "@/stores/voice-library-store";
import { OMNIVOICE_LANGUAGES } from "@/constants/omnivoice-constants";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function VoiceoverView() {
	const editor = useEditor();
	const segments = useTranscriptStore((s) => s.segments);
	const hasTranscript = segments.length > 0;

	// Shared state
	const [language, setLanguage] = useState("en");
	const [customText, setCustomText] = useState("");
	const [isGenerating, setIsGenerating] = useState(false);
	const [generationProgress, setGenerationProgress] = useState("");
	const [generatedAudioUrl, setGeneratedAudioUrl] = useState<string | null>(null);
	const [generatedBlob, setGeneratedBlob] = useState<Blob | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [useTranscript, setUseTranscript] = useState(true);
	const audioRef = useRef<HTMLAudioElement>(null);

	const [voiceGender, setVoiceGender] = useState<"male" | "female">("male");
	const [clonedVoice, setClonedVoice] = useState<ClonedVoice | null>(null);
	const [speed, setSpeed] = useState(1.0);

	// Text to generate from
	const textToGenerate = useMemo(() => {
		if (useTranscript && hasTranscript) {
			return segments.map((s) => s.text).join(" ").trim();
		}
		return customText.trim();
	}, [useTranscript, hasTranscript, segments, customText]);

	// Check if translation is needed
	const transcriptLanguage = useTranscriptStore((s) => s.language) || "en";
	const needsTranslation = useTranscript && hasTranscript && language !== transcriptLanguage && language !== "en";

	const addTask = useBackgroundTasksStore((s) => s.addTask);
	const updateTask = useBackgroundTasksStore((s) => s.updateTask);

	// Translate text for TTS
	const translateForTTS = useCallback(async (text: string, taskId?: string): Promise<string> => {
		if (!needsTranslation) return text;
		const langName = OMNIVOICE_LANGUAGES.find((l) => l.code === language)?.name ?? language;
		const progress = `Translating to ${langName}...`;
		setGenerationProgress(progress);
		if (taskId) updateTask(taskId, { progress });
		return await aiClient.translateText(text, langName);
	}, [needsTranslation, language, updateTask]);

	// Generate speech with OmniVoice
	const generateSpeech = useCallback(async (text: string): Promise<Blob> => {
		return aiClient.generateSpeechBlob({
			text,
			language,
			speakerWav: clonedVoice?.path,
			referenceText: clonedVoice?.referenceText,
			speaker: clonedVoice ? undefined : voiceGender,
			speed,
		});
	}, [language, clonedVoice, voiceGender, speed]);

	// Generate full voiceover
	const handleGenerate = useCallback(async () => {
		if (!textToGenerate) {
			toast.error("No text to generate speech from");
			return;
		}

		const taskId = `vo-full-${Date.now()}`;
		addTask({ id: taskId, type: "voiceover", label: "Generating voiceover", progress: "Preparing..." });

		setIsGenerating(true);
		setError(null);
		setGeneratedAudioUrl(null);
		setGeneratedBlob(null);
		setGenerationProgress("Preparing text...");

		try {
			const ttsText = await translateForTTS(textToGenerate, taskId);
			setGenerationProgress("Generating speech...");
			updateTask(taskId, { progress: "Generating speech..." });

			const blob = await generateSpeech(ttsText);

			const url = URL.createObjectURL(blob);
			setGeneratedAudioUrl(url);
			setGeneratedBlob(blob);
			setGenerationProgress("");
			updateTask(taskId, { status: "completed", completedAt: Date.now() });
		} catch (err) {
			const msg = err instanceof Error ? err.message : "Generation failed";
			setError(msg);
			setGenerationProgress("");
			updateTask(taskId, { status: "error", error: msg, completedAt: Date.now() });
		} finally {
			setIsGenerating(false);
		}
	}, [textToGenerate, translateForTTS, generateSpeech, addTask, updateTask]);

	// Generate per-segment and auto-add to timeline
	const handleGeneratePerSegment = useCallback(async () => {
		if (!hasTranscript || segments.length === 0) {
			toast.error("No transcript segments to generate from");
			return;
		}

		const taskId = `vo-seg-${Date.now()}`;
		const langName = OMNIVOICE_LANGUAGES.find((l) => l.code === language)?.name ?? language;
		const activeProject = editor.project.getActive();
		if (!activeProject) return;

		addTask({ id: taskId, type: "voiceover", label: `Voiceover (${segments.length} segments)`, progress: "Starting..." });

		setIsGenerating(true);
		setError(null);

		const trackId = editor.timeline.addTrack({ type: "audio", index: 0 });

		try {
			for (let i = 0; i < segments.length; i++) {
				const seg = segments[i];
				const originalText = seg.text.trim();
				if (!originalText) continue;

				let ttsText = originalText;
				if (needsTranslation) {
					const progress = `Translating ${i + 1}/${segments.length} to ${langName}...`;
					setGenerationProgress(progress);
					updateTask(taskId, { progress });
					ttsText = await translateForTTS(originalText, taskId);
				}

				const progress = `Generating ${i + 1}/${segments.length}...`;
				setGenerationProgress(progress);
				updateTask(taskId, { progress });

				const blob = await generateSpeech(ttsText);

				const file = new File([blob], `voiceover_seg_${i}.wav`, { type: "audio/wav" });
				const audioUrl = URL.createObjectURL(file);
				const duration = await getAudioDuration(audioUrl);
				URL.revokeObjectURL(audioUrl);

				await insertGeneratedAudioElement({
					editor,
					projectId: activeProject.metadata.id,
					trackId,
					file,
					name: `Voice [${language}]: ${originalText.slice(0, 25)}...`,
					startTime: seg.start,
					duration: duration || (seg.end - seg.start),
				});
			}

			setGenerationProgress("");
			updateTask(taskId, { status: "completed", completedAt: Date.now() });
		} catch (err) {
			const msg = err instanceof Error ? err.message : "Generation failed";
			setError(msg);
			setGenerationProgress("");
			updateTask(taskId, { status: "error", error: msg, completedAt: Date.now() });
		} finally {
			setIsGenerating(false);
		}
	}, [segments, hasTranscript, language, needsTranslation, editor, translateForTTS, generateSpeech, addTask, updateTask]);

	// Add full voiceover to timeline
	const handleAddToTimeline = useCallback(async () => {
		if (!generatedBlob) return;
		const activeProject = editor.project.getActive();
		if (!activeProject) return;

		const file = new File([generatedBlob], `voiceover_${Date.now()}.wav`, { type: "audio/wav" });
		const audioUrl = URL.createObjectURL(file);
		const duration = await getAudioDuration(audioUrl);
		URL.revokeObjectURL(audioUrl);
		const currentTime = editor.playback.getCurrentTime();

		const trackId = editor.timeline.addTrack({ type: "audio", index: 0 });

		try {
			await insertGeneratedAudioElement({
				editor,
				projectId: activeProject.metadata.id,
				trackId,
				file,
				name: "Voiceover",
				startTime: currentTime,
				duration: duration || 5,
			});

			toast.success("Voiceover added to timeline");
		} catch (error) {
			toast.error("Failed to add voiceover", {
				description: error instanceof Error ? error.message : "Unknown error",
			});
		}
	}, [editor, generatedBlob]);

	return (
		<PanelView title="Voiceover">
			<div className="flex flex-col gap-4">

				{/* ── Source text ── */}
				{hasTranscript && (
					<div className="flex flex-col gap-2">
						<div className="flex items-center gap-2">
							<Label className="text-xs flex-1">Source</Label>
							<button
								type="button"
								className={cn(
									"text-[10px] px-2 py-0.5 rounded-full border transition-colors",
									useTranscript ? "bg-primary text-primary-foreground border-primary" : "text-muted-foreground hover:bg-accent",
								)}
								onClick={() => setUseTranscript(true)}
							>
								Transcript
							</button>
							<button
								type="button"
								className={cn(
									"text-[10px] px-2 py-0.5 rounded-full border transition-colors",
									!useTranscript ? "bg-primary text-primary-foreground border-primary" : "text-muted-foreground hover:bg-accent",
								)}
								onClick={() => setUseTranscript(false)}
							>
								Custom text
							</button>
						</div>

						{useTranscript && (
							<div className="rounded-md bg-muted/50 px-2.5 py-2 max-h-24 overflow-y-auto">
								<p className="text-[10px] text-muted-foreground leading-relaxed">
									{segments.map((s) => s.text).join(" ").slice(0, 500)}
									{segments.map((s) => s.text).join(" ").length > 500 && "..."}
								</p>
							</div>
						)}
					</div>
				)}

				{(!hasTranscript || !useTranscript) && (
					<div className="flex flex-col gap-2">
						<Label className="text-xs">Text</Label>
						<textarea
							value={customText}
							onChange={(e) => setCustomText(e.target.value)}
							placeholder="Type or paste text to convert to speech..."
							rows={4}
							maxLength={5000}
							className={cn(
								"w-full resize-none rounded-md border bg-transparent px-2.5 py-2 text-xs outline-none",
								"focus:ring-1 focus:ring-ring placeholder:text-muted-foreground/40",
							)}
						/>
					</div>
				)}

				{/* ── Voice engine ── */}
				<div className="flex flex-col gap-2">
					<Label className="text-xs">Voice engine</Label>
					<div className="rounded-md border border-border px-2.5 py-1.5 text-[10px] text-muted-foreground">
						On-device OmniVoice — voice design or voice cloning, any language
					</div>
				</div>

				{/* Language */}
				<div className="flex flex-col gap-2">
					<Label className="text-xs">Language</Label>
					<Select value={language} onValueChange={setLanguage}>
						<SelectTrigger>
							<SelectValue />
						</SelectTrigger>
						<SelectContent>
							{OMNIVOICE_LANGUAGES.map((lang) => (
								<SelectItem key={lang.code} value={lang.code}>
									{lang.name}
								</SelectItem>
							))}
						</SelectContent>
					</Select>
					{needsTranslation && (
						<div className="rounded-md bg-blue-500/10 border border-blue-500/20 px-2.5 py-1.5">
							<p className="text-[10px] text-blue-400 leading-relaxed">
								Transcript will be auto-translated to {OMNIVOICE_LANGUAGES.find((l) => l.code === language)?.name || language} before generating speech.
							</p>
						</div>
					)}
				</div>

				{/* Voice type */}
				<div className="flex flex-col gap-2">
					<Label className="text-xs">Voice type</Label>
					<div className="flex gap-1.5">
						<button
							type="button"
							className={cn(
								"flex-1 rounded-md border px-3 py-2 text-xs font-medium transition-colors",
								voiceGender === "male"
									? "bg-primary text-primary-foreground border-primary"
									: "text-muted-foreground hover:bg-accent border-border",
							)}
							onClick={() => setVoiceGender("male")}
						>
							Male
						</button>
						<button
							type="button"
							className={cn(
								"flex-1 rounded-md border px-3 py-2 text-xs font-medium transition-colors",
								voiceGender === "female"
									? "bg-primary text-primary-foreground border-primary"
									: "text-muted-foreground hover:bg-accent border-border",
							)}
							onClick={() => setVoiceGender("female")}
						>
							Female
						</button>
					</div>
					{clonedVoice && (
						<p className="text-[9px] text-muted-foreground">
							Voice type is overridden by the cloned voice below.
						</p>
					)}
				</div>

				{/* Voice cloning */}
				<VoiceLibraryPicker selectedVoice={clonedVoice} onSelect={setClonedVoice} />

				{/* Speed */}
				<div className="flex flex-col gap-2">
					<Label className="text-xs">Speed ({speed.toFixed(1)}x)</Label>
					<input
						type="range"
						min={0.5}
						max={2.0}
						step={0.1}
						value={speed}
						onChange={(e) => setSpeed(parseFloat(e.target.value))}
						className="w-full accent-primary"
					/>
					<div className="flex justify-between text-[9px] text-muted-foreground">
						<span>0.5x</span>
						<span>1.0x</span>
						<span>2.0x</span>
					</div>
				</div>

				{/* ── Errors & progress ── */}
				{error && (
					<div className="bg-destructive/10 border-destructive/20 rounded-md border p-2.5">
						<p className="text-destructive text-[11px]">{error}</p>
					</div>
				)}

				{generationProgress && (
					<div className="flex items-center gap-2 text-[11px] text-muted-foreground">
						<Spinner className="size-3" />
						{generationProgress}
					</div>
				)}

				{/* ── Generate buttons ── */}
				<div className="flex flex-col gap-1.5">
					{hasTranscript && useTranscript && (
						<Button
							className="w-full"
							onClick={handleGeneratePerSegment}
							disabled={isGenerating}
						>
							{isGenerating && <Spinner className="mr-1" />}
							Generate per segment
						</Button>
					)}

					<Button
						variant={hasTranscript && useTranscript ? "outline" : "default"}
						className="w-full"
						onClick={handleGenerate}
						disabled={isGenerating || !textToGenerate}
					>
						{isGenerating && !generationProgress.includes("segment") && <Spinner className="mr-1" />}
						Generate full voiceover
					</Button>
				</div>

				{/* ── Audio preview ── */}
				{generatedAudioUrl && (
					<div className="flex flex-col gap-2 rounded-md border p-2.5 bg-muted/30">
						<p className="text-[10px] text-muted-foreground font-medium">Preview</p>
						<audio
							ref={audioRef}
							src={generatedAudioUrl}
							controls
							className="w-full h-8"
						/>
						<Button
							variant="outline"
							size="sm"
							className="w-full text-[11px]"
							onClick={handleAddToTimeline}
						>
							Add to timeline as voice track
						</Button>
					</div>
				)}
			</div>
		</PanelView>
	);
}

function getAudioDuration(url: string): Promise<number> {
	return new Promise((resolve) => {
		const audio = new Audio(url);
		audio.addEventListener("loadedmetadata", () => {
			resolve(audio.duration);
		});
		audio.addEventListener("error", () => {
			resolve(5);
		});
	});
}
