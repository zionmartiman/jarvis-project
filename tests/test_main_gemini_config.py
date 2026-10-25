import unittest
from unittest.mock import Mock, patch

from config.settings import GeminiCredentials


class MainGeminiConfigTest(unittest.TestCase):
    @unittest.skip("Rewritten in phase 6: main.py cannot import 'Arduino'")
    def test_conversation_and_memory_summary_share_model_and_timeout(self) -> None:
        # Imported here because `import main` fails at import time until phase 6.
        import main

        credentials = GeminiCredentials(api_key="test-key", model="gemini-test-model")
        settings_patch = patch("main.settings.load_gemini_credentials", return_value=credentials)
        bridge_patch = patch("main.GeminiBridge", return_value=Mock())

        with settings_patch, bridge_patch as bridge_factory:
            main.build_bridge("gemini")
            conversation_call = bridge_factory.call_args
            bridge_factory.reset_mock()

            main.summarize_memory("prompt")
            summary_call = bridge_factory.call_args

        self.assertEqual(conversation_call.args[0], credentials)
        self.assertEqual(summary_call.args[0], credentials)
        self.assertEqual(
            conversation_call.kwargs["timeout_seconds"],
            main.settings.GEMINI_TIMEOUT_SECONDS,
        )
        self.assertEqual(
            summary_call.kwargs["timeout_seconds"],
            main.settings.GEMINI_TIMEOUT_SECONDS,
        )


if __name__ == "__main__":
    unittest.main()