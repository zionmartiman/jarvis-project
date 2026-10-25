import json
import unittest
import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

from jarvis.config.credentials import GeminiCredentials
from jarvis.domain.conversation import ChatMessage, ConversationContext, Role
from jarvis.infrastructure.assistants.gemini import GeminiAssistant, GeminiHttpError

CREDENTIALS = GeminiCredentials(api_key="test-key", model="gemini-test")


def assistant(history_limit: int = 11, system_prompt: str = "") -> GeminiAssistant:
    return GeminiAssistant(CREDENTIALS, history_limit, timeout_seconds=9, system_prompt=system_prompt)


def reply_response(text: str) -> MagicMock:
    body = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    response = MagicMock()
    response.read.return_value = json.dumps(body).encode("utf-8")
    response.__enter__.return_value = response
    return response


class BuildRequestPayloadTest(unittest.TestCase):
    def test_system_prompt_goes_into_system_instruction(self) -> None:
        payload = assistant(system_prompt="Eres Jarvis.").build_request_payload(
            "Hola", ConversationContext()
        )

        self.assertEqual(payload["systemInstruction"]["parts"][0]["text"], "Eres Jarvis.")
        self.assertEqual(payload["contents"], [{"role": "user", "parts": [{"text": "Hola"}]}])
        self.assertEqual(payload["generationConfig"], {"temperature": 0.7})

    def test_no_system_instruction_without_prompt_or_summary(self) -> None:
        payload = assistant().build_request_payload("Hola", ConversationContext())

        self.assertNotIn("systemInstruction", payload)

    def test_summary_is_appended_to_the_system_prompt_not_the_turn_window(self) -> None:
        context = ConversationContext(
            messages=(ChatMessage(Role.USER, "Hola."), ChatMessage(Role.ASSISTANT, "Hola.")),
            summary="Prefiere el té.",
        )

        payload = assistant(system_prompt="Eres Jarvis.").build_request_payload("¿Qué prefiero?", context)

        self.assertEqual(
            payload["systemInstruction"]["parts"][0]["text"],
            "Eres Jarvis.\n\nMemoria a largo plazo del usuario: Prefiere el té.",
        )
        self.assertEqual([item["role"] for item in payload["contents"]], ["user", "model", "user"])

    def test_summary_alone_is_the_system_instruction(self) -> None:
        payload = assistant().build_request_payload(
            "Hola", ConversationContext(summary="Prefiere el té.")
        )

        self.assertEqual(
            payload["systemInstruction"]["parts"][0]["text"],
            "Memoria a largo plazo del usuario: Prefiere el té.",
        )

    def test_only_the_last_history_limit_messages_are_sent(self) -> None:
        messages = tuple(ChatMessage(Role.USER, str(index)) for index in range(5))

        payload = assistant(history_limit=2).build_request_payload(
            "Hola", ConversationContext(messages=messages)
        )

        self.assertEqual(
            [item["parts"][0]["text"] for item in payload["contents"]], ["3", "4", "Hola"]
        )

    def test_messages_without_text_are_skipped(self) -> None:
        context = ConversationContext(messages=(ChatMessage(Role.USER, ""),))

        payload = assistant().build_request_payload("Hola", context)

        self.assertEqual(len(payload["contents"]), 1)


class GenerationConfigTest(unittest.TestCase):
    def test_extra_generation_config_is_merged_with_the_temperature(self) -> None:
        extra = {"responseMimeType": "application/json", "responseSchema": {"type": "OBJECT"}}
        gemini = GeminiAssistant(CREDENTIALS, 1, generation_config=extra)

        payload = gemini.build_request_payload("Hola", ConversationContext())

        self.assertEqual(
            payload["generationConfig"],
            {
                "temperature": 0.7,
                "responseMimeType": "application/json",
                "responseSchema": {"type": "OBJECT"},
            },
        )

    def test_without_generation_config_the_payload_is_unchanged(self) -> None:
        for config in (None, {}):
            with self.subTest(config=config):
                gemini = GeminiAssistant(CREDENTIALS, 11, generation_config=config)

                payload = gemini.build_request_payload("Hola", ConversationContext())

                self.assertEqual(
                    payload,
                    {
                        "contents": [{"role": "user", "parts": [{"text": "Hola"}]}],
                        "generationConfig": {"temperature": 0.7},
                    },
                )

    def test_the_given_config_is_copied(self) -> None:
        extra = {"responseMimeType": "application/json"}
        gemini = GeminiAssistant(CREDENTIALS, 1, generation_config=extra)
        extra["responseMimeType"] = "text/plain"

        payload = gemini.build_request_payload("Hola", ConversationContext())

        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")


class AskTest(unittest.TestCase):
    def test_sends_the_request_to_the_configured_model_and_returns_the_reply(self) -> None:
        with patch("urllib.request.urlopen", return_value=reply_response("  Buenas.  ")) as urlopen:
            reply = assistant().ask("Hola", ConversationContext())

        request = urlopen.call_args.args[0]
        self.assertEqual(reply, "Buenas.")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 9)
        self.assertEqual(
            request.full_url,
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent",
        )
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("X-goog-api-key"), "test-key")
        self.assertEqual(
            json.loads(request.data.decode("utf-8"))["contents"][-1]["parts"][0]["text"], "Hola"
        )

    def test_http_error_includes_the_google_error_message(self) -> None:
        error = urllib.error.HTTPError(
            "https://example.invalid", 503, "Unavailable", None,
            BytesIO(b'{"error":{"message":"The model is overloaded."}}'),
        )

        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, r"\(503\): The model is overloaded"):
                assistant().ask("Hola", ConversationContext())

    def test_http_error_without_json_body_reports_only_the_code(self) -> None:
        error = urllib.error.HTTPError(
            "https://example.invalid", 500, "Error", None, BytesIO(b"not json")
        )

        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as raised:
                assistant().ask("Hola", ConversationContext())

        self.assertEqual(str(raised.exception), "Gemini no está disponible (500)")

    def test_http_error_keeps_its_status(self) -> None:
        error = urllib.error.HTTPError("https://example.invalid", 429, "Busy", None, BytesIO(b""))

        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(GeminiHttpError) as raised:
                assistant().ask("Hola", ConversationContext())

        self.assertIsInstance(raised.exception, RuntimeError)
        self.assertEqual(raised.exception.status, 429)
        self.assertEqual(str(raised.exception), "Gemini no está disponible (429)")

    def test_network_error_is_reported(self) -> None:
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("sin red")):
            with self.assertRaisesRegex(RuntimeError, "No se pudo contactar con Gemini: sin red"):
                assistant().ask("Hola", ConversationContext())

    def test_invalid_and_empty_replies_raise(self) -> None:
        for body, message in (
            ("no es json", "respuesta no válida"),
            ('{"candidates": []}', "respuesta no válida"),
            ('{"candidates":[{"content":{"parts":[{"text":"  "}]}}]}', "respuesta vacía"),
        ):
            with self.subTest(body=body):
                response = MagicMock()
                response.read.return_value = body.encode("utf-8")
                response.__enter__.return_value = response
                with patch("urllib.request.urlopen", return_value=response):
                    with self.assertRaisesRegex(RuntimeError, message):
                        assistant().ask("Hola", ConversationContext())


if __name__ == "__main__":
    unittest.main()
