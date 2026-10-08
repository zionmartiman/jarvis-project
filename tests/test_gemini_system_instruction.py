import unittest
from pathlib import Path
import tempfile

from bridge.gemini_bridge import GeminiBridge
from config.settings import GeminiCredentials


class GeminiSystemInstructionTest(unittest.TestCase):
    def test_build_request_payload_includes_system_instruction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            system_prompt = Path(directory) / "system.md"
            system_prompt.write_text("Eres Jarvis, un asistente de hogar inteligente.", encoding="utf-8")
            bridge = GeminiBridge(
                GeminiCredentials(api_key="test-key", model="gemini-2.5-flash"),
                history_limit=10,
                system_prompt_path=system_prompt,
            )

            payload = bridge.build_request_payload("Hola", [{"role": "user", "text": "Mensaje previo"}])

            self.assertEqual(payload["systemInstruction"]["parts"][0]["text"], "Eres Jarvis, un asistente de hogar inteligente.")
            self.assertEqual(payload["contents"][-1]["role"], "user")
            self.assertEqual(payload["contents"][-1]["parts"][0]["text"], "Hola")

    def test_memory_summary_is_added_to_system_instruction_not_turn_window(self) -> None:
        bridge = GeminiBridge(
            GeminiCredentials(api_key="test-key", model="gemini-2.5-flash"),
            history_limit=11,
            include_system_prompt=False,
        )

        payload = bridge.build_request_payload(
            "¿Qué prefiero?",
            [
                {"role": "summary", "text": "Prefiere el té."},
                {"role": "user", "text": "Hola."},
                {"role": "assistant", "text": "Hola."},
            ],
        )

        self.assertEqual(payload["systemInstruction"]["parts"][0]["text"], "Memoria a largo plazo del usuario: Prefiere el té.")
        self.assertEqual([item["role"] for item in payload["contents"]], ["user", "model", "user"])


if __name__ == "__main__":
    unittest.main()
