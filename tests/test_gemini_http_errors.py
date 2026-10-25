from io import BytesIO
import unittest
from unittest.mock import patch
import urllib.error

from bridge.gemini_bridge import GeminiBridge
from config.settings import GeminiCredentials


class GeminiHttpErrorTest(unittest.TestCase):
    def test_http_error_includes_google_error_message(self) -> None:
        error_body = b'{"error":{"message":"The model is overloaded."}}'
        http_error = urllib.error.HTTPError(
            url="https://example.invalid",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=BytesIO(error_body),
        )
        bridge = GeminiBridge(
            GeminiCredentials(api_key="test-key", model="configured-model"),
            history_limit=1,
            include_system_prompt=False,
        )

        with patch("urllib.request.urlopen", side_effect=http_error):
            with self.assertRaisesRegex(RuntimeError, "503.*The model is overloaded"):
                bridge.ask("Hola", [])


if __name__ == "__main__":
    unittest.main()