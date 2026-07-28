"""Subtitle generation from transcription segments."""

import math

from app.models.translation import (
    DisplayCaptionSegment,
    SubtitleDocumentSet,
    SubtitleVariants,
)


def _total_milliseconds(seconds: float) -> int:
    return max(0, round(float(seconds) * 1000))


def _format_srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp: HH:MM:SS,mmm."""
    total_ms = _total_milliseconds(seconds)
    h, remainder = divmod(total_ms, 3_600_000)
    m, remainder = divmod(remainder, 60_000)
    s, ms = divmod(remainder, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_vtt_time(seconds: float) -> str:
    """Format seconds as WebVTT timestamp: HH:MM:SS.mmm."""
    total_ms = _total_milliseconds(seconds)
    h, remainder = divmod(total_ms, 3_600_000)
    m, remainder = divmod(remainder, 60_000)
    s, ms = divmod(remainder, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _display_text(segment: DisplayCaptionSegment, order: str) -> str:
    if order == "source":
        return segment.source
    if order == "translation":
        return segment.translation
    if order == "source_translation":
        return f"{segment.source}\n{segment.translation}"
    if order == "translation_source":
        return f"{segment.translation}\n{segment.source}"
    raise ValueError(f"unsupported subtitle text order: {order}")


def _display_to_srt(segments: list[DisplayCaptionSegment], order: str) -> str:
    entries: list[str] = []
    for index, segment in enumerate(segments, start=1):
        entries.append(
            f"{index}\n"
            f"{_format_srt_time(segment.start)} --> {_format_srt_time(segment.end)}\n"
            f"{_display_text(segment, order)}"
        )
    return "\n\n".join(entries) + ("\n" if entries else "")


def _display_to_vtt(segments: list[DisplayCaptionSegment], order: str) -> str:
    lines: list[str] = ["WEBVTT", ""]
    for segment in segments:
        lines.extend(
            [
                f"{_format_vtt_time(segment.start)} --> {_format_vtt_time(segment.end)}",
                _display_text(segment, order),
                "",
            ]
        )
    return "\n".join(lines)


def build_subtitle_documents(
    segments: list[DisplayCaptionSegment],
) -> SubtitleDocumentSet:
    """Serialize final display cues without performing another line wrap."""
    orders = {
        "source": SubtitleVariants(
            srt=_display_to_srt(segments, "source"),
            vtt=_display_to_vtt(segments, "source"),
        ),
        "translation": SubtitleVariants(
            srt=_display_to_srt(segments, "translation"),
            vtt=_display_to_vtt(segments, "translation"),
        ),
        "source_translation": SubtitleVariants(
            srt=_display_to_srt(segments, "source_translation"),
            vtt=_display_to_vtt(segments, "source_translation"),
        ),
        "translation_source": SubtitleVariants(
            srt=_display_to_srt(segments, "translation_source"),
            vtt=_display_to_vtt(segments, "translation_source"),
        ),
    }
    return SubtitleDocumentSet(**orders)


def _split_text(text: str, max_chars: int) -> list[str]:
    """Split text at word boundaries respecting max_chars per line."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    words = text.split()
    lines: list[str] = []
    current_line = ""

    for word in words:
        candidate = f"{current_line} {word}".strip() if current_line else word
        if len(candidate) <= max_chars:
            current_line = candidate
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines


def segments_to_srt(segments: list[dict], max_chars: int = 42) -> str:
    """Convert transcript segments to SRT format with smart line splitting.

    Args:
        segments: List of dicts with 'start', 'end', and 'text' keys.
        max_chars: Maximum characters per subtitle line before wrapping.

    Returns:
        SRT-formatted subtitle string.
    """
    entries: list[str] = []

    for i, seg in enumerate(segments, start=1):
        start = _format_srt_time(seg["start"])
        end = _format_srt_time(seg["end"])
        lines = _split_text(seg.get("text", ""), max_chars)
        text_block = "\n".join(lines)
        entries.append(f"{i}\n{start} --> {end}\n{text_block}")

    return "\n\n".join(entries) + "\n"


def segments_to_vtt(segments: list[dict], max_chars: int = 42) -> str:
    """Convert transcript segments to WebVTT format.

    Args:
        segments: List of dicts with 'start', 'end', and 'text' keys.
        max_chars: Maximum characters per subtitle line before wrapping.

    Returns:
        WebVTT-formatted subtitle string.
    """
    lines: list[str] = ["WEBVTT", ""]

    for seg in segments:
        start = _format_vtt_time(seg["start"])
        end = _format_vtt_time(seg["end"])
        text_lines = _split_text(seg.get("text", ""), max_chars)
        text_block = "\n".join(text_lines)
        lines.append(f"{start} --> {end}")
        lines.append(text_block)
        lines.append("")

    return "\n".join(lines)


def segments_to_ass(segments: list[dict], style: dict | None = None) -> str:
    """Convert transcript segments to ASS (Advanced SubStation Alpha) format.

    Args:
        segments: List of dicts with 'start', 'end', and 'text' keys.
        style: Optional dict with keys: font_name, font_size, primary_color,
               outline_color, bold, alignment. Uses sensible defaults.

    Returns:
        ASS-formatted subtitle string.
    """
    s = style or {}
    font_name = s.get("font_name", "Arial")
    font_size = s.get("font_size", 20)
    primary_color = s.get("primary_color", "&H00FFFFFF")  # white
    outline_color = s.get("outline_color", "&H00000000")  # black
    bold = s.get("bold", 0)
    alignment = s.get("alignment", 2)  # bottom-center

    header = (
        "[Script Info]\n"
        "Title: OpenCut AI Subtitles\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_name},{font_size},{primary_color},&H000000FF,"
        f"{outline_color},&H80000000,{bold},0,0,0,100,100,0,0,1,2,1,"
        f"{alignment},10,10,30,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    events: list[str] = []
    for seg in segments:
        start = _format_ass_time(seg["start"])
        end = _format_ass_time(seg["end"])
        text = seg.get("text", "").strip().replace("\n", "\\N")
        events.append(
            f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}"
        )

    return header + "\n".join(events) + "\n"


def _format_ass_time(seconds: float) -> str:
    """Format seconds as ASS timestamp: H:MM:SS.cc (centiseconds)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - math.floor(seconds)) * 100))
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
