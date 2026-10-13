import unittest
from unittest.mock import Mock, patch

from bridge.gemini_bridge import create_configured_gemini_bridge
from config import settings
from config.settings import GeminiCredentials


class GeminiBridgeFactoryTest(unittest.TestCase):
    def test_factory_uses_configured_model_and_shared_timeout(self) -> None:
        credentials = GeminiCredentials(api_key="test-key", model="redirected-model")
        with patch(
            "bridge.gemini_bridge.settings.load_gemini_credentials",
            return_value=credentials,
        ), patch("bridge.gemini_bridge.GeminiBridge", return_value=Mock()) as bridge:
            create_configured_gemini_bridge(history_limit=1, include_system_prompt=False)

        self.assertEqual(bridge.call_args.kwargs["credentials"], credentials)
        self.assertEqual(bridge.call_args.kwargs["credentials"].model, "redirected-model")
        self.assertEqual(
            bridge.call_args.kwargs["timeout_seconds"],
            settings.GEMINI_TIMEOUT_SECONDS,
        )
        self.assertFalse(bridge.call_args.kwargs["include_system_prompt"])


if __name__ == "__main__":
    unittest.main()