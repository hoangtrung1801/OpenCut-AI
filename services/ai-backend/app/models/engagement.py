"""Request and response models for engagement scoring and YouTube ingestion."""

from typing import Any

from pydantic import BaseModel, Field


class ScoreClipRequest(BaseModel):
    audio_path: str | None = None
    video_path: str | None = None
    transcript_text: str = ""
    transcript_segments: list[dict[str, Any]] = Field(default_factory=list)
    start: float = 0.0
    end: float = 30.0
    title: str = ""


class ScoreBatchRequest(BaseModel):
    clips: list[ScoreClipRequest] = Field(default_factory=list)


class HookScore(BaseModel):
    visual_novelty: float = 0.0
    audio_energy_spike: float = 0.0
    early_face_present: bool = False
    hook_type: str = "neutral"
    hook_type_confidence: float = 0.0
    speech_rate: float = 0.0
    composite: float = 50.0


class EnergyScore(BaseModel):
    mean_energy: float = 0.0
    peak_energy: float = 0.0
    energy_variance: float = 0.0
    has_dynamic_range: bool = False
    composite: float = 50.0


class CuriosityScore(BaseModel):
    has_question: bool = False
    has_bold_claim: bool = False
    has_open_loop: bool = False
    gap_count: int = 0
    composite: float = 50.0


class FacePresenceScore(BaseModel):
    face_ratio: float = 0.0
    is_optimal: bool = False
    early_face_present: bool = False
    composite: float = 50.0


class EmotionalArcScore(BaseModel):
    has_strong_open: bool = False
    has_buildup: bool = False
    has_peak: bool = False
    peak_timestamp: float = 0.0
    dominant_emotion: str = "neutral"
    composite: float = 50.0


class ViralityScore(BaseModel):
    hook_strength: int = 0
    shareability: int = 0
    emotional_impact: int = 0
    standalone_value: int = 0
    reason: str = ""
    suggested_title: str = ""
    composite: float = 50.0


class AudioSyncScore(BaseModel):
    bpm: float | None = None
    beat_count: int = 0
    caption_beat_alignment: float = 50.0
    composite: float = 50.0


class EnhancementSuggestion(BaseModel):
    signal: str
    current_score: float
    suggestion: str
    action_type: str
    expected_impact: str


class EngagementScore(BaseModel):
    hook: HookScore = Field(default_factory=HookScore)
    curiosity: CuriosityScore = Field(default_factory=CuriosityScore)
    energy: EnergyScore = Field(default_factory=EnergyScore)
    audio_sync: AudioSyncScore = Field(default_factory=AudioSyncScore)
    face_presence: FacePresenceScore = Field(default_factory=FacePresenceScore)
    emotional_arc: EmotionalArcScore = Field(default_factory=EmotionalArcScore)
    virality: ViralityScore = Field(default_factory=ViralityScore)
    suggestions: list[EnhancementSuggestion] = Field(default_factory=list)
    composite: float = 0.0
    grade: str = "C"
    grade_label: str = "Average"

    def model_post_init(self, __context: Any) -> None:
        if self.composite == 0.0:
            self.composite = round(
                self.hook.composite * 0.25
                + self.curiosity.composite * 0.20
                + self.virality.composite * 0.15
                + self.energy.composite * 0.15
                + self.emotional_arc.composite * 0.10
                + self.audio_sync.composite * 0.10
                + self.face_presence.composite * 0.05,
                1,
            )
        if self.grade == "C":
            self.grade, self.grade_label = _grade_for_score(self.composite)

    def to_response(self) -> dict[str, Any]:
        return self.model_dump()


def _grade_for_score(score: float) -> tuple[str, str]:
    if score >= 90:
        return "A", "Excellent"
    if score >= 80:
        return "B", "Strong"
    if score >= 70:
        return "C", "Good"
    if score >= 60:
        return "D", "Needs improvement"
    return "F", "Weak"


class ScoredClip(BaseModel):
    index: int
    title: str
    start: float
    end: float
    transcript_preview: str = ""
    tags: list[str] = Field(default_factory=list)
    engagement: EngagementScore | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


class YouTubeVideoMeta(BaseModel):
    video_id: str
    title: str
    channel_name: str
    channel_id: str
    duration_seconds: int
    thumbnail_url: str
    upload_date: str
    view_count: int | None = None
    is_live: bool = False
    is_private: bool = False
    warning: str | None = None


class JobStatus(BaseModel):
    job_id: str
    status: str
    progress: float = 0.0
    message: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None
