export const TTS_MODELS = [
	{
		name: "omnivoice",
		description: "600+ languages with voice cloning and voice design",
		size: "~2.5 GB",
		device: "cpu" as const,
		multilingual: true,
		voiceCloning: true,
	},
] as const;

export function loadedWhisperModel(model: unknown): string {
	if (!model || typeof model !== "object") return "";
	const value = model as { loaded?: unknown; model_size?: unknown };
	return value.loaded === true && typeof value.model_size === "string"
		? value.model_size
		: "";
}
