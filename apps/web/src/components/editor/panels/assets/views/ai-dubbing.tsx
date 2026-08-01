"use client";

import { useCallback, useState } from "react";
import { useEditor } from "@/hooks/use-editor";
import { useTranscriptStore } from "@/stores/transcript-store";
import { useAIDubbing, type DubbingEngine } from "@/hooks/use-ai-dubbing";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/utils/ui";
import { toast } from "sonner";
import { VoiceLibraryPicker } from "@/components/editor/ai/voice-library-picker";
import type { ClonedVoice } from "@/stores/voice-library-store";
import { OMNIVOICE_LANGUAGES } from "@/constants/omnivoice-constants";
import { aiClient } from "@/lib/ai-client";
import { ensureTargetTranslation } from "@/lib/transcription/dubbing-runner";
import {
	Dialog,
	DialogBody,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";

interface DubbingReviewSentence {
	id: number;
	start: number;
	source: string;
	translation: string;
}

function formatTimestamp(seconds: number): string {
	const minutes = Math.floor(seconds / 60);
	const remainder = Math.floor(seconds % 60);
	return `${minutes}:${remainder.toString().padStart(2, "0")}`;
}

const ENGINES: Array<{
	value: DubbingEngine;
	label: string;
	description: string;
}> = [
	{
		value: "local",
		label: "Local OmniVoice",
		description: "Auto voice or voice design, any language",
	},
];

export function AIDubbingPanel() {
	const segments = useTranscriptStore((s) => s.segments);
	const language = useTranscriptStore((s) => s.language);
	const editor = useEditor();
	const { runDubbing, isDubbing, progress } = useAIDubbing();

	const [targetLanguage, setTargetLanguage] = useState("hi");
	const [engine, setEngine] = useState<DubbingEngine>("local");
	const [voiceDesign, setVoiceDesign] = useState("");
	const [clonedVoice, setClonedVoice] = useState<ClonedVoice | null>(null);
	const [reviewOpen, setReviewOpen] = useState(false);
	const [reviewLoading, setReviewLoading] = useState(false);
	const [reviewSentences, setReviewSentences] = useState<DubbingReviewSentence[]>([]);

	const handleDub = useCallback(async () => {
		if (segments.length === 0) {
			toast.error("No transcript available. Transcribe first.");
			return;
		}
		if (language === targetLanguage) {
			toast.error("Target language is same as source.");
			return;
		}

		setReviewLoading(true);
		try {
			const transcript = useTranscriptStore.getState();
			let translation = transcript.translations.find(
				(item) => item.languageCode.toLowerCase() === targetLanguage.toLowerCase(),
			);
			if (!translation) {
				translation = await ensureTargetTranslation({
					transcript,
					targetLanguage,
					translate: (request) => aiClient.translateTranscript(request),
				});
				useTranscriptStore.getState().addTranslation(translation);
			}

			const sourceById = new Map(
				transcript.segments.map((segment) => [segment.id, segment.text]),
			);
			setReviewSentences(
				translation.segments.map((segment) => ({
					id: segment.id,
					start: segment.start,
					source: sourceById.get(segment.id) ?? "",
					translation: segment.text,
				})),
			);
			setReviewOpen(true);
		} catch (error) {
			toast.error("Unable to prepare dubbing", {
				description: error instanceof Error ? error.message : "Translation failed.",
			});
		} finally {
			setReviewLoading(false);
		}
	}, [segments, language, targetLanguage]);

	const handleConfirmReview = useCallback(() => {
		const sentenceOverrides = Object.fromEntries(
			reviewSentences.map((sentence) => [sentence.id, sentence.translation.trim()]),
		);
		setReviewOpen(false);
		runDubbing({
			targetLanguage,
			engine,
			voiceDesign,
			voiceClonePath: clonedVoice?.path,
			voiceCloneReferenceText: clonedVoice?.referenceText,
			sentenceOverrides,
		});
	}, [reviewSentences, targetLanguage, engine, voiceDesign, clonedVoice, runDubbing]);

	return (
		<div className="flex flex-col gap-4 p-3">
			<div className="flex items-center justify-between">
				<div className="flex items-center gap-1.5">
					<span className="text-xs font-medium">AI Dubbing</span>
					{segments.length > 0 && (
						<Badge variant="secondary" className="text-[8px] px-1 py-0">
							{segments.length} segments
						</Badge>
					)}
				</div>
				<Badge variant="outline" className="text-[8px] px-1 py-0">
					Source: {language}
				</Badge>
			</div>

			<p className="text-[10px] text-muted-foreground leading-relaxed">
				Uses the translated caption rows, fits speech to their timing, reuses the
				Demucs background stem, and mutes the original source audio.
			</p>

			<div className="flex flex-col gap-1.5">
				<Label className="text-[10px]">Target language</Label>
				<Select value={targetLanguage} onValueChange={setTargetLanguage}>
					<SelectTrigger className="w-full">
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
			</div>

			<div className="flex flex-col gap-1.5">
				<Label className="text-[10px]">TTS Engine</Label>
				<div className="flex flex-col gap-1">
					{ENGINES.map((e) => {
						const isActive = engine === e.value;
						return (
							<button
								key={e.value}
								type="button"
								onClick={() => setEngine(e.value)}
								className={cn(
									"flex items-center justify-between rounded-md border px-2.5 py-1.5 text-left transition-colors",
									isActive
										? "border-primary/40 bg-primary/5"
										: "border-border hover:bg-accent cursor-pointer",
								)}
							>
								<div className="flex items-center gap-1.5">
									{isActive ? (
										<svg
											className="size-3 text-primary shrink-0"
											viewBox="0 0 16 16"
											fill="none"
										>
											<path
												d="M3 8.5L6.5 12L13 4"
												stroke="currentColor"
												strokeWidth="2"
												strokeLinecap="round"
												strokeLinejoin="round"
											/>
										</svg>
									) : (
										<span className="size-3 shrink-0" />
									)}
									<span className="text-[10px] font-medium">{e.label}</span>
								</div>
								<span className="text-[9px] text-muted-foreground">
									{e.description}
								</span>
							</button>
						);
					})}
				</div>
			</div>

			<div className="flex flex-col gap-1.5">
				<Label htmlFor="ai-dubbing-voice-design" className="text-[10px]">
					Voice design (optional)
				</Label>
				<Input
					id="ai-dubbing-voice-design"
					size="sm"
					value={voiceDesign}
					onChange={(event) => setVoiceDesign(event.target.value)}
					placeholder="female, young adult, high pitch, british accent"
					className="text-[10px]"
					disabled={!!clonedVoice}
				/>
				<p className="text-[9px] text-muted-foreground leading-relaxed">
					{clonedVoice
						? "Voice design is overridden by the cloned voice below."
						: "Leave blank for Auto voice. You can describe gender, age, pitch, whisper style, accents, or Chinese dialects such as 四川话."}
				</p>
			</div>

			<VoiceLibraryPicker selectedVoice={clonedVoice} onSelect={setClonedVoice} />

			{progress && (
				<div className="flex flex-col gap-1 rounded-md border border-primary/20 bg-primary/5 p-2">
					<div className="flex items-center justify-between">
						<span className="text-[9px] font-medium">
							{progress.phase === "queued"
								? "Queued..."
								: progress.phase === "preparing"
									? "Preparing..."
								: progress.phase === "generating"
									? "Generating speech..."
									: progress.phase === "fitting"
										? "Fitting timing..."
									: progress.phase === "placing"
										? "Placing on timeline..."
										: "Done"}
						</span>
						<span className="text-[9px] text-muted-foreground">
							{progress.currentSegment}/{progress.totalSegments}
						</span>
					</div>
					<div className="w-full bg-muted rounded-full h-1">
						<div
							className="bg-primary h-1 rounded-full transition-all"
							style={{
								width: `${(progress.currentSegment / progress.totalSegments) * 100}%`,
							}}
						/>
					</div>
					<span className="text-[8px] text-muted-foreground truncate">
						{progress.currentText}
					</span>
				</div>
			)}

			<button
				type="button"
				disabled={isDubbing || reviewLoading || segments.length === 0}
				onClick={handleDub}
				className={cn(
					"w-full rounded-md py-2 text-xs font-medium transition-colors",
					isDubbing
						? "bg-muted text-muted-foreground cursor-not-allowed"
						: "bg-primary text-primary-foreground hover:bg-primary/90",
				)}
			>
				{isDubbing ? "Dubbing..." : reviewLoading ? "Preparing review..." : "Start Dubbing"}
			</button>

			<DubbingReviewDialog
				open={reviewOpen}
				onOpenChange={setReviewOpen}
				sentences={reviewSentences}
				onSentencesChange={setReviewSentences}
				onConfirm={handleConfirmReview}
			/>
		</div>
	);
}

function DubbingReviewDialog({
	open,
	onOpenChange,
	sentences,
	onSentencesChange,
	onConfirm,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	sentences: DubbingReviewSentence[];
	onSentencesChange: (sentences: DubbingReviewSentence[]) => void;
	onConfirm: () => void;
}) {
	const hasEmptySentence =
		sentences.length === 0 || sentences.some((sentence) => !sentence.translation.trim());

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="flex max-h-[85vh] max-w-2xl flex-col p-0">
				<DialogHeader>
					<DialogTitle>Review dubbing sentences</DialogTitle>
					<DialogDescription>
						Edit the complete sentences used for speech generation. Caption line
						splits and timing stay unchanged.
					</DialogDescription>
				</DialogHeader>
				<DialogBody className="min-h-0 overflow-y-auto">
					{sentences.map((sentence, index) => (
						<div key={sentence.id} className="flex flex-col gap-2 rounded-md border p-3">
							<div className="flex items-center justify-between gap-2">
								<span className="text-xs font-medium">Sentence {index + 1}</span>
								<span className="text-[10px] font-mono text-muted-foreground">
									{formatTimestamp(sentence.start)}
								</span>
							</div>
							<p className="text-[10px] text-muted-foreground">{sentence.source}</p>
							<Textarea
								value={sentence.translation}
								onChange={(event) =>
									onSentencesChange(
										sentences.map((item) =>
											item.id === sentence.id
												? { ...item, translation: event.target.value }
												: item,
										),
								)
								}
								rows={2}
								aria-label={`Dubbing sentence ${index + 1}`}
								className="text-sm"
							/>
						</div>
					))}
				</DialogBody>
				<DialogFooter>
					<Button variant="outline" onClick={() => onOpenChange(false)}>
						Cancel
					</Button>
					<Button disabled={hasEmptySentence} onClick={onConfirm}>
						Confirm dubbing
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
