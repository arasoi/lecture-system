import importlib
import sys
import types
import unittest
from unittest.mock import patch


class LoadWhisperModelTests(unittest.TestCase):
    def test_cuda_falls_back_to_cpu_when_cuda_unavailable(self):
        fake_torch = types.SimpleNamespace(
            cuda=types.SimpleNamespace(is_available=lambda: False)
        )
        fake_whisper = types.SimpleNamespace(
            load_model=lambda model_name, device=None: {
                "model_name": model_name,
                "device": device,
            }
        )

        with patch.dict(sys.modules, {"torch": fake_torch, "whisper": fake_whisper}):
            import lecture_transcriber.transcribe as transcribe

            importlib.reload(transcribe)
            model = transcribe.load_whisper_model("base", device="cuda")

            self.assertEqual(model["device"], "cpu")


if __name__ == "__main__":
    unittest.main()
