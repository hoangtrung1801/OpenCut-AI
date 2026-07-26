"use client";

import { useRef, useState } from "react";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { aiClient } from "@/lib/ai-client";
import { useVoiceLibraryStore, type ClonedVoice } from "@/stores/voice-library-store";
import { generateUUID } from "@/utils/id";
import { toast } from "sonner";

const NONE_VALUE = "__none__";

export interface VoiceLibraryPickerProps {
	selectedVoice: ClonedVoice | null;
	onSelect: (voice: ClonedVoice | null) => void;
}

export function VoiceLibraryPicker({
	selectedVoice,
	onSelect,
}: VoiceLibraryPickerProps) {
	const voices = useVoiceLibraryStore((s) => s.voices);
	const addVoice = useVoiceLibraryStore((s) => s.addVoice);
	const removeVoice = useVoiceLibraryStore((s) => s.removeVoice);

	const [isCloning, setIsCloning] = useState(voices.length === 0);
	const [isUploading, setIsUploading] = useState(false);
	const [draftName, setDraftName] = useState("");
	const fileInputRef = useRef<HTMLInputElement>(null);

	const handleSelectChange = (value: string) => {
		if (value === NONE_VALUE) {
			onSelect(null);
			return;
		}
		const voice = voices.find((v) => v.id === value);
		onSelect(voice ?? null);
	};

	const handleRemove = (id: string) => {
		removeVoice(id);
		if (selectedVoice?.id === id) onSelect(null);
	};

	const handleFilePicked = async (file: File) => {
		const name = draftName.trim() || file.name.replace(/\.[^.]+$/, "");
		setIsUploading(true);
		try {
			const result = await aiClient.cloneVoice(file, name);
			const voice: ClonedVoice = {
				id: generateUUID(),
				name: result.name,
				path: result.path,
				createdAt: Date.now(),
			};
			addVoice(voice);
			onSelect(voice);
			setDraftName("");
			setIsCloning(false);
			toast.success(`Voice "${voice.name}" saved to your library`);
		} catch (err) {
			toast.error("Voice cloning failed", {
				description: err instanceof Error ? err.message : "Unknown error",
			});
		} finally {
			setIsUploading(false);
		}
	};

	return (
		<div className="flex flex-col gap-1.5">
			<Label className="text-[10px]">Cloned voice (optional)</Label>

			{voices.length > 0 && (
				<div className="flex flex-col gap-1">
					<Select
						value={selectedVoice?.id ?? NONE_VALUE}
						onValueChange={handleSelectChange}
					>
						<SelectTrigger className="w-full">
							<SelectValue />
						</SelectTrigger>
						<SelectContent>
							<SelectItem value={NONE_VALUE}>None</SelectItem>
							{voices.map((voice) => (
								<SelectItem key={voice.id} value={voice.id}>
									{voice.name}
								</SelectItem>
							))}
						</SelectContent>
					</Select>
					<div className="flex flex-wrap gap-1">
						{voices.map((voice) => (
							<span
								key={voice.id}
								className="flex items-center gap-1 rounded-full border border-border px-1.5 py-0.5 text-[9px] text-muted-foreground"
							>
								{voice.name}
								<button
									type="button"
									className="text-destructive hover:text-destructive/80"
									onClick={() => handleRemove(voice.id)}
									aria-label={`Remove ${voice.name}`}
								>
									×
								</button>
							</span>
						))}
					</div>
				</div>
			)}

			{isCloning ? (
				<div className="flex flex-col gap-1.5 rounded-md border border-border p-2">
					<Input
						size="sm"
						value={draftName}
						onChange={(e) => setDraftName(e.target.value)}
						placeholder="Voice name (e.g. Alice)"
						className="text-[10px]"
					/>
					<div className="flex gap-1.5">
						<Button
							variant="outline"
							size="sm"
							className="flex-1 text-[10px] h-7"
							disabled={isUploading}
							onClick={() => fileInputRef.current?.click()}
						>
							{isUploading ? (
								<>
									<Spinner className="size-3 mr-1" />
									Uploading...
								</>
							) : (
								"Upload voice sample"
							)}
						</Button>
						{voices.length > 0 && (
							<Button
								variant="ghost"
								size="sm"
								className="text-[10px] h-7"
								disabled={isUploading}
								onClick={() => setIsCloning(false)}
							>
								Cancel
							</Button>
						)}
					</div>
					<p className="text-[9px] text-muted-foreground">
						Upload 10-30s audio to clone a specific voice.
					</p>
					<input
						ref={fileInputRef}
						type="file"
						accept=".wav,.mp3,.flac,.ogg,.m4a"
						className="hidden"
						onChange={(e) => {
							const file = e.target.files?.[0];
							if (file) handleFilePicked(file);
							e.target.value = "";
						}}
					/>
				</div>
			) : (
				<Button
					variant="outline"
					size="sm"
					className="text-[10px] h-7 self-start"
					onClick={() => setIsCloning(true)}
				>
					+ Clone new voice
				</Button>
			)}
		</div>
	);
}
