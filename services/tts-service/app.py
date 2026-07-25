"""TTS (Text-to-Speech) microservice.

Standalone FastAPI service for voice generation with OmniVoice.
Runs on port 8422.
"""

import logging
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration via environment variables
# ---------------------------------------------------------------------------
TTS_MODEL = os.getenv("TTS_MODEL", "omnivoice")
OMNIVOICE_MODEL = os.getenv("OMNIVOICE_MODEL", "k2-fsa/OmniVoice")
GENERATED_DIR = os.getenv("GENERATED_DIR", "generated")
VOICES_DIR = os.path.join(GENERATED_DIR, "voices")

os.makedirs(GENERATED_DIR, exist_ok=True)
os.makedirs(VOICES_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Available TTS models
# ---------------------------------------------------------------------------

AVAILABLE_TTS_MODELS = [
    {
        "name": "omnivoice",
        "full_name": OMNIVOICE_MODEL,
        "description": "600+ languages with voice cloning and voice design",
        "size": "~2.5 GB",
        "size_mb": 2500,
        "multilingual": True,
        "voice_cloning": True,
        "languages": 600,
        "device": "cpu",
    },
]

# Quick lookup
_MODEL_MAP = {m["name"]: m for m in AVAILABLE_TTS_MODELS}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TTSGenerateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="Text to speak")
    language: str = Field(default="en", description="Language code")
    speaker_wav: str | None = Field(
        default=None, description="Path to reference speaker WAV for voice cloning"
    )
    speaker: str | None = Field(
        default=None, description="Built-in speaker name (e.g., 'male', 'female')"
    )
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speech speed")


# ---------------------------------------------------------------------------
# TTS service singleton
# ---------------------------------------------------------------------------

class TTSService:
    """Text-to-speech generation service with multi-model support."""

    _instance: "TTSService | None" = None
    _model = None
    _model_name: str = ""

    def __new__(cls) -> "TTSService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def device(self) -> str:
        """Return the device the model is running on."""
        if self._model is None:
            return "cpu"
        try:
            if hasattr(self._model, "device"):
                return str(self._model.device)
        except Exception:
            pass
        return "cpu"

    def load_model(self, model_name: str | None = None) -> dict:
        """Load a TTS model by name. Returns status dict."""
        target = model_name or TTS_MODEL

        # If same model already loaded, skip
        if self._model is not None and self._model_name == target:
            return {"status": "already_loaded", "model": self._model_name}

        try:
            from omnivoice import OmniVoice
        except ImportError:
            msg = "omnivoice is not installed. Install with: pip install omnivoice"
            logger.warning(msg)
            return {"status": "not_installed", "error": msg, "install_command": "pip install omnivoice"}

        # Unload current model if switching
        if self._model is not None:
            self.unload_model()

        full_name = _MODEL_MAP.get(target, {}).get("full_name", target)
        if target == "omnivoice":
            full_name = OMNIVOICE_MODEL

        try:
            logger.info("Loading TTS model '%s' (%s)...", target, full_name)
            import torch

            if torch.cuda.is_available():
                device_map = "cuda:0"
                dtype = torch.float16
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device_map = "mps"
                dtype = torch.float16
            else:
                device_map = "cpu"
                dtype = torch.float32

            self._model = OmniVoice.from_pretrained(
                full_name,
                device_map=device_map,
                dtype=dtype,
            )
            self._model_name = target
            logger.info("OmniVoice model loaded on %s.", device_map)

            return {"status": "loaded", "model": target}
        except Exception as e:
            logger.exception("Failed to load TTS model '%s'", target)
            return {"status": "error", "error": str(e)}

    def unload_model(self) -> None:
        if self._model is not None:
            logger.info("Unloading TTS model '%s'...", self._model_name)
            del self._model
            self._model = None
            self._model_name = ""
            logger.info("TTS model unloaded.")

    @property
    def is_installed(self) -> bool:
        try:
            import omnivoice  # noqa: F401
            return True
        except ImportError:
            return False

    def _build_generation_kwargs(
        self,
        text: str,
        language: str,
        speaker_wav: str | None,
        speaker: str | None,
        speed: float,
    ) -> dict:
        """Map the existing API request fields to OmniVoice generation modes."""
        kwargs = {
            "text": text,
            "language": "zh" if language == "zh-cn" else language,
            "speed": speed,
        }
        if speaker_wav:
            kwargs["ref_audio"] = speaker_wav
        elif speaker:
            kwargs["instruct"] = speaker
        return kwargs

    def _write_audio(self, audio, output_path: str) -> None:
        """Write an OmniVoice waveform using the loaded model's sample rate."""
        import soundfile as sf

        sf.write(output_path, audio, self._model.sampling_rate)

    def _generate_sync(
        self,
        text: str,
        language: str,
        speaker_wav: str | None,
        speaker: str | None,
        speed: float,
        output_path: str,
    ) -> None:
        """Synchronous OmniVoice generation — runs in a thread pool."""
        import gc

        try:
            generation_kwargs = self._build_generation_kwargs(
                text=text,
                language=language,
                speaker_wav=speaker_wav,
                speaker=speaker,
                speed=speed,
            )
            audio = self._model.generate(**generation_kwargs)
            if not audio:
                raise RuntimeError("OmniVoice returned no audio")
            self._write_audio(audio[0], output_path)
        except (MemoryError, RuntimeError) as exc:
            # Free memory and re-raise with a clear message
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
            raise MemoryError(
                "Out of memory during TTS generation. "
                "Try shorter text or allocate more RAM to Docker."
            ) from exc
        finally:
            gc.collect()

    async def generate_speech(
        self,
        text: str,
        language: str = "en",
        speaker_wav: str | None = None,
        speaker: str | None = None,
        speed: float = 1.0,
    ) -> str:
        if not self.is_loaded:
            result = self.load_model()
            if result["status"] not in ("loaded", "already_loaded"):
                raise NotImplementedError(result.get("error", "TTS model not available"))

        import uuid
        import asyncio
        output_path = os.path.join(GENERATED_DIR, f"tts_{uuid.uuid4().hex[:8]}.wav")

        # Run CPU-bound TTS in a thread so health checks remain responsive
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self._generate_sync,
            text,
            language,
            speaker_wav,
            speaker,
            speed,
            output_path,
        )
        return output_path


tts_service = TTSService()

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="OpenCutAI TTS Service", version="1.0.0")

AUTOLOAD = os.getenv("TTS_AUTOLOAD", "true").lower() in ("true", "1", "yes")


@app.on_event("startup")
async def _startup_load_model():
    """Auto-load TTS model on startup so it survives crash-restarts."""
    if not AUTOLOAD:
        return
    if not tts_service.is_installed:
        logger.warning("omnivoice not installed — skipping autoload")
        return
    logger.info("Auto-loading OmniVoice model on startup...")
    result = tts_service.load_model()
    logger.info("TTS autoload result: %s", result.get("status"))


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3100",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPPORTED_LANGUAGES = [
    "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl",
    "cs", "ar", "zh-cn", "ja", "hu", "ko",
]


@app.get("/health")
async def health():
    """Return service health and model status."""
    installed = tts_service.is_installed

    return {
        "status": "ok",
        "service": "tts",
        "model": {
            "loaded": tts_service.is_loaded,
            "model_name": tts_service.model_name if tts_service.is_loaded else None,
            "installed": installed,
            "device": tts_service.device if tts_service.is_loaded else None,
        },
        "install_command": "pip install omnivoice" if not installed else None,
        "supported_languages": SUPPORTED_LANGUAGES,
    }


@app.get("/models")
async def list_models():
    """List available TTS models with metadata."""
    active = tts_service.model_name if tts_service.is_loaded else None
    device = tts_service.device if tts_service.is_loaded else "cpu"
    models = []
    for m in AVAILABLE_TTS_MODELS:
        is_active = m["name"] == active
        models.append({
            **m,
            "active": is_active,
            # Override device with actual runtime device for active model
            "device": device if is_active else m["device"],
        })
    return {"models": models, "active_model": active, "device": device}


@app.post("/test")
async def test_model():
    """Quick test: generate a short phrase to verify the model works."""
    if not tts_service.is_loaded:
        raise HTTPException(status_code=400, detail="No model loaded. Load a model first.")

    try:
        output_path = await tts_service.generate_speech(
            text="Test successful.",
            language="en",
        )
        # Clean up the test file
        if os.path.exists(output_path):
            os.remove(output_path)

        return {
            "status": "ok",
            "model": tts_service.model_name,
            "device": tts_service.device,
            "message": f"Model '{tts_service.model_name}' is working correctly.",
        }
    except Exception as e:
        logger.exception("TTS test failed")
        raise HTTPException(status_code=500, detail=f"Test failed: {e}")


@app.post("/generate")
async def generate_speech(request: TTSGenerateRequest):
    """Generate speech audio from text."""
    try:
        output_path = await tts_service.generate_speech(
            text=request.text,
            language=request.language,
            speaker_wav=request.speaker_wav,
            speaker=request.speaker,
            speed=request.speed,
        )
        from fastapi.responses import FileResponse
        return FileResponse(
            path=output_path,
            media_type="audio/wav",
            filename="tts_output.wav",
        )
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except MemoryError as e:
        logger.error("OOM during TTS: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Out of memory during speech generation. "
            "Try shorter text or allocate more RAM to Docker.",
        )
    except Exception:
        logger.exception("TTS generation failed")
        raise HTTPException(status_code=500, detail="TTS generation failed.")


@app.post("/clone-voice")
async def clone_voice(
    name: str = Form(...),
    file: UploadFile = File(...),
):
    """Upload a reference audio file for voice cloning."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    ext = Path(file.filename).suffix.lower()
    if ext not in {".wav", ".mp3", ".flac", ".ogg"}:
        raise HTTPException(
            status_code=400,
            detail="Unsupported audio format. Use WAV, MP3, FLAC, or OGG.",
        )

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    voice_path = os.path.join(VOICES_DIR, f"{safe_name}{ext}")

    try:
        contents = await file.read()
        with open(voice_path, "wb") as f:
            f.write(contents)

        return {
            "status": "success",
            "name": name,
            "path": voice_path,
            "message": "Voice reference saved. Use the path with /generate.",
        }
    except Exception:
        logger.exception("Voice cloning upload failed")
        raise HTTPException(status_code=500, detail="Failed to save voice reference.")


@app.post("/load")
async def load_model(model_name: str | None = None):
    """Load a TTS model by name. Downloads on first use."""
    result = tts_service.load_model(model_name)

    if result["status"] == "not_installed":
        raise HTTPException(
            status_code=501,
            detail=result.get("error", "OmniVoice library not installed"),
        )
    if result["status"] == "error":
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to load model"),
        )

    return result


@app.post("/unload")
async def unload_model():
    """Unload the TTS model and free memory."""
    tts_service.unload_model()
    return {"status": "success", "message": "TTS model unloaded."}
