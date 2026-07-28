import unittest
from pathlib import Path


class DeploymentContractTests(unittest.TestCase):
    def test_compose_persists_artifacts_and_configures_ai_callback(self):
        compose = Path(__file__).parents[2] / "../docker-compose.yml"
        content = compose.resolve().read_text()
        self.assertIn("whisper_artifacts:/artifacts", content)
        self.assertIn("AI_BACKEND_URL=http://ai-backend:8420", content)
        self.assertIn("whisper_artifacts:", content)

    def test_requirements_pin_whisperx_spacy_and_all_pipeline_wheels(self):
        requirements = (Path(__file__).parents[1] / "requirements.txt").read_text()
        for package in ("whisperx==3.8.5", "spacy==3.8.14", "xx_sent_ud_sm", "treetable==0.2.6"):
            self.assertIn(package, requirements)

        demucs = (Path(__file__).parents[1] / "requirements-demucs.txt").read_text()
        self.assertIn("demucs @ git+https://github.com/adefossez/demucs@b9ab48cad45976ba42b2ff17b229c071f0df9390", demucs)

    def test_demucs_imports_against_treetable_package_api(self):
        from demucs.pretrained import get_model
        from treetable.table import _Node

        self.assertTrue(callable(get_model))
        self.assertTrue(_Node)


if __name__ == "__main__":
    unittest.main()
