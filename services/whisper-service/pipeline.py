"""End-to-end Whisper enrichment orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alignment import WhisperAligner
from media_pipeline import MediaPipeline
from models import SeparatedAudio, TranscriptionResult, WordToken
from segmentation import SpacySegmenter, reconstruct_segments
from semantic_client import SemanticClient
from settings import Settings


class TranscriptionPipeline:
    def __init__(
        self,
        settings: Settings,
        *,
        media: MediaPipeline,
        asr: Any,
        aligner: WhisperAligner,
        segmenter: SpacySegmenter,
        semantic: SemanticClient,
    ):
        self.settings = settings
        self.media = media
        self.asr = asr
        self.aligner = aligner
        self.segmenter = segmenter
        self.semantic = semantic

    @staticmethod
    def _deterministic_candidates(words: list[WordToken]) -> list[int]:
        candidates: list[int] = []
        for index, word in enumerate(words[:-1]):
            if word.word.rstrip().endswith((".", "!", "?", "。", "！", "？")):
                candidates.append(index)
            elif words[index + 1].start - word.end >= 0.8:
                candidates.append(index)
        return candidates

    def run(
        self,
        source_path: Path,
        language: str | None,
        artifact_id: str,
    ) -> TranscriptionResult:
        prepared = None
        try:
            prepared = self.media.prepare(Path(source_path), artifact_id)
            raw_segments, info, native_words = self.asr.transcribe_raw(str(prepared.asr_path), language)
            detected_language = getattr(info, "language", None) or language or "en"
            aligned_words = self.aligner.align(
                native_words,
                raw_segments,
                detected_language,
                prepared.alignment_path,
            )
            preliminary = self.segmenter.preliminary_groups(aligned_words, detected_language)
            groups: list[list[WordToken]] = []
            for group in preliminary:
                if self.settings.semantic_split_enabled and len(group) > self.settings.semantic_max_words:
                    groups.extend(
                        self.semantic.split(
                            group,
                            detected_language,
                            self._deterministic_candidates(group),
                        )
                    )
                else:
                    groups.append(group)
            segments = reconstruct_segments(groups)
            return TranscriptionResult(
                text=" ".join(segment.text for segment in segments),
                segments=segments,
                language=detected_language,
                duration=round(float(getattr(info, "duration", 0.0) or 0.0), 3),
                separated_audio=SeparatedAudio(
                    vocals_url=f"/artifacts/{artifact_id}/vocals",
                    background_url=f"/artifacts/{artifact_id}/background",
                ),
            )
        finally:
            if prepared is not None:
                prepared.cleanup_temporary()

