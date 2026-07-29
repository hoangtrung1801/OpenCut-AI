"use client";

import { useCallback, useEffect, useState } from "react";
import { cn } from "@/utils/ui";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
	DialogDescription,
	DialogBody,
	DialogFooter,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";

import { HugeiconsIcon } from "@hugeicons/react";
import {
	SparklesIcon,
	Tick01Icon,
	ArrowRight01Icon,
	Download04Icon,
} from "@hugeicons/core-free-icons";
import { toast } from "sonner";
import {
	useServiceHealth,
	SERVICE_URLS,
	SERVICE_DOCKER_COMMANDS,
	type ServiceHealth,
	type ServiceName,
} from "@/hooks/use-service-health";
import { TTS_MODELS, loadedWhisperModel } from "@/lib/ai/service-models";

// ----- Types -----

interface AISetupGuideProps {
	isOpen: boolean;
	onOpenChange: (open: boolean) => void;
}

type ServiceState = "running" | "stopped" | "loaded" | "available" | "not_installed" | "loading" | "error";

// ----- Helpers -----

function statusBadge(status: ServiceState): {
	variant: "default" | "secondary" | "destructive" | "outline";
	label: string;
	dotColor: string;
} {
	switch (status) {
		case "running":
		case "loaded":
			return { variant: "default", label: status === "loaded" ? "Loaded" : "Running", dotColor: "bg-green-500" };
		case "available":
			return { variant: "secondary", label: "Not loaded", dotColor: "bg-yellow-500" };
		case "not_installed":
			return { variant: "destructive", label: "Not installed", dotColor: "bg-red-500" };
		case "loading":
			return { variant: "outline", label: "Loading...", dotColor: "bg-yellow-500" };
		case "stopped":
			return { variant: "destructive", label: "Stopped", dotColor: "bg-red-500" };
		case "error":
			return { variant: "destructive", label: "Error", dotColor: "bg-red-500" };
	}
}

const SUGGESTED_WHISPER_MODELS = [
	{ name: "tiny", description: "Fastest — minimal accuracy", size: "~75 MB", device: "cpu" as const },
	{ name: "base", description: "Good balance of speed and accuracy", size: "~140 MB", device: "cpu" as const },
	{ name: "small", description: "Better accuracy, moderate speed", size: "~460 MB", device: "cpu" as const },
	{ name: "medium", description: "High accuracy, slower", size: "~1.5 GB", device: "cpu" as const },
	{ name: "large-v3", description: "Best accuracy — needs 4+ GB", size: "~3 GB", device: "gpu" as const },
];

const SUGGESTED_IMAGE_MODELS = [
	{ name: "stable-diffusion-2-1", description: "Good quality — versatile default", size: "~5 GB", device: "gpu" as const },
	{ name: "sdxl-turbo", description: "Fast SDXL — 1-4 step generation", size: "~7 GB", device: "gpu" as const },
	{ name: "sdxl-base", description: "Highest quality — SDXL 1.0", size: "~7 GB", device: "gpu" as const },
	{ name: "sd-1.5", description: "Classic SD 1.5 — huge ecosystem", size: "~4 GB", device: "gpu" as const },
	{ name: "flux-schnell", description: "FLUX.1 Schnell — fast, high quality", size: "~12 GB", device: "gpu" as const },
	{ name: "segmind-tiny", description: "Tiny SD — CPU-friendly, compact", size: "~1 GB", device: "cpu" as const },
	{ name: "small-sd", description: "Small SD — runs on CPU, decent quality", size: "~1.5 GB", device: "cpu" as const },
];

// ----- Component -----

export function AISetupGuide({ isOpen, onOpenChange }: AISetupGuideProps) {
	const { services, isChecking, checkAll, loadModel, testModel } = useServiceHealth(isOpen);
	const [whisperError, setWhisperError] = useState<string | null>(null);
	const [ttsError, setTtsError] = useState<string | null>(null);
	const [diffusionError, setDiffusionError] = useState<string | null>(null);
	const [actionMessage, setActionMessage] = useState<string | null>(null);
	const [activeTTSModel, setActiveTTSModel] = useState<string>("");
	const [activeTTSDevice, setActiveTTSDevice] = useState<string>("cpu");
	const [isSwitchingTTS, setIsSwitchingTTS] = useState<string | null>(null);
	const [activeWhisperModel, setActiveWhisperModel] = useState<string>("");
	const [activeWhisperDevice, setActiveWhisperDevice] = useState<string>("cpu");
	const [isSwitchingWhisper, setIsSwitchingWhisper] = useState<string | null>(null);
	const [activeImageModel, setActiveImageModel] = useState<string>("");
	const [activeImageDevice, setActiveImageDevice] = useState<string>("cpu");
	const [isSwitchingImage, setIsSwitchingImage] = useState<string | null>(null);
	const [isTestingService, setIsTestingService] = useState<string | null>(null);

	const isLoading = isChecking;

	// Re-fetch when dialog opens
	useEffect(() => {
		if (isOpen) {
			checkAll();
			// Fetch active TTS model + device
			fetch(`${SERVICE_URLS.tts}/models`, { signal: AbortSignal.timeout(5000) })
				.then((r) => r.ok ? r.json() : null)
				.then((d) => {
					setActiveTTSModel(d?.active_model ?? "");
					if (d?.device) setActiveTTSDevice(d.device);
				})
				.catch(() => {});
			// Fetch active Whisper model + device
			fetch(`${SERVICE_URLS.whisper}/health`, { signal: AbortSignal.timeout(5000) })
				.then((r) => r.ok ? r.json() : null)
				.then((d) => {
					setActiveWhisperModel(loadedWhisperModel(d?.model));
					if (d?.model?.device) setActiveWhisperDevice(d.model.device);
				})
				.catch(() => {});
			// Fetch active Image model + device
			fetch(`${SERVICE_URLS.image}/models`, { signal: AbortSignal.timeout(5000) })
				.then((r) => r.ok ? r.json() : null)
				.then((d) => {
					if (d?.active_model) setActiveImageModel(d.active_model);
					if (d?.device) setActiveImageDevice(d.device);
				})
				.catch(() => {});
		}
	}, [isOpen, checkAll]);

	const handleRefresh = useCallback(async () => {
		await checkAll();
	}, [checkAll]);

	const handleSwitchTTSModel = useCallback(async (modelName: string) => {
		setIsSwitchingTTS(modelName);
		setTtsError(null);
		setActionMessage(null);
		try {
			const result = await loadModel("tts", { model_name: modelName });
			if (result.verified) {
				setActiveTTSModel(modelName);
				setActionMessage(`TTS switched to ${modelName}`);
				toast.success(`TTS now using ${modelName}`);
				// Refresh device info
				fetch(`${SERVICE_URLS.tts}/models`, { signal: AbortSignal.timeout(5000) })
					.then((r) => r.ok ? r.json() : null)
					.then((d) => { if (d?.device) setActiveTTSDevice(d.device); })
					.catch(() => {});
			} else {
				setTtsError("Model loaded but could not be verified. Try again.");
			}
		} catch (error) {
			setTtsError(error instanceof Error ? error.message : "Failed to switch TTS model");
		} finally {
			setIsSwitchingTTS(null);
		}
	}, [loadModel]);

	const handleSwitchWhisperModel = useCallback(async (modelSize: string) => {
		setIsSwitchingWhisper(modelSize);
		setWhisperError(null);
		setActionMessage(null);
		try {
			const result = await loadModel("whisper", { model_size: modelSize });
			if (result.verified) {
				setActiveWhisperModel(modelSize);
				setActionMessage(`Whisper switched to ${modelSize}`);
				toast.success(`Whisper now using ${modelSize}`);
			} else {
				setWhisperError("Model loaded but could not be verified. Click 'Verify' to re-check.");
			}
		} catch (error) {
			setWhisperError(error instanceof Error ? error.message : "Failed to switch Whisper model");
		} finally {
			setIsSwitchingWhisper(null);
		}
	}, [loadModel]);

	const handleSwitchImageModel = useCallback(async (modelName: string) => {
		setIsSwitchingImage(modelName);
		setDiffusionError(null);
		setActionMessage(null);
		try {
			const result = await loadModel("image", { model_name: modelName });
			if (result.verified) {
				setActiveImageModel(modelName);
				setActionMessage(`Image model switched to ${modelName}`);
				toast.success(`Image model now using ${modelName}`);
				fetch(`${SERVICE_URLS.image}/models`, { signal: AbortSignal.timeout(5000) })
					.then((r) => r.ok ? r.json() : null)
					.then((d) => { if (d?.device) setActiveImageDevice(d.device); })
					.catch(() => {});
			} else {
				setDiffusionError("Model loaded but could not be verified. Try again.");
			}
		} catch (error) {
			setDiffusionError(error instanceof Error ? error.message : "Failed to switch image model");
		} finally {
			setIsSwitchingImage(null);
		}
	}, [loadModel]);

	const handleTestService = useCallback(async (service: "whisper" | "tts" | "image", label: string) => {
		setIsTestingService(service);
		setActionMessage(null);
		try {
			const result = await testModel(service);
			if (result.ok) {
				setActionMessage(result.message ?? `${label} is working correctly.`);
				toast.success(`${label} test passed`);
			} else {
				const errMsg = result.message ?? `${label} test failed.`;
				if (service === "tts") setTtsError(errMsg);
				if (service === "whisper") setWhisperError(errMsg);
				if (service === "image") setDiffusionError(errMsg);
			}
		} catch (error) {
			const msg = error instanceof Error ? error.message : "Test failed";
			if (service === "tts") setTtsError(msg);
			if (service === "whisper") setWhisperError(msg);
			if (service === "image") setDiffusionError(msg);
		} finally {
			setIsTestingService(null);
		}
	}, [testModel]);

	const backend = services.backend;
	const whisper = services.whisper;
	const tts = services.tts;
	const diffusion = services.image;

	const isBackendRunning = backend.status === "running";
	const isWhisperRunning = whisper.status === "running";
	const isTTSRunning = tts.status === "running";
	const isImageRunning = diffusion.status === "running";

	// Count how many services are ready
	const readyCount = [
		isBackendRunning,
		isWhisperRunning,
		isTTSRunning,
		isImageRunning,
	].filter(Boolean).length;
	const totalServices = 4; // backend, whisper, tts, image

	return (
		<Dialog open={isOpen} onOpenChange={onOpenChange}>
			<DialogContent className="max-w-lg max-h-[85vh] flex flex-col">
				<DialogHeader>
					<DialogTitle className="flex items-center gap-2">
						<HugeiconsIcon icon={SparklesIcon} className="size-5 text-primary" />
						AI Setup
					</DialogTitle>
					<DialogDescription>
						Manage AI services, models, and verify everything is ready.
					</DialogDescription>
				</DialogHeader>

				<ScrollArea className="flex-1">
					<div className="flex flex-col gap-4 px-6 pb-2">

						{/* ── Overall Status ── */}
						<div
							className={cn(
								"flex items-center gap-3 rounded-lg px-3 py-2.5 text-xs",
								readyCount >= totalServices
									? "bg-green-500/10 text-green-400"
									: readyCount > 0
										? "bg-yellow-500/10 text-yellow-400"
										: "bg-red-500/10 text-red-400",
							)}
						>
							<span
								className={cn(
									"size-2.5 rounded-full shrink-0",
									readyCount >= totalServices
										? "bg-green-500"
										: readyCount > 0 ? "bg-yellow-500" : "bg-red-500",
								)}
							/>
							<div className="flex-1">
								{readyCount >= totalServices ? (
									<span className="font-medium">All {totalServices} services running</span>
								) : readyCount > 0 ? (
									<span className="font-medium">
										{readyCount}/{totalServices} services running
									</span>
								) : (
									<div>
										<span className="font-medium">No services running</span>
										<p className="text-[11px] mt-0.5 opacity-80">
											Start all with: <code className="font-mono bg-black/20 px-1 rounded">docker compose up -d</code>
										</p>
									</div>
								)}
							</div>
							<Button
								variant="ghost"
								size="sm"
								onClick={handleRefresh}
								disabled={isLoading}
								className="h-6 text-[11px] px-2 shrink-0"
							>
								{isLoading ? <Spinner className="size-3" /> : "Refresh"}
							</Button>
						</div>

						{/* ── 1. Docker / Backend Service ── */}
						<ServiceCard
							title="AI Backend"
							status={isBackendRunning ? "running" : "stopped"}
							detail={isBackendRunning ? `v${backend?.version ?? "0.1.0"} on port 8420` : SERVICE_URLS.backend}
						>
							{!isBackendRunning && (
								<div className="flex flex-col gap-2 mt-2">
									<p className="text-[11px] text-muted-foreground leading-relaxed">
										The AI backend gateway powers all AI features. Start it using Docker:
									</p>
									<div className="flex flex-col gap-1">
										<CommandBlock label="Start all services" command="docker compose up -d" />
										<CommandBlock label="Or start backend only" command={SERVICE_DOCKER_COMMANDS.backend} />
									</div>
								</div>
							)}
						</ServiceCard>

						{/* ── 2. TTS (Voice Generation) ── */}
						<ServiceCard
							title="Voice (TTS)"
							status={isTTSRunning
								? (tts.model_loaded || activeTTSModel)
									? "loaded"
									: tts.model_installed === false
										? "not_installed"
										: "available"
								: "stopped"
							}
							detail={
								!isTTSRunning
									? SERVICE_URLS.tts
									: (tts.model_loaded || activeTTSModel)
										? `${activeTTSModel || tts.model_name || "omnivoice"} loaded`
										: tts.model_installed === false
											? "Not installed"
											: "Choose a model to load"
							}
						>
							{!isTTSRunning && (
								<div className="mt-2 flex flex-col gap-2">
									<p className="text-[11px] text-muted-foreground leading-relaxed">
										TTS service is not running. Start it with Docker:
									</p>
									<CommandBlock label="Start TTS" command={SERVICE_DOCKER_COMMANDS.tts} />
								</div>
							)}

							{isTTSRunning && (
								<div className="mt-2 flex flex-col gap-2">
									{/* Active model */}
									{(tts.model_loaded || activeTTSModel) && activeTTSModel && (
										<div className="flex flex-col gap-1">
											<span className="text-[11px] text-muted-foreground font-medium">Active model</span>
											<div className="flex items-center justify-between rounded px-2 py-1.5 text-[11px] bg-primary/10 border border-primary/30">
												<div className="flex items-center gap-1.5">
													<span className={cn("size-1.5 rounded-full bg-primary")} />
													<span className="font-medium">{activeTTSModel}</span>
													<Badge
														variant="outline"
														className={cn(
															"text-[8px] px-1 py-0",
															activeTTSDevice === "cuda"
																? "text-purple-400 border-purple-500/30"
																: "text-green-400 border-green-500/30",
														)}
													>
														{activeTTSDevice === "cuda" ? "GPU" : "CPU"}
													</Badge>
												</div>
												<div className="flex items-center gap-1.5">
													<Badge variant="default" className="text-[8px] px-1.5 py-0 h-4">Active</Badge>
													<Button
														variant="ghost"
														size="sm"
														className="h-5 text-[10px] px-1.5 text-muted-foreground"
														disabled={isTestingService === "tts"}
														onClick={() => handleTestService("tts", "TTS")}
													>
														{isTestingService === "tts" ? <Spinner className="size-2.5" /> : "Test"}
													</Button>
												</div>
											</div>
										</div>
									)}

									{/* Model list */}
									<div className="flex flex-col gap-1">
										<span className="text-[11px] text-muted-foreground font-medium">
											{(tts.model_loaded || activeTTSModel) ? "Switch to a different model" : "Choose a model to load"}
										</span>
										{TTS_MODELS.map((model) => {
											const isActive = model.name === activeTTSModel;
											const isSwitching = isSwitchingTTS === model.name;

											return (
												<div
													key={model.name}
													className={cn(
														"flex items-center gap-2 rounded px-2.5 py-2 text-[11px]",
														isActive
															? "bg-primary/10 border border-primary/30"
															: "bg-muted/30",
													)}
												>
													<div className="flex-1 min-w-0">
														<div className="flex items-center gap-1.5 flex-wrap">
															<span className="font-medium font-mono">{model.name}</span>
															<span className="text-muted-foreground">{model.size}</span>
															<Badge
																variant="outline"
																className={cn(
																	"text-[8px] px-1 py-0",
																	model.device === "cpu"
																		? "text-green-400 border-green-500/30"
																		: "text-purple-400 border-purple-500/30",
																)}
															>
																{model.device === "cpu" ? "CPU" : "GPU"}
															</Badge>
															{model.multilingual && (
																<Badge
																	variant="outline"
																	className="text-[8px] px-1 py-0 text-blue-400 border-blue-500/30"
																>
																	Multilingual
																</Badge>
															)}
															{model.voiceCloning && (
																<Badge
																	variant="outline"
																	className="text-[8px] px-1 py-0 text-purple-400 border-purple-500/30"
																>
																	Cloning
																</Badge>
															)}
															{isActive && (
																<Badge variant="default" className="text-[8px] px-1 py-0 h-3.5">
																	Active
																</Badge>
															)}
														</div>
														<p className="text-muted-foreground mt-0.5">{model.description}</p>
													</div>
													<div className="shrink-0">
														{isSwitching ? (
															<Button size="sm" variant="outline" className="h-6 text-[10px] px-2" disabled>
																<Spinner className="size-3 mr-1" />
																Loading...
															</Button>
														) : isActive ? (
															<Badge variant="default" className="text-[9px] px-1.5 py-0.5">
																In use
															</Badge>
														) : (
															<Button
																size="sm"
																variant="secondary"
																className="h-6 text-[10px] px-2"
																disabled={isSwitchingTTS !== null}
																onClick={() => handleSwitchTTSModel(model.name)}
															>
																<HugeiconsIcon icon={Download04Icon} className="size-3 mr-0.5" />
																Load & Use
															</Button>
														)}
													</div>
												</div>
											);
										})}
									</div>

									{ttsError && (
										<p className="text-[11px] text-destructive">{ttsError}</p>
									)}
								</div>
							)}
						</ServiceCard>

						{/* ── 3. Whisper (Transcription) ── */}
						<ServiceCard
							title="Whisper (Transcription)"
							status={isWhisperRunning
								? (whisper.model_loaded || activeWhisperModel ? "loaded" : "available")
								: "stopped"
							}
							detail={
								!isWhisperRunning
									? SERVICE_URLS.whisper
									: (whisper.model_loaded || activeWhisperModel)
										? `"${activeWhisperModel || whisper.model_size || "base"}" loaded`
										: "Choose a model to load"
							}
						>
							{!isWhisperRunning && (
								<div className="mt-2 flex flex-col gap-2">
									<p className="text-[11px] text-muted-foreground leading-relaxed">
										Whisper service is not running. Start it with Docker:
									</p>
									<CommandBlock label="Start Whisper" command={SERVICE_DOCKER_COMMANDS.whisper} />
								</div>
							)}

							{isWhisperRunning && (
								<div className="mt-2 flex flex-col gap-2">
									{/* Active model */}
									{(whisper.model_loaded || activeWhisperModel) && activeWhisperModel && (
										<div className="flex flex-col gap-1">
											<span className="text-[11px] text-muted-foreground font-medium">Active model</span>
											<div className="flex items-center justify-between rounded px-2 py-1.5 text-[11px] bg-primary/10 border border-primary/30">
												<div className="flex items-center gap-1.5">
													<span className={cn("size-1.5 rounded-full bg-primary")} />
													<span className="font-medium">{activeWhisperModel}</span>
													<Badge
														variant="outline"
														className={cn(
															"text-[8px] px-1 py-0",
															activeWhisperDevice === "cuda"
																? "text-purple-400 border-purple-500/30"
																: "text-green-400 border-green-500/30",
														)}
													>
														{activeWhisperDevice === "cuda" ? "GPU" : "CPU"}
													</Badge>
												</div>
												<div className="flex items-center gap-1.5">
													<Badge variant="default" className="text-[8px] px-1.5 py-0 h-4">Active</Badge>
													<Button
														variant="ghost"
														size="sm"
														className="h-5 text-[10px] px-1.5 text-muted-foreground"
														disabled={isTestingService === "whisper"}
														onClick={() => handleTestService("whisper", "Whisper")}
													>
														{isTestingService === "whisper" ? <Spinner className="size-2.5" /> : "Test"}
													</Button>
												</div>
											</div>
										</div>
									)}

									{/* Model list */}
									<div className="flex flex-col gap-1">
										<span className="text-[11px] text-muted-foreground font-medium">
											{(whisper.model_loaded || activeWhisperModel) ? "Switch to a different model" : "Choose a model to load"}
										</span>
										{SUGGESTED_WHISPER_MODELS.map((model) => {
											const isActive = model.name === activeWhisperModel;
											const isSwitching = isSwitchingWhisper === model.name;

											return (
												<div
													key={model.name}
													className={cn(
														"flex items-center gap-2 rounded px-2.5 py-2 text-[11px]",
														isActive
															? "bg-primary/10 border border-primary/30"
															: "bg-muted/30",
													)}
												>
													<div className="flex-1 min-w-0">
														<div className="flex items-center gap-1.5 flex-wrap">
															<span className="font-medium font-mono">{model.name}</span>
															<span className="text-muted-foreground">{model.size}</span>
															<Badge
																variant="outline"
																className={cn(
																	"text-[8px] px-1 py-0",
																	model.device === "cpu"
																		? "text-green-400 border-green-500/30"
																		: "text-purple-400 border-purple-500/30",
																)}
															>
																{model.device === "cpu" ? "CPU" : "GPU"}
															</Badge>
															{isActive && (
																<Badge variant="default" className="text-[8px] px-1 py-0 h-3.5">
																	Active
																</Badge>
															)}
														</div>
														<p className="text-muted-foreground mt-0.5">{model.description}</p>
													</div>
													<div className="shrink-0">
														{isSwitching ? (
															<Button size="sm" variant="outline" className="h-6 text-[10px] px-2" disabled>
																<Spinner className="size-3 mr-1" />
																Loading...
															</Button>
														) : isActive ? (
															<Badge variant="default" className="text-[9px] px-1.5 py-0.5">
																In use
															</Badge>
														) : (
															<Button
																size="sm"
																variant="secondary"
																className="h-6 text-[10px] px-2"
																disabled={isSwitchingWhisper !== null}
																onClick={() => handleSwitchWhisperModel(model.name)}
															>
																<HugeiconsIcon icon={Download04Icon} className="size-3 mr-0.5" />
																Load & Use
															</Button>
														)}
													</div>
												</div>
											);
										})}
									</div>

									{whisperError && (
										<p className="text-[11px] text-destructive">{whisperError}</p>
									)}
								</div>
							)}
						</ServiceCard>

						{/* ── 4. Image Generation ── */}
						<ServiceCard
							title="Image Generation"
							status={isImageRunning
								? (diffusion.model_loaded || activeImageModel)
									? "loaded"
									: diffusion.model_installed === false
										? "not_installed"
										: "available"
								: "stopped"
							}
							detail={
								!isImageRunning
									? SERVICE_URLS.image
									: (diffusion.model_loaded || activeImageModel)
										? `${activeImageModel || diffusion.model_name || "stable-diffusion-2-1"} loaded`
										: diffusion.model_installed === false
											? "Not installed"
											: "Choose a model to load"
							}
						>
							{!isImageRunning && (
								<div className="mt-2 flex flex-col gap-2">
									<p className="text-[11px] text-muted-foreground leading-relaxed">
										Image service is not running. Start it with Docker:
									</p>
									<CommandBlock label="Start Image service" command={SERVICE_DOCKER_COMMANDS.image} />
								</div>
							)}

							{isImageRunning && (
								<div className="mt-2 flex flex-col gap-2">
									{/* Active model */}
									{(diffusion.model_loaded || activeImageModel) && activeImageModel && (
										<div className="flex flex-col gap-1">
											<span className="text-[11px] text-muted-foreground font-medium">Active model</span>
											<div className="flex items-center justify-between rounded px-2 py-1.5 text-[11px] bg-primary/10 border border-primary/30">
												<div className="flex items-center gap-1.5">
													<span className={cn("size-1.5 rounded-full bg-primary")} />
													<span className="font-medium">{activeImageModel}</span>
													<Badge
														variant="outline"
														className={cn(
															"text-[8px] px-1 py-0",
															activeImageDevice === "cuda"
																? "text-purple-400 border-purple-500/30"
																: "text-green-400 border-green-500/30",
														)}
													>
														{activeImageDevice === "cuda" ? "GPU" : "CPU"}
													</Badge>
												</div>
												<div className="flex items-center gap-1.5">
													<Badge variant="default" className="text-[8px] px-1.5 py-0 h-4">Active</Badge>
													<Button
														variant="ghost"
														size="sm"
														className="h-5 text-[10px] px-1.5 text-muted-foreground"
														disabled={isTestingService === "image"}
														onClick={() => handleTestService("image", "Image")}
													>
														{isTestingService === "image" ? <Spinner className="size-2.5" /> : "Test"}
													</Button>
												</div>
											</div>
										</div>
									)}

									{/* Model list */}
									<div className="flex flex-col gap-1">
										<span className="text-[11px] text-muted-foreground font-medium">
											{(diffusion.model_loaded || activeImageModel) ? "Switch to a different model" : "Choose a model to load"}
										</span>
										{SUGGESTED_IMAGE_MODELS.map((model) => {
											const isActive = model.name === activeImageModel;
											const isSwitching = isSwitchingImage === model.name;

											return (
												<div
													key={model.name}
													className={cn(
														"flex items-center gap-2 rounded px-2.5 py-2 text-[11px]",
														isActive
															? "bg-primary/10 border border-primary/30"
															: "bg-muted/30",
													)}
												>
													<div className="flex-1 min-w-0">
														<div className="flex items-center gap-1.5 flex-wrap">
															<span className="font-medium font-mono">{model.name}</span>
															<span className="text-muted-foreground">{model.size}</span>
															<Badge
																variant="outline"
																className={cn(
																	"text-[8px] px-1 py-0",
																	model.device === "cpu"
																		? "text-green-400 border-green-500/30"
																		: "text-purple-400 border-purple-500/30",
																)}
															>
																{model.device === "cpu" ? "CPU" : "GPU"}
															</Badge>
															{isActive && (
																<Badge variant="default" className="text-[8px] px-1 py-0 h-3.5">
																	Active
																</Badge>
															)}
														</div>
														<p className="text-muted-foreground mt-0.5">{model.description}</p>
													</div>
													<div className="shrink-0">
														{isSwitching ? (
															<Button size="sm" variant="outline" className="h-6 text-[10px] px-2" disabled>
																<Spinner className="size-3 mr-1" />
																Loading...
															</Button>
														) : isActive ? (
															<Badge variant="default" className="text-[9px] px-1.5 py-0.5">
																In use
															</Badge>
														) : (
															<Button
																size="sm"
																variant="secondary"
																className="h-6 text-[10px] px-2"
																disabled={isSwitchingImage !== null}
																onClick={() => handleSwitchImageModel(model.name)}
															>
																<HugeiconsIcon icon={Download04Icon} className="size-3 mr-0.5" />
																Load & Use
															</Button>
														)}
													</div>
												</div>
											);
										})}
									</div>

									{diffusionError && (
										<p className="text-[11px] text-destructive">{diffusionError}</p>
									)}
								</div>
							)}
						</ServiceCard>

						{/* ── Success message ── */}
						{actionMessage && (
							<div className="flex items-center gap-2 rounded-lg bg-green-500/10 px-3 py-2 text-[11px] text-green-400">
								<HugeiconsIcon icon={Tick01Icon} className="size-3.5 shrink-0" />
								{actionMessage}
							</div>
						)}

					</div>
				</ScrollArea>

				<DialogFooter>
					{readyCount >= totalServices ? (
						<Button onClick={() => onOpenChange(false)}>
							Get started
							<HugeiconsIcon icon={ArrowRight01Icon} className="!size-3.5 ml-1" />
						</Button>
					) : (
						<div className="flex items-center gap-2 w-full">
							<Button variant="outline" onClick={() => onOpenChange(false)} className="flex-1">
								Close
							</Button>
							<Button onClick={handleRefresh} disabled={isLoading} className="flex-1">
								{isLoading ? (
									<>
										<Spinner className="size-3 mr-1" />
										Checking...
									</>
								) : (
									"Check all services"
								)}
							</Button>
						</div>
					)}
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

// ----- Sub-components -----

function ServiceCard({
	title,
	status,
	detail,
	children,
}: {
	title: string;
	status: ServiceState;
	detail: string;
	children?: React.ReactNode;
}) {
	const badge = statusBadge(status);

	return (
		<Card className="rounded-lg">
			<CardContent className="p-3">
				<div className="flex items-center justify-between">
					<div className="flex items-center gap-2">
						<span className={cn("size-2 rounded-full shrink-0", badge.dotColor)} />
						<span className="text-xs font-medium">{title}</span>
					</div>
					<div className="flex items-center gap-2">
						<span className="text-[11px] text-muted-foreground">{detail}</span>
						<Badge
							variant={badge.variant}
							className="text-[9px] px-1.5 py-0"
						>
							{badge.label}
						</Badge>
					</div>
				</div>
				{children}
			</CardContent>
		</Card>
	);
}

function CommandBlock({ label, command }: { label: string; command: string }) {
	return (
		<div className="mt-1">
			<span className="text-[10px] text-muted-foreground">{label}:</span>
			<code className="block text-[11px] font-mono bg-muted rounded px-2 py-1 mt-0.5 text-muted-foreground select-all">
				{command}
			</code>
		</div>
	);
}
