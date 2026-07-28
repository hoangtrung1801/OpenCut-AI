"""REST routes for audio/video transcription.

Proxies transcription requests to the whisper-service microservice.
Subtitle generation remains local (no heavy dependencies).
"""

import logging
import uuid

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["transcription"])


def _rewrite_artifact_urls(payload: dict) -> dict:
    separated = payload.get("separated_audio")
    if not isinstance(separated, dict):
        return payload
    for key in ("vocals_url", "background_url"):
        value = separated.get(key)
        if isinstance(value, str) and value.startswith("/artifacts/"):
            separated[key] = f"/api/transcribe{value}"
    return payload


async def _proxy_file_upload(
    service_url: str,
    path: str,
    file: UploadFile,
    extra_form: dict | None = None,
):
    """Forward a file upload to a downstream microservice."""
    async with httpx.AsyncClient(timeout=300) as client:
        files = {"file": (file.filename, await file.read(), file.content_type)}
        data = {}
        if extra_form:
            data = {k: str(v) for k, v in extra_form.items() if v is not None}
        resp = await client.post(f"{service_url}{path}", files=files, data=data)
        resp.raise_for_status()
        return resp


@router.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
):
    """Transcribe an uploaded audio or video file.

    Proxies to the whisper-service at WHISPER_SERVICE_URL.
    Returns structured JSON with segments and word-level timestamps.
    """
    try:
        resp = await _proxy_file_upload(
            settings.WHISPER_SERVICE_URL,
            "/transcribe",
            file,
            extra_form={"language": language} if language else {},
        )
        return _rewrite_artifact_urls(resp.json())
    except httpx.HTTPStatusError as e:
        detail = e.response.text if e.response else str(e)
        raise HTTPException(status_code=e.response.status_code, detail=detail)
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Whisper service is not available. Ensure whisper-service is running on "
            f"{settings.WHISPER_SERVICE_URL}",
        )
    except Exception:
        logger.exception("Transcription proxy failed")
        raise HTTPException(status_code=500, detail="Transcription failed.")


@router.get("/transcribe/artifacts/{artifact_id}/{stem}")
async def proxy_artifact(artifact_id: str, stem: str) -> StreamingResponse:
    """Stream Whisper artifacts through the same-origin AI backend."""
    try:
        parsed = uuid.UUID(artifact_id)
        if str(parsed) != artifact_id:
            raise ValueError
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid artifact id.") from exc
    if stem not in {"vocals", "background"}:
        raise HTTPException(status_code=422, detail="Unsupported artifact stem.")

    client = httpx.AsyncClient(timeout=300)
    stream_context = client.stream(
        "GET",
        f"{settings.WHISPER_SERVICE_URL}/artifacts/{artifact_id}/{stem}",
    )
    try:
        response = await stream_context.__aenter__()
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Artifact not found.")
        response.raise_for_status()
    except httpx.ConnectError as exc:
        await client.aclose()
        raise HTTPException(status_code=503, detail="Whisper service is not available.") from exc
    except httpx.HTTPStatusError as exc:
        await client.aclose()
        raise HTTPException(status_code=exc.response.status_code, detail="Artifact download failed.") from exc
    except Exception:
        await client.aclose()
        raise

    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() in {"content-length", "content-type", "content-disposition"}
    }
    headers.setdefault("content-type", "audio/mpeg")

    async def iterator():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await stream_context.__aexit__(None, None, None)
            await client.aclose()

    return StreamingResponse(iterator(), media_type=headers.pop("content-type", "audio/mpeg"), headers=headers)


# ---------------------------------------------------------------------------
# Subtitle generation (stays local -- no heavy deps)
# ---------------------------------------------------------------------------

class SubtitleSegment(BaseModel):
    """A single transcription segment."""

    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    text: str = Field(..., description="Segment text")


class SubtitleRequest(BaseModel):
    """Request body for subtitle generation."""

    segments: list[SubtitleSegment] = Field(..., description="Transcription segments")
    format: str = Field(
        default="srt",
        description="Subtitle format: srt, vtt, or ass",
    )
    max_chars_per_line: int = Field(
        default=42,
        description="Maximum characters per subtitle line before wrapping",
        ge=10,
        le=120,
    )
    style: dict | None = Field(
        default=None,
        description="Optional style settings for ASS format (font_name, font_size, primary_color, etc.)",
    )


@router.post("/transcribe/subtitles")
async def generate_subtitles(request: SubtitleRequest) -> dict:
    """Generate subtitles from transcription segments in SRT, VTT, or ASS format.

    Accepts segments (typically from the /api/transcribe endpoint) and converts
    them to the requested subtitle format.
    """
    from app.services.subtitle_service import segments_to_ass, segments_to_srt, segments_to_vtt

    segments = [seg.model_dump() for seg in request.segments]
    fmt = request.format.lower().strip()

    if fmt == "srt":
        content = segments_to_srt(segments, max_chars=request.max_chars_per_line)
        media_type = "application/x-subrip"
        filename = "subtitles.srt"
    elif fmt == "vtt":
        content = segments_to_vtt(segments, max_chars=request.max_chars_per_line)
        media_type = "text/vtt"
        filename = "subtitles.vtt"
    elif fmt == "ass":
        content = segments_to_ass(segments, style=request.style)
        media_type = "text/x-ssa"
        filename = "subtitles.ass"
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported subtitle format '{fmt}'. Use: srt, vtt, or ass.",
        )

    return {
        "format": fmt,
        "filename": filename,
        "media_type": media_type,
        "content": content,
    }
