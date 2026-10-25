import tempfile
import unittest
from pathlib import Path

from jarvis.config.credentials import (
    AzureCredentials,
    GeminiCredentials,
    VentoCredentials,
    load_azure_credentials,
    load_gemini_credentials,
    load_vento_credentials,
)


class CredentialsTest(unittest.TestCase):
    def write_env(self, content: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "private.env"
        path.write_text(content, encoding="utf-8")
        return path

    def test_loads_azure_credentials(self) -> None:
        path = self.write_env("AZURE_SPEECH_KEY=k\nAZURE_SPEECH_REGION=westeurope\n")

        self.assertEqual(load_azure_credentials(path), AzureCredentials("k", "westeurope"))

    def test_azure_requires_key_and_region(self) -> None:
        path = self.write_env("AZURE_SPEECH_KEY=k\n")

        with self.assertRaisesRegex(
            RuntimeError, "azure.env debe contener AZURE_SPEECH_KEY y AZURE_SPEECH_REGION"
        ):
            load_azure_credentials(path)

    def test_gemini_uses_the_model_from_the_file(self) -> None:
        path = self.write_env("GEMINI_API_KEY=g\nGEMINI_MODEL=custom-model\n")

        self.assertEqual(
            load_gemini_credentials(path, "default-model"), GeminiCredentials("g", "custom-model")
        )

    def test_gemini_falls_back_to_the_default_model(self) -> None:
        path = self.write_env("GEMINI_API_KEY=g\n")

        self.assertEqual(
            load_gemini_credentials(path, "default-model"), GeminiCredentials("g", "default-model")
        )

    def test_gemini_requires_api_key(self) -> None:
        path = self.write_env("GEMINI_MODEL=m\n")

        with self.assertRaisesRegex(RuntimeError, "gemini.env debe contener GEMINI_API_KEY"):
            load_gemini_credentials(path, "default-model")

    def test_loads_vento_credentials(self) -> None:
        path = self.write_env("BRIDGE_URL=https://vento.test/bridge\nBRIDGE_TOKEN=t\n")

        self.assertEqual(
            load_vento_credentials(path), VentoCredentials("https://vento.test/bridge", "t")
        )

    def test_vento_requires_url_and_token(self) -> None:
        path = self.write_env("BRIDGE_URL=https://vento.test/bridge\n")

        with self.assertRaisesRegex(
            RuntimeError, "state/bridge.env debe contener BRIDGE_URL y BRIDGE_TOKEN"
        ):
            load_vento_credentials(path)


if __name__ == "__main__":
    unittest.main()
