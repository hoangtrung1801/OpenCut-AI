import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SERVICE_DIR = Path(__file__).resolve().parents[1]


class DotenvConfigTests(unittest.TestCase):
    def test_app_reads_dotenv_before_loading_provider_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / ".env").write_text(
                "AI_PROVIDER=openai\nOPENAI_MODEL=dotenv-model\n",
                encoding="utf-8",
            )

            environment = os.environ.copy()
            for key in ("AI_PROVIDER", "OPENAI_MODEL", "MODEL_NAME"):
                environment.pop(key, None)
            environment["MODEL_DIR"] = str(temp_path / "models")
            environment["PYTHONPATH"] = str(SERVICE_DIR)

            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import app; print(f'{app.AI_PROVIDER}|{app.OPENAI_MODEL}')",
                ],
                cwd=temp_dir,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("openai|dotenv-model", result.stdout)


if __name__ == "__main__":
    unittest.main()
