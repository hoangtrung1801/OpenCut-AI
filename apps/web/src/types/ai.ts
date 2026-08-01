// Transcription types
export interface TranscriptionWord {
	word: string;
	start: number;
	end: number;
	confidence: number;
}

export interface TranscriptionSegment {
	id: number;
	text: string;
	start: number;
	end: number;
	words: TranscriptionWord[];
	speaker?: string;
}

export interface SeparatedAudio {
	vocals_url: string;
	background_url: string;
}

export interface TranscriptionResult {
	segments: TranscriptionSegment[];
	language: string;
	duration: number;
	separated_audio?: SeparatedAudio;
}

export type DubbingVoice =
	| { mode: "clone"; speaker_wav: string; reference_text: string }
	| { mode: "design"; speaker: string }
	| { mode: "auto" };

export interface DubbingParentSegment {
	id: number;
	source: string;
	translation: string;
	start: number;
	end: number;
}

export interface DubbingDisplaySegment extends DubbingParentSegment {
	parent_id: number;
	part_index: number;
}

export interface DubbingJobRequest {
	source_language: string;
	target_language: string;
	audio_segments: DubbingParentSegment[];
	display_segments: DubbingDisplaySegment[];
	voice: DubbingVoice;
	pace?: number;
}

export type DubbingJobStatus =
	| "queued"
	| "preparing"
	| "generating"
	| "fitting"
	| "completed"
	| "failed";

export interface DubbingClipResult {
	id: number;
	parent_id: number;
	part_index: number;
	text: string;
	start: number;
	end: number;
	duration: number;
	audio_url: string;
	timing_warning?: "overflow";
}

export interface DubbingCaptionResult {
	id: number;
	parent_id: number;
	part_index: number;
	text: string;
	start: number;
	end: number;
}

export interface DubbingJobSnapshot {
	job_id: string;
	status: DubbingJobStatus;
	completed_clips: number;
	total_clips: number;
	result?: {
		clips: DubbingClipResult[];
		captions: DubbingCaptionResult[];
		srt: string;
	};
	error?: { code: string; message: string };
}

export interface TranslationTerm {
	source: string;
	target: string;
	note: string;
}

export interface ContextualTranslationWordInput {
	word: string;
	start: number;
	end: number;
}

export interface ContextualTranslationSegmentInput {
	id: number;
	text: string;
	start: number;
	end: number;
	words?: ContextualTranslationWordInput[];
}

export interface ContextualTranslationRequest {
	source_language: string;
	target_language: string;
	segments: ContextualTranslationSegmentInput[];
	custom_terms: TranslationTerm[];
}

export interface ContextualTranslatedSegment {
	id: number;
	source: string;
	translation: string;
	start: number;
	end: number;
}

export interface CaptionTranslationInput {
	id: number;
	source: string;
	translation: string;
	start: number;
	end: number;
	words: ContextualTranslationWordInput[];
}

export interface DisplayCaptionSegment {
	id: number;
	parent_id: number;
	part_index: number;
	source: string;
	translation: string;
	start: number;
	end: number;
}

export interface SubtitleVariants {
	srt: string;
	vtt: string;
}

export interface SubtitleDocumentSet {
	source: SubtitleVariants;
	translation: SubtitleVariants;
	source_translation: SubtitleVariants;
	translation_source: SubtitleVariants;
}

export interface CaptionPostProcessRequest {
	source_language: string;
	target_language: string;
	segments: CaptionTranslationInput[];
}

export interface CaptionPostProcessResult {
	source_language: string;
	target_language: string;
	display_segments: DisplayCaptionSegment[];
	audio_segments: ContextualTranslatedSegment[];
	subtitles: SubtitleDocumentSet;
}

export interface ContextualTranslationResult {
	source_language: string;
	target_language: string;
	theme: string;
	terminology: TranslationTerm[];
	segments: ContextualTranslatedSegment[];
	display_segments: DisplayCaptionSegment[];
	audio_segments: ContextualTranslatedSegment[];
	subtitles: SubtitleDocumentSet;
}

// Image generation
export interface ImageGenParams {
	prompt: string;
	negativePrompt?: string;
	width: number;
	height: number;
	steps: number;
	guidanceScale: number;
	model?: string;
}

export interface ImageGenResult {
	imageUrl: string;
	seed: number;
	prompt: string;
}

// LLM Command types
export type EditorActionType =
	| "REMOVE_SEGMENTS"
	| "ADD_SUBTITLE_TRACK"
	| "ADD_IMAGE_OVERLAY"
	| "TRIM_CLIP"
	| "ADD_TRANSITION"
	| "SPLIT_CLIP"
	| "ADD_TEXT_OVERLAY"
	| "ADJUST_SPEED"
	| "ADD_VOICEOVER"
	| "REMOVE_SILENCE"
	| "REMOVE_FILLERS"
	| "ADD_CHAPTER_MARKERS"
	| "DENOISE_AUDIO"
	| "GENERATE_IMAGE"
	| "SET_CANVAS_SIZE"
	| "ADD_MUSIC"
	| "NORMALIZE_AUDIO"
	| "AUTO_DUCK"
	| "COLOR_CORRECT"
	| "EXPORT_PROJECT";

export interface EditorAction {
	type: EditorActionType;
	params: Record<string, unknown>;
	description: string;
}

export interface CommandResult {
	actions: EditorAction[];
	explanation: string;
	needsClarification?: boolean;
	clarificationQuestion?: string;
}

// TTS types
export interface TTSRequest {
	text: string;
	language: string;
	speakerWav?: string;
	referenceText?: string;
	speaker?: string;
	speed?: number;
}

export interface TTSResult {
	audioUrl: string;
	duration: number;
}

// Audio types
export interface DenoiseRequest {
	strength: number;
}

export interface DenoiseResult {
	audioUrl: string;
	originalUrl: string;
}

// Silence detection
export interface SilenceRegion {
	start: number;
	end: number;
	duration: number;
}

// Filler detection
export interface FillerWord {
	word: string;
	start: number;
	end: number;
	segmentIndex: number;
	wordIndex: number;
	isFiller: boolean;
}

// Chapter detection
export interface Chapter {
	title: string;
	start: number;
	end: number;
	summary?: string;
}

export interface StructureAnalysis {
	chapters: Chapter[];
	highlights: { start: number; end: number; reason: string }[];
	suggestedTitle?: string;
	suggestedDescription?: string;
}

// B-Roll suggestions
export interface BRollSuggestion {
	segmentIndex: number;
	startTime: number;
	endTime: number;
	segmentText: string;
	visualDescription: string;
	imagePrompt: string;
	stockKeywords: string[];
	mood: string;
	priority: "high" | "medium" | "low";
}

export interface BRollSuggestionsResult {
	suggestions: BRollSuggestion[];
	totalSegments: number;
}

// Suggestion types
export interface AISuggestion {
	id: string;
	type: "warning" | "improvement" | "info";
	message: string;
	action?: EditorAction;
	dismissed: boolean;
}

// AI Backend status
export interface AIBackendStatus {
	available: boolean;
	models: string[];
	gpuAvailable: boolean;
	memoryUsage?: {
		ram?: { usedMb: number; totalMb: number; percent: number };
		gpu?: { usedMb: number; totalMb: number };
	};
	error?: string;
	errorType?: AIErrorType;
}

export type AIErrorType =
	| "connection_refused"
	| "timeout"
	| "backend_error"
	| "network_error"
	| "unknown";

// Infographic types
export interface InfographicTemplate {
	id: string;
	name: string;
	category:
		| "lower-third"
		| "stat-callout"
		| "comparison"
		| "step-flow"
		| "quote-card"
		| "list-overlay"
		| "progress-bar";
	thumbnail: string;
}

export interface InfographicData {
	template: string;
	content: Record<string, string | number>;
	style: {
		primaryColor: string;
		secondaryColor: string;
		fontFamily: string;
		fontSize: number;
		animation: "none" | "fade" | "slide" | "bounce";
	};
	position: { x: number; y: number };
	duration: number;
}

// Subtitle styles
export type SubtitlePreset = "captions" | "classic" | "modern" | "karaoke";

export interface SubtitleStyle {
	preset: SubtitlePreset;
	fontFamily: string;
	fontSize: number;
	fontColor: string;
	backgroundColor: string;
	outlineColor: string;
	outlineWidth: number;
	position: "top" | "center" | "bottom";
	animation: "none" | "word-highlight" | "karaoke-fill" | "bounce-in";
}

// Podcast clip types
export interface ClipCandidate {
	title: string;
	start: number;
	end: number;
	score: number;
	reason: string;
	tags: string[];
}

export interface FindClipsResult {
	clips: ClipCandidate[];
	total_duration: number;
}

export interface KeywordEntry {
	word: string;
	color: string;
	category: string;
}

export interface KeywordResult {
	keywords: KeywordEntry[];
}

export interface QuestionCard {
	question: string;
	timestamp: number;
	theme: "dark" | "gradient" | "bold" | "neon";
	emoji: string;
}

export interface QuestionCardsResult {
	cards: QuestionCard[];
}

// Face detection / auto-reframe
export interface FaceBBox {
	x: number;
	y: number;
	width: number;
	height: number;
	confidence: number;
}

export interface FaceFrame {
	timestamp: number;
	faces: FaceBBox[];
}

export interface FaceDetectionResult {
	frames: FaceFrame[];
	video_width: number;
	video_height: number;
	duration: number;
	total_faces_detected: number;
}

// Emotion detection
export interface EmotionSegment {
	start: number;
	end: number;
	emotion: string;
	intensity: number;
}

export interface EmotionDetectionResult {
	emotions: EmotionSegment[];
	method: string;
	peak_emotion: string;
}

// Speaker diarization
export interface SpeakerSegment {
	speaker: string;
	start: number;
	end: number;
}

export interface SpeakerDiarizationResult {
	segments: SpeakerSegment[];
	num_speakers: number;
	method: string;
}

// Model management
export interface ModelInfo {
	name: string;
	size: string;
	installed: boolean;
	downloading: boolean;
	progress: number;
}

export interface ModelTier {
	name: "lite" | "standard" | "full";
	label: string;
	description: string;
	totalSize: string;
	models: ModelInfo[];
}

// Reel template types
export interface ReelTemplateSegment {
	order: number;
	start_time: number;
	end_time: number;
	duration: number;
	title: string;
	narration: string;
	visual_description: string;
	key_message: string;
	audio_mood: string;
}

export interface AudioSuggestion {
	query: string;
	mood: string;
	tags: string[];
}

export interface ReelTemplate {
	topic: string;
	total_duration: number;
	style: string;
	title: string;
	segments: ReelTemplateSegment[];
	background_audio: AudioSuggestion;
}

// Video generation types
export type VideoProvider = "replicate" | "seedance" | "stability" | "luma" | "kling" | "local";

export type VideoGenMode = "text-to-video" | "image-to-video" | "video-to-video";

export interface VideoGenRequest {
	prompt: string;
	duration: number;
	width: number;
	height: number;
	provider: VideoProvider;
	model?: string;
	mode?: VideoGenMode;
	imageUrl?: string;
	videoUrl?: string;
}

export interface VideoGenResult {
	videoUrl: string;
	prompt: string;
	duration: number;
	provider: string;
	status: "completed" | "processing" | "failed";
	jobId?: string;
	error?: string;
}

export interface PromptGenResult {
	prompt: string;
	enhancedDescription: string;
}

// TurboQuant optimization types
export type ComputeMode = "auto" | "cpu" | "cuda";

export interface TurboQuantStatus {
	kv_cache_bits: number;
	/** What the user requested in Settings (same as kv_cache_bits, kept for clarity). */
	kv_cache_bits_requested?: number;
	/** What the active backend will actually use — GPU clamps to 2 or 3, CPU always 3. */
	kv_cache_bits_effective?: number;
	kv_compression_ratio: number;
	/** Compression ratio the backend is actually producing — measured live when available. */
	kv_compression_ratio_effective?: number;
	kv_quality: string;
	kv_cosine_similarity: number;
	memory_budget: string;
	model_tier: string;
	compute_mode: ComputeMode;
	recommended_tier: string;
	recommended_model: {
		name: string;
		model_tag: string;
		memory_mb: number;
		quality: string;
		quantization: string;
	};
	hardware: {
		ram_total_mb: number;
		ram_available_mb: number;
		gpu_available: boolean;
		gpu_vram_mb: number;
		gpu_name: string | null;
	};
	stack_memory_estimate: StackMemoryEstimate;
	inference_service: {
		available: boolean;
		reason?: string;
		model?: string;
		compute_mode?: string;
		turboquant_engine_available?: boolean;
		compression_ratio_last?: number | null;
	};
}

export interface StackMemoryEstimate {
	llm_mb: number;
	whisper_mb: number;
	tts_mb: number;
	kv_cache_compressed_mb: number;
	kv_cache_baseline_mb: number;
	total_with_turboquant_mb: number;
	total_without_turboquant_mb: number;
	savings_mb: number;
	kv_bits: number;
	/** The compression ratio used to compute the savings above. */
	kv_compression_ratio?: number;
	/** "measured" when the ratio came from a live inference, "estimated" from the static table. */
	source?: "measured" | "estimated";
}

export interface KVCacheConfig {
	bits: number;
	compression_ratio: number;
	cosine_similarity: number;
	quality: string;
	recommended: boolean;
	description: string;
}

export interface ModelTierSpec {
	name: string;
	label: string;
	description: string;
	min_ram_mb: number;
	models: {
		name: string;
		model_tag: string;
		memory_mb: number;
		quality: string;
		description: string;
		quantization: string;
	}[];
}

export interface ModelRecommendation {
	recommendation: {
		model: string;
		model_name: string;
		model_memory_mb: number;
		model_quality: string;
		model_quantization: string;
		whisper_model: string;
		whisper_compute_type: string;
		whisper_memory_mb: number;
		kv_cache_bits: number;
	};
	tier: string;
	budget: string;
	hardware: TurboQuantStatus["hardware"];
	stack_estimate: StackMemoryEstimate;
}

// TurboQuant multi-model types
export interface TQModelEntry {
	id: string;
	name: string;
	family: string;
	params: string;
	memory_fp16_mb: number;
	memory_4bit_mb: number;
	context_length: number;
	description: string;
	turboquant_validated: boolean;
	downloaded: boolean;
	loaded: boolean;
	downloading: boolean;
	loading: boolean;
	size_on_disk_mb?: number;
	download_progress?: { status: string; progress: number; message: string };
	quantization?: string;
	request_count?: number;
}

export interface TQModelsResponse {
	object: string;
	data: TQModelEntry[];
	active_model: string | null;
}

export interface TQDownloadProgress {
	status: "downloading" | "completed" | "error";
	progress: number;
	message: string;
}

export interface TQLoadResult {
	status: string;
	model_id: string;
	device: string;
	quantization: string;
	memory: Record<string, number>;
}
