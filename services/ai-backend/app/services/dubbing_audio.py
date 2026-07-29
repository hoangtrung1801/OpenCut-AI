"""Pure dubbing timing fitting and small FFmpeg audio adapters."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Mapping, Sequence


@dataclass(frozen=True)
class FittedClip:
    id: int
    start: float
    end: float
    duration: float
    timing_warning: Literal["overflow"] | None


@dataclass(frozen=True)
class ChunkFit:
    speed: float
    keep_gaps: bool
    clips: tuple[FittedClip, ...]


def fit_chunk_timing(
    *,
    clip_windows: Sequence[tuple[int, float, float]],
    raw_durations: Mapping[int, float],
    allowed_end: float,
    accept_speed: float,
    max_speed: float,
) -> ChunkFit:
    if not clip_windows:
        raise ValueError("a dubbing chunk must contain at least one clip")
    if accept_speed <= 0 or max_speed <= 0 or accept_speed > max_speed:
        raise ValueError("invalid dubbing speed limits")

    ordered = sorted(clip_windows, key=lambda item: (item[1], item[0]))
    window_start = ordered[0][1]
    window_duration = allowed_end - window_start
    if window_duration <= 0:
        raise ValueError("dubbing chunk window must be positive")
    for clip_id, _start, _end in ordered:
        duration = raw_durations.get(clip_id)
        if duration is None or not math.isfinite(duration) or duration <= 0:
            raise ValueError(f"missing duration for dubbing clip {clip_id}")

    gaps = [
        max(0.0, ordered[index][1] - ordered[index - 1][2])
        for index in range(1, len(ordered))
    ]
    raw_total = sum(raw_durations[clip_id] for clip_id, _, _ in ordered)
    with_gaps = raw_total + sum(gaps)

    keep_gaps = with_gaps / window_duration <= accept_speed
    fitted_total = with_gaps if keep_gaps else raw_total
    speed = min(max_speed, max(1.0, fitted_total / window_duration))

    cursor = window_start
    fitted: list[FittedClip] = []
    for clip_id, original_start, _original_end in ordered:
        if keep_gaps:
            cursor = max(cursor, original_start)
        duration = raw_durations[clip_id] / speed
        end = cursor + duration
        fitted.append(
            FittedClip(
                id=clip_id,
                start=cursor,
                end=end,
                duration=duration,
                timing_warning="overflow" if end > allowed_end else None,
            )
        )
        cursor = end

    return ChunkFit(
        speed=round(speed, 6),
        keep_gaps=keep_gaps,
        clips=tuple(fitted),
    )


CommandRunner = Callable[[Sequence[str]], None]
ProbeRunner = Callable[[Sequence[str]], str]


class DubbingAudioProcessor:
    def __init__(
        self,
        command_runner: CommandRunner | None = None,
        probe_runner: ProbeRunner | None = None,
    ):
        self.command_runner = command_runner or self._run_command
        self.probe_runner = probe_runner or self._run_probe

    @staticmethod
    def _run_command(args: Sequence[str]) -> None:
        subprocess.run(list(args), check=True, capture_output=True, text=True)

    @staticmethod
    def _run_probe(args: Sequence[str]) -> str:
        completed = subprocess.run(
            list(args),
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout

    def adjust_speed(self, source: Path, destination: Path, speed: float) -> None:
        if not source.is_file() or source.stat().st_size == 0:
            raise FileNotFoundError(f"dubbing source audio is missing: {source}")
        if not math.isfinite(speed) or speed < 1.0 or speed > 2.0:
            raise ValueError("dubbing speed must be between 1.0 and 2.0")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if abs(speed - 1.0) < 0.000001:
            shutil.copy2(source, destination)
            return
        self.command_runner((
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-filter:a",
            f"atempo={speed:.6f}",
            "-c:a",
            "pcm_s16le",
            str(destination),
        ))

    def probe_duration(self, path: Path) -> float:
        output = self.probe_runner((
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ))
        duration = float(json.loads(output)["format"]["duration"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError(f"invalid audio duration: {path}")
        return duration

    @staticmethod
    def write_silence(path: Path, duration: float = 0.1) -> None:
        if duration <= 0 or not math.isfinite(duration):
            raise ValueError("silence duration must be positive")
        path.parent.mkdir(parents=True, exist_ok=True)
        sample_rate = 16_000
        frame_count = max(1, round(sample_rate * duration))
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(b"\x00\x00" * frame_count)
