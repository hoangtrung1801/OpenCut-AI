"""Regression tests for TurboQuant OpenAI-provider routing."""

import unittest
from unittest.mock import AsyncMock, patch


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class FakeAsyncClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get(self, url: str):
        if url.endswith("/health"):
            return FakeResponse(
                {
                    "provider": "openai",
                    "provider_model": "gpt-4o-mini",
                    "openai_configured": True,
                    "active_model_loaded": False,
                }
            )
        return FakeResponse({"models": [{"name": "llama3.2:1b"}]})


class OpenAITurboQuantRoutingTests(unittest.IsolatedAsyncioTestCase):
    @patch("app.services.model_backend.httpx.AsyncClient", FakeAsyncClient)
    async def test_openai_provider_is_ready_without_local_model(self) -> None:
        from app.services.model_backend import LLMBackend

        backend = LLMBackend()
        self.assertTrue(await backend._is_turboquant_ready())

    async def test_openai_stream_path_yields_buffered_response(self) -> None:
        from app.services.model_backend import LLMBackend

        backend = LLMBackend()
        backend._tq_provider = "openai"
        backend._should_use_turboquant = AsyncMock(return_value=True)
        backend._tq_generate = AsyncMock(return_value="Complete response")

        tokens = [
            token
            async for token in backend._tq_generate_stream(
                prompt="Hello",
                model=None,
                system=None,
            )
        ]

        self.assertEqual(tokens, ["Complete response"])

    @patch("app.services.model_backend.httpx.AsyncClient", FakeAsyncClient)
    async def test_status_exposes_openai_provider_and_model(self) -> None:
        from app.services.model_backend import LLMBackend

        status = await LLMBackend().get_status()

        self.assertEqual(status["active_backend"], "turboquant")
        self.assertEqual(status["turboquant"]["provider"], "openai")
        self.assertEqual(status["turboquant"]["provider_model"], "gpt-4o-mini")
        self.assertTrue(status["turboquant"]["openai_configured"])

    async def test_llm_status_exposes_turboquant_provider_metadata(self) -> None:
        from app.routes.llm import llm_status

        backend_status = {
            "active_backend": "turboquant",
            "ollama": {"available": False, "url": "http://ollama", "models": []},
            "turboquant": {
                "available": True,
                "url": "http://turboquant",
                "active_model": None,
                "provider": "openai",
                "provider_model": "gpt-4o-mini",
                "openai_configured": True,
                "kv_cache_bits": 4,
            },
        }
        with patch(
            "app.routes.llm.llm_backend.get_status",
            return_value=backend_status,
        ), patch.object(
            __import__("app.routes.llm", fromlist=["ollama_service"]).ollama_service,
            "default_model",
            "llama3.2:1b",
        ):
            result = await llm_status()

        self.assertEqual(result["provider"], "openai")
        self.assertEqual(result["provider_model"], "gpt-4o-mini")
        self.assertTrue(result["openai_configured"])
        self.assertEqual(result["models"], [{"name": "gpt-4o-mini", "provider": "openai"}])

    @patch("app.services.turboquant_service.httpx.AsyncClient", FakeAsyncClient)
    async def test_turboquant_service_status_preserves_provider_metadata(self) -> None:
        from app.services.turboquant_service import TurboQuantService

        result = await TurboQuantService().get_service_status()

        self.assertTrue(result["available"])
        self.assertEqual(result["provider"], "openai")
        self.assertEqual(result["provider_model"], "gpt-4o-mini")
        self.assertTrue(result["openai_configured"])


if __name__ == "__main__":
    unittest.main()
