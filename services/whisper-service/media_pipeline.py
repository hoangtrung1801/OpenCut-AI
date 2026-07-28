"""Audio preparation, Demucs separation, and durable stem artifacts."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Callable, Protocol, Sequence

from models import PreparedMedia
from settings import Settings

logger = logging.getLogger(__name__)


class MediaProcessingError(RuntimeError):
    """Raised when media normalization, separation, or encoding fails."""


class Separator(Protocol):
    def separate(self, source_path: Path, output_dir: Path) -> tuple[Path, Path]:
        """Return lossless vocal and background paths written under output_dir."""


class DemucsSeparator:
    """Lazy, process-safe wrapper around the Demucs separator."""

    _model = None
    _model_name = ""
    _lock = threading.Lock()

    def __init__(self, settings: Settings):
        self.settings = settings
        self.background_sources: list[str] = []

    def _device(self):
        import torch

        configured = self.settings.demucs_device
        if configured != "auto":
            return configured
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _load_model(self):
        with self._lock:
            if self._model is not None and self._model_name == self.settings.demucs_model:
                return self._model
            try:
                from demucs.pretrained import get_model

                model = get_model(self.settings.demucs_model)
                model.to(self._device())
                model.eval()
                self.__class__._model = model
                self.__class__._model_name = self.settings.demucs_model
                return model
            except Exception as exc:  # pragma: no cover - exercised in deployment
                raise MediaProcessingError(f"Unable to load Demucs model: {exc}") from exc

    @staticmethod
    def normalize_channels(waveform, expected_channels: int):
        """Adapt decoded audio to the channel count required by the Demucs model."""
        if waveform.ndim != 2:
            raise MediaProcessingError("Decoded audio must have shape [channels, samples]")
        if expected_channels <= 0:
            raise MediaProcessingError("Demucs model reported an invalid channel count")
        if waveform.shape[0] == expected_channels:
            return waveform
        # Demucs checkpoints are stereo. A mono source is duplicated so the
        # model receives the same mix on both channels without changing ASR audio.
        mono = waveform.mean(dim=0, keepdim=True)
        return mono.repeat(expected_channels, 1)

    def separate(self, source_path: Path, output_dir: Path) -> tuple[Path, Path]:
        try:
            import torch
            import torchaudio
            from demucs.apply import apply_model
        except Exception as exc:  # pragma: no cover - dependency validation covers this
            raise MediaProcessingError(f"Demucs dependencies are unavailable: {exc}") from exc

        model = self._load_model()
        device = self._device()
        try:
            waveform, sample_rate = torchaudio.load(str(source_path))
            waveform = self.normalize_channels(
                waveform,
                int(getattr(model, "audio_channels", 2)),
            )
            target_device = torch.device(device)
            with self._lock, torch.inference_mode():
                separated = apply_model(
                    model,
                    waveform.to(target_device).unsqueeze(0),
                    device=device,
                    split=True,
                    overlap=0.25,
                    progress=False,
                )[0]
            sources = list(model.sources)
            vocal_index = sources.index("vocals")
            vocal = separated[vocal_index].detach().cpu()
            background_indices = [index for index, name in enumerate(sources) if name != "vocals"]
            background = separated[background_indices].sum(dim=0).detach().cpu()
            self.background_sources = [sources[index] for index in background_indices]

            vocals_path = output_dir / "vocals-lossless.wav"
            background_path = output_dir / "background-lossless.wav"
            torchaudio.save(str(vocals_path), vocal, sample_rate)
            torchaudio.save(str(background_path), background, sample_rate)
            return vocals_path, background_path
        except MediaProcessingError:
            raise
        except Exception as exc:  # pragma: no cover - exercised in deployment
            raise MediaProcessingError(f"Demucs separation failed: {exc}") from exc


def _run_command(args: Sequence[str]) -> None:
    try:
        completed = subprocess.run(
            list(args),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        raise MediaProcessingError(
            f"Command failed ({list(args)[0]}): {stderr.strip() or exc}"
        ) from exc
    if completed.returncode != 0:  # defensive for custom runners
        raise MediaProcessingError(f"Command failed: {list(args)}")


class MediaPipeline:
    """Prepare an original mix and persist Demucs vocal/background artifacts."""

    _allowed_stems = frozenset({"vocals", "background"})

    def __init__(
        self,
        settings: Settings,
        *,
        separator: Separator | None = None,
        command_runner: Callable[[Sequence[str]], None] | None = None,
    ):
        self.settings = settings
        self.separator = separator or DemucsSeparator(settings)
        self.command_runner = command_runner or _run_command
        self.artifact_root = settings.artifact_dir
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    def _validate_artifact_id(self, artifact_id: str) -> None:
        try:
            parsed = uuid.UUID(artifact_id)
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("artifact_id must be a UUID") from exc
        if str(parsed) != artifact_id:
            raise ValueError("artifact_id must use canonical UUID spelling")

    def artifact_path(self, artifact_id: str, stem: str) -> Path:
        self._validate_artifact_id(artifact_id)
        if stem not in self._allowed_stems:
            raise ValueError(f"unsupported artifact stem: {stem}")
        artifact_dir = (self.artifact_root / artifact_id).resolve()
        root = self.artifact_root.resolve()
        if root not in artifact_dir.parents:
            raise ValueError("artifact path escapes configured artifact directory")
        return artifact_dir / f"{stem}.mp3"

    def _ffmpeg(self, *args: str) -> None:
        self.command_runner(("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args))

    def _encode_audio(self, source: Path, destination: Path, *, filter_args: Sequence[str] = ()) -> None:
        self._ffmpeg("-i", str(source), *filter_args, "-vn", "-c:a", "libmp3lame", "-b:a", self.settings.demucs_mp3_bitrate, str(destination))

    def prepare(self, source_path: Path, artifact_id: str) -> PreparedMedia:
        source = Path(source_path)
        if not source.is_file():
            raise MediaProcessingError(f"Source media does not exist: {source}")
        self._validate_artifact_id(artifact_id)
        final_dir = self.artifact_root / artifact_id
        partial_dir = self.artifact_root / f"{artifact_id}.partial"
        if final_dir.exists():
            raise MediaProcessingError(f"Artifact already exists: {artifact_id}")
        shutil.rmtree(partial_dir, ignore_errors=True)
        partial_dir.mkdir(parents=True, exist_ok=False)

        separation_source = partial_dir / "separation-source.wav"
        asr_path = partial_dir / "original-asr.wav"
        alignment_path = partial_dir / "vocal-align.wav"
        vocals_mp3 = partial_dir / "vocals.mp3"
        background_mp3 = partial_dir / "background.mp3"

        try:
            # Preserve source rate/channels for Demucs; ASR receives a separate normalized mix.
            self._ffmpeg("-i", str(source), "-c:a", "pcm_s16le", str(separation_source))
            self._ffmpeg("-i", str(source), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(asr_path))
            vocal_lossless, background_lossless = self.separator.separate(separation_source, partial_dir)
            self._ffmpeg(
                "-i",
                str(vocal_lossless),
                "-af",
                "loudnorm=I=-20:TP=-1.5:LRA=11",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(alignment_path),
            )
            self._encode_audio(vocal_lossless, vocals_mp3)
            self._encode_audio(background_lossless, background_mp3)
            for artifact in (vocals_mp3, background_mp3):
                if not artifact.is_file() or artifact.stat().st_size == 0:
                    raise MediaProcessingError(f"Empty separated artifact: {artifact.name}")

            os.replace(partial_dir, final_dir)
            return PreparedMedia(
                artifact_id=artifact_id,
                asr_path=final_dir / asr_path.name,
                alignment_path=final_dir / alignment_path.name,
                vocals_path=final_dir / vocals_mp3.name,
                background_path=final_dir / background_mp3.name,
                temporary_paths=(
                    final_dir / separation_source.name,
                    final_dir / asr_path.name,
                    final_dir / alignment_path.name,
                    final_dir / vocal_lossless.name,
                    final_dir / background_lossless.name,
                ),
            )
        except Exception as exc:
            shutil.rmtree(partial_dir, ignore_errors=True)
            if isinstance(exc, MediaProcessingError):
                raise
            raise MediaProcessingError(f"Media preparation failed: {exc}") from exc
