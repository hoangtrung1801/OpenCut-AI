from pathlib import Path
import unittest


SCRIPT = (Path(__file__).resolve().parents[1] / "start-local-services.sh").read_text()


class LocalServicesLauncherTest(unittest.TestCase):
    def test_launcher_waits_for_tts_before_starting_other_model_services(self):
        self.assertIn("wait_for_health", SCRIPT)
        tts_start = SCRIPT.index('start_service "tts-service"')
        tts_ready = SCRIPT.index('wait_for_health "tts-service"', tts_start)
        other_services_loop = SCRIPT.index('for spec in "${SERVICE_SPECS[@]}"', tts_ready)
        self.assertLess(tts_start, tts_ready)
        self.assertLess(tts_ready, other_services_loop)


if __name__ == "__main__":
    unittest.main()
