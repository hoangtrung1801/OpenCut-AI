import unittest

from models import WordToken
from semantic_client import SemanticClient, SemanticSegmentationError
from settings import Settings


def make_words(count):
    return [
        WordToken(f" w{i}", f"w{i}", float(i), float(i + 1), 0.9, 0, -0.1, 0.01)
        for i in range(count)
    ]


class FakeTransport:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.call_count = 0
        self.payloads = []

    def __call__(self, payload):
        self.call_count += 1
        self.payloads.append(payload)
        if self.error:
            raise self.error
        return self.responses.pop(0)


class SemanticClientTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings.from_env({"SEMANTIC_MAX_RETRIES": "3"})
        self.words = make_words(21)
        self.candidates = [8, 17]

    def test_valid_indexes_split_without_changing_words(self):
        transport = FakeTransport([{"split_after": [8, 17]}])
        client = SemanticClient(self.settings, transport=transport)
        parts = client.split(self.words, "en", self.candidates)
        self.assertEqual([len(part) for part in parts], [9, 9, 3])
        self.assertEqual([word.word for part in parts for word in part], [word.word for word in self.words])

    def test_invalid_boundaries_retry_three_times_then_fail(self):
        transport = FakeTransport([
            {"split_after": [99]},
            {"split_after": [1, 1]},
            {"split_after": []},
        ])
        client = SemanticClient(self.settings, transport=transport)
        with self.assertRaises(SemanticSegmentationError):
            client.split(self.words, "en", [])
        self.assertEqual(transport.call_count, 3)
        self.assertIn("previous_error", transport.payloads[1])

    def test_connection_failure_is_not_a_deterministic_fallback(self):
        transport = FakeTransport(error=TimeoutError())
        client = SemanticClient(self.settings, transport=transport)
        with self.assertRaises(SemanticSegmentationError):
            client.split(self.words, "en", [])
        self.assertEqual(transport.call_count, 1)

    def test_long_input_is_partitioned_into_lossless_windows(self):
        words = make_words(65)
        transport = FakeTransport([
            {"split_after": [19, 39]},
            {"split_after": []},
        ])
        client = SemanticClient(self.settings, transport=transport)
        parts = client.split(words, "en", [19, 39, 59])
        self.assertEqual(sum(len(part) for part in parts), 65)
        self.assertEqual(len(transport.payloads[0]["words"]), 60)


if __name__ == "__main__":
    unittest.main()
