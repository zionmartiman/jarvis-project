import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from jarvis.bootstrap.assistants import (
    build_assistant,
    build_graph_extractor,
    build_memory_summarizer,
)
from jarvis.config.credentials import GeminiCredentials
from jarvis.config.settings import load_settings
from jarvis.domain.assistant_model import AssistantModel
from jarvis.domain.conversation import ChatMessage, ConversationContext, Role
from jarvis.infrastructure.assistants.gemini import GeminiAssistant
from jarvis.infrastructure.assistants.vento import VentoAssistant
from jarvis.infrastructure.knowledge.gemini_extractor import GRAPH_DELTA_SCHEMA

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class BuildAssistantTest(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.base = Path(self._directory.name)
        self.gemini_env = self.base / "gemini.env"
        self.gemini_env.write_text("GEMINI_API_KEY=test-key\nGEMINI_MODEL=gemini-test-model\n")
        self.bridge_env = self.base / "bridge.env"
        self.bridge_env.write_text("BRIDGE_URL=https://vento.test/bridge\nBRIDGE_TOKEN=secret\n")
        self.prompt = self.base / "system.md"
        self.prompt.write_text("  Eres Jarvis.\n", encoding="utf-8")

        defaults = load_settings(self.base)
        self.settings = replace(
            defaults,
            gemini=replace(
                defaults.gemini,
                credentials_path=self.gemini_env,
                system_prompt_path=self.prompt,
            ),
            vento=replace(defaults.vento, credentials_path=self.bridge_env),
        )

    def test_gemini_uses_the_configured_model_prompt_and_memory_window(self) -> None:
        with patch("jarvis.bootstrap.assistants.GeminiAssistant") as assistant_class:
            build_assistant(AssistantModel.GEMINI, self.settings)

        credentials, history_limit, timeout, system_prompt = assistant_class.call_args.args
        self.assertEqual(credentials, GeminiCredentials("test-key", "gemini-test-model"))
        self.assertEqual(history_limit, 11)
        self.assertEqual(timeout, 130)
        self.assertEqual(system_prompt, "Eres Jarvis.")

    def test_gemini_without_a_prompt_file_uses_an_empty_prompt(self) -> None:
        self.prompt.unlink()
        assistant = build_assistant(AssistantModel.GEMINI, self.settings)

        payload = assistant.build_request_payload("Hola", ConversationContext())

        self.assertNotIn("systemInstruction", payload)

    def test_gemini_default_model_applies_when_the_env_file_has_none(self) -> None:
        self.gemini_env.write_text("GEMINI_API_KEY=test-key\n")

        with patch("jarvis.bootstrap.assistants.GeminiAssistant") as assistant_class:
            build_assistant(AssistantModel.GEMINI, self.settings)

        self.assertEqual(assistant_class.call_args.args[0].model, "gemini-2.5-flash")

    def test_vento_keeps_the_last_six_messages_of_the_short_term_history(self) -> None:
        assistant = build_assistant(AssistantModel.VENTO, self.settings)
        context = ConversationContext(
            messages=tuple(ChatMessage(Role.USER, f"mensaje {n}") for n in range(10)),
            summary="nunca se envía",
        )
        sent: list[bytes] = []

        def fake_urlopen(request, timeout):
            sent.append(request.data)
            response = Mock()
            response.__enter__ = lambda self_: response
            response.__exit__ = lambda self_, *args: False
            response.read.return_value = b"hola"
            response.headers.get.return_value = "text/plain"
            return response

        with patch("urllib.request.urlopen", fake_urlopen):
            assistant.ask("hola", context)

        history = json.loads(sent[0])["history"]
        self.assertIsInstance(assistant, VentoAssistant)
        self.assertEqual([item["text"] for item in history], [f"mensaje {n}" for n in range(4, 10)])

    def test_vento_credentials_are_only_read_when_vento_is_built(self) -> None:
        self.bridge_env.unlink()

        build_assistant(AssistantModel.GEMINI, self.settings)
        with self.assertRaises(RuntimeError):
            build_assistant(AssistantModel.VENTO, self.settings)


class BuildMemorySummarizerTest(unittest.TestCase):
    def test_summary_uses_the_same_model_and_timeout_without_the_system_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "gemini.env").write_text("GEMINI_API_KEY=test-key\nGEMINI_MODEL=gemini-test\n")
            defaults = load_settings(base)
            settings = replace(
                defaults,
                gemini=replace(defaults.gemini, credentials_path=base / "gemini.env"),
            )
            assistant = Mock()
            assistant.ask.return_value = "resumen"

            with patch("jarvis.bootstrap.assistants.GeminiAssistant", return_value=assistant) as cls:
                reply = build_memory_summarizer(settings)("prompt")

        credentials, history_limit, timeout, system_prompt = cls.call_args.args
        self.assertEqual(credentials, GeminiCredentials("test-key", "gemini-test"))
        self.assertEqual((history_limit, timeout, system_prompt), (1, 130, ""))
        assistant.ask.assert_called_once_with("prompt", ConversationContext())
        self.assertEqual(reply, "resumen")


class BuildGraphExtractorTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        self.gemini_env = base / "gemini.env"
        self.gemini_env.write_text("GEMINI_API_KEY=test-key\nGEMINI_MODEL=gemini-chat\n")
        defaults = load_settings(base)
        self.settings = replace(
            defaults, gemini=replace(defaults.gemini, credentials_path=self.gemini_env)
        )

    def extract(self, settings, reply: str = '{"entities": []}'):
        assistant = Mock()
        assistant.ask.return_value = reply
        with patch("jarvis.bootstrap.assistants.GeminiAssistant", return_value=assistant) as cls:
            delta = build_graph_extractor(settings).extract("prompt")
        assistant.ask.assert_called_once_with("prompt", ConversationContext())
        return cls.call_args, delta

    def test_json_schema_without_system_prompt_and_the_gemini_env_model(self) -> None:
        call, delta = self.extract(self.settings)

        credentials, history_limit, timeout, system_prompt = call.args
        self.assertEqual(credentials, GeminiCredentials("test-key", "gemini-chat"))
        self.assertEqual((history_limit, timeout, system_prompt), (1, 130, ""))
        self.assertEqual(
            call.kwargs["generation_config"],
            {"responseMimeType": "application/json", "responseSchema": GRAPH_DELTA_SCHEMA},
        )
        self.assertTrue(delta.is_empty)

    def test_extraction_model_and_thinking_override_the_defaults(self) -> None:
        settings = replace(
            self.settings,
            knowledge=replace(
                self.settings.knowledge,
                extraction_model="gemini-extract",
                extraction_thinking={"thinkingBudget": 0},
            ),
        )

        call, _ = self.extract(settings)

        self.assertEqual(call.args[0].model, "gemini-extract")
        self.assertEqual(call.kwargs["generation_config"]["thinkingConfig"], {"thinkingBudget": 0})

    def test_credentials_are_read_on_each_extraction_not_when_built(self) -> None:
        self.gemini_env.unlink()
        extractor = build_graph_extractor(self.settings)

        with self.assertRaisesRegex(RuntimeError, "gemini.env"):
            extractor.extract("prompt")

    def test_the_real_request_carries_the_schema(self) -> None:
        sent: list[dict] = []

        def fake_urlopen(request, timeout):
            sent.append(json.loads(request.data))
            body = {"candidates": [{"content": {"parts": [{"text": '{"entities": []}'}]}}]}
            response = Mock()
            response.__enter__ = lambda self_: response
            response.__exit__ = lambda self_, *args: False
            response.read.return_value = json.dumps(body).encode("utf-8")
            return response

        with patch("urllib.request.urlopen", fake_urlopen):
            build_graph_extractor(self.settings).extract("prompt")

        self.assertNotIn("systemInstruction", sent[0])
        self.assertEqual(sent[0]["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(sent[0]["generationConfig"]["temperature"], 0.7)


class SystemPromptFileTest(unittest.TestCase):
    def test_the_default_prompt_lives_in_prompts_and_keeps_memory_topics_separate(self) -> None:
        settings = load_settings()
        self.assertEqual(settings.gemini.system_prompt_path, PROJECT_ROOT / "prompts" / "system.md")

        prompt = settings.gemini.system_prompt_path.read_text(encoding="utf-8")

        self.assertIn("trata cada sección como un concepto independiente", prompt)
        self.assertIn("No mezcles temas diferentes", prompt)
        self.assertIn("si hay duda, conserva ambos por separado", prompt)

    def test_the_prompt_reaches_the_gemini_system_instruction(self) -> None:
        settings = load_settings()
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "gemini.env"
            env.write_text("GEMINI_API_KEY=test-key\n")
            settings = replace(settings, gemini=replace(settings.gemini, credentials_path=env))

            assistant = build_assistant(AssistantModel.GEMINI, settings)

        self.assertIsInstance(assistant, GeminiAssistant)
        instruction = assistant.build_request_payload("Hola", ConversationContext())
        self.assertIn("Jarvis", instruction["systemInstruction"]["parts"][0]["text"])


if __name__ == "__main__":
    unittest.main()
