import importlib.metadata
import unittest


class TorchCompatibilityTest(unittest.TestCase):
    def test_torch_and_torchaudio_share_major_minor_version(self):
        torch_version = importlib.metadata.version("torch").split("+")[0]
        torchaudio_version = importlib.metadata.version("torchaudio").split("+")[0]

        self.assertEqual(torch_version.split(".")[:2], torchaudio_version.split(".")[:2])


if __name__ == "__main__":
    unittest.main()
