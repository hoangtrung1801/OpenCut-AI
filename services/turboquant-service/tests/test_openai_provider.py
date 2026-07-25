import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))


class FakeCompletions:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.last_request = None

    def create(self, **kwargs):
        self.last_request = kwargs
        if self.error:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, completions):
        self.chat = SimpleNamespace(completions=completions)


class OpenAIProviderTests(unittest.TestCase):
    def _import_provider(self):
        try:
            from openai_provider import OpenAIProvider
        except ModuleNotFoundError as error:
            self.fail(f"OpenAI provider is not implemented yet: {error}")
        return OpenAIProvider

    def test_chat_generation_translates_request_and_usage(self):
        completions = FakeCompletions(
            response=SimpleNamespace(
                model="gpt-test",
                choices=[SimpleNamespace(message=SimpleNamespace(content="Hello!"))],
                usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3, total_tokens=10),
            )
        )

        OpenAIProvider = self._import_provider()
        result = OpenAIProvider(
            client=FakeClient(completions),
            default_model="gpt-default",
        ).generate_chat(
            messages=[{"role": "user", "content": "Hi"}],
            model=None,
            max_tokens=64,
            temperature=0.4,
            top_p=0.8,
        )

        self.assertEqual(
            completions.last_request,
            {
                "model": "gpt-default",
                "messages": [{"role": "user", "content": "Hi"}],
                "max_completion_tokens": 64,
                "temperature": 0.4,
                "top_p": 0.8,
                "stream": False,
            },
        )
        self.assertEqual(result["response_text"], "Hello!")
        self.assertEqual(result["prompt_tokens"], 7)
        self.assertEqual(result["completion_tokens"], 3)
        self.assertEqual(result["total_tokens"], 10)
        self.assertEqual(result["model"], "gpt-test")

    def test_completion_generation_wraps_prompt_as_user_message(self):
        completions = FakeCompletions(
            response=SimpleNamespace(
                model="gpt-test",
                choices=[SimpleNamespace(message=SimpleNamespace(content="Done"))],
                usage=None,
            )
        )

        OpenAIProvider = self._import_provider()
        result = OpenAIProvider(
            client=FakeClient(completions),
            default_model="gpt-default",
        ).generate_completion(
            prompt="Write a title",
            model="gpt-override",
            max_tokens=12,
            temperature=0.0,
        )

        self.assertEqual(completions.last_request["model"], "gpt-override")
        self.assertEqual(
            completions.last_request["messages"],
            [{"role": "user", "content": "Write a title"}],
        )
        self.assertEqual(completions.last_request["top_p"], 1.0)
        self.assertEqual(result["response_text"], "Done")
        self.assertEqual(result["prompt_tokens"], 0)
        self.assertEqual(result["completion_tokens"], 0)

    def test_gpt_5_family_models_use_completion_token_limit(self):
        from openai_provider import OpenAIProvider

        for model in ("gpt-5.5", "gpt-5.6", "gpt-5.6-sol"):
            completions = FakeCompletions(
                response=SimpleNamespace(
                    model=model,
                    choices=[SimpleNamespace(message=SimpleNamespace(content="Done"))],
                    usage=None,
                )
            )

            OpenAIProvider(
                client=FakeClient(completions),
                default_model=model,
            ).generate_chat(
                messages=[{"role": "user", "content": "Hi"}],
                model=None,
                max_tokens=128,
                temperature=0.0,
                top_p=1.0,
            )

            self.assertEqual(completions.last_request["max_completion_tokens"], 128)
            self.assertNotIn("max_tokens", completions.last_request)

    def test_missing_api_key_fails_with_configuration_error(self):
        OpenAIProvider = self._import_provider()
        try:
            from openai_provider import OpenAIProviderConfigurationError
        except ModuleNotFoundError as error:
            self.fail(f"OpenAI provider errors are not implemented yet: {error}")

        with self.assertRaises(OpenAIProviderConfigurationError):
            OpenAIProvider(api_key=None, default_model="gpt-test").generate_chat(
                messages=[{"role": "user", "content": "Hi"}],
                model=None,
                max_tokens=1,
                temperature=0.0,
                top_p=1.0,
            )

    def test_upstream_failure_is_wrapped_without_changing_provider_contract(self):
        completions = FakeCompletions(error=RuntimeError("upstream failed"))

        OpenAIProvider = self._import_provider()
        try:
            from openai_provider import OpenAIProviderError
        except ModuleNotFoundError as error:
            self.fail(f"OpenAI provider errors are not implemented yet: {error}")

        with self.assertRaises(OpenAIProviderError) as context:
            OpenAIProvider(
                client=FakeClient(completions),
                default_model="gpt-test",
            ).generate_chat(
                messages=[{"role": "user", "content": "Hi"}],
                model=None,
                max_tokens=1,
                temperature=0.0,
                top_p=1.0,
            )

        self.assertIn("OpenAI request failed: upstream failed", str(context.exception))


if __name__ == "__main__":
    unittest.main()
