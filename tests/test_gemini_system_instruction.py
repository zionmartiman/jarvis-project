import unittest
from pathlib import Path

from bridge.gemini_bridge import GeminiBridge
from config.settings import GeminiCredentials


class GeminiSystemInstructionTest(unittest.TestCase):
    def test_build_request_payload_includes_system_instruction(self) -> None:
        system_prompt = Path("system.md")
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


if __name__ == "__main__":
    unittest.main()
