import json
import unittest
import urllib.error
import urllib.parse
from io import BytesIO
from unittest.mock import MagicMock, patch

from jarvis.config.credentials import VentoCredentials
from jarvis.domain.conversation import ChatMessage, ConversationContext, Role
from jarvis.infrastructure.assistants.vento import VentoAssistant
from jarvis.infrastructure.assistants.vento_reply_parser import parse_vento_reply


def sse(*events: dict) -> str:
    return "\n\n".join(f"data: {json.dumps(event)}" for event in events)


class ParseVentoReplyTest(unittest.TestCase):
    def test_plain_text(self) -> None:
        self.assertEqual(parse_vento_reply("  Hola, señor.\n", "text/plain"), "Hola, señor.")

    def test_json_variants(self) -> None:
        cases = {
            "reply as string": {"reply": "uno"},
            "reply.content": {"reply": {"content": "uno"}},
            "reply.message": {"reply": {"message": "uno"}},
            "reply.text": {"reply": {"text": "uno"}},
            "message": {"message": "uno"},
            "content": {"content": "uno"},
            "text": {"text": "uno"},
        }
        for name, payload in cases.items():
            with self.subTest(name):
                self.assertEqual(parse_vento_reply(json.dumps(payload), "application/json"), "uno")

    def test_json_string_payload(self) -> None:
        self.assertEqual(parse_vento_reply(json.dumps("directo"), "application/json"), "directo")

    def test_json_without_text_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            parse_vento_reply(json.dumps({"reply": {}}), "application/json")

    def test_invalid_json_falls_back_to_the_body(self) -> None:
        self.assertEqual(parse_vento_reply("{no es json", "application/json"), "{no es json")

    def test_sse_uses_the_terminal_event(self) -> None:
        body = sse(
            {"type": "progress", "reply": {"content": "pensando"}},
            {"type": "completed", "reply": {"content": "respuesta final"}},
        )
        self.assertEqual(parse_vento_reply(body, "text/event-stream"), "respuesta final")

    def test_sse_is_detected_from_the_body_prefix(self) -> None:
        body = sse({"type": "completed", "reply": "sin cabecera"})
        self.assertEqual(parse_vento_reply(body, "text/plain"), "sin cabecera")

    def test_sse_failure_raises_with_the_message(self) -> None:
        body = sse({"type": "failed", "reply": {"content": "fallo del agente"}})
        with self.assertRaisesRegex(RuntimeError, "fallo del agente"):
            parse_vento_reply(body, "text/event-stream")

    def test_sse_failure_without_message_uses_the_default(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no pudo completar"):
            parse_vento_reply(sse({"type": "error"}), "text/event-stream")

    def test_sse_without_terminal_event_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            parse_vento_reply(sse({"type": "progress"}), "text/event-stream")

    def test_empty_body_raises(self) -> None:
        for body in ("", "  \n "):
            with self.subTest(body=body), self.assertRaises(RuntimeError):
                parse_vento_reply(body, "text/plain")


class AskTest(unittest.TestCase):
    def ask(self, context: ConversationContext, url: str = "https://bridge.example/api"):
        assistant = VentoAssistant(
            VentoCredentials(url=url, token="a b/c"), history_limit=2, timeout_seconds=7
        )
        response = MagicMock()
        response.read.return_value = b"respuesta"
        response.headers.get.return_value = "text/plain"
        response.__enter__.return_value = response
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            reply = assistant.ask("Hola", context)
        return reply, urlopen.call_args.args[0], urlopen.call_args.kwargs

    def test_sends_the_message_and_the_trimmed_history(self) -> None:
        context = ConversationContext(
            messages=tuple(ChatMessage(Role.USER, str(index)) for index in range(4))
        )

        reply, request, kwargs = self.ask(context)

        self.assertEqual(reply, "respuesta")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(kwargs["timeout"], 7)
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {
                "message": "Hola",
                "history": [{"role": "user", "text": "2"}, {"role": "user", "text": "3"}],
            },
        )
        self.assertEqual(request.get_header("Content-type"), "application/json")

    def test_the_summary_is_never_sent(self) -> None:
        _, request, _ = self.ask(ConversationContext(summary="Memoria privada"))

        self.assertNotIn("Memoria privada", request.data.decode("utf-8"))

    def test_assistant_messages_use_the_assistant_role(self) -> None:
        context = ConversationContext(messages=(ChatMessage(Role.ASSISTANT, "ok"),))

        _, request, _ = self.ask(context)

        self.assertEqual(
            json.loads(request.data.decode("utf-8"))["history"], [{"role": "assistant", "text": "ok"}]
        )

    def test_token_is_added_to_the_query_string(self) -> None:
        _, request, _ = self.ask(ConversationContext())
        self.assertEqual(request.full_url, "https://bridge.example/api?token=a%20b%2Fc")

        _, request, _ = self.ask(ConversationContext(), url="https://bridge.example/api?agent=home")
        parsed = urllib.parse.urlparse(request.full_url)
        self.assertEqual(urllib.parse.parse_qs(parsed.query), {"agent": ["home"], "token": ["a b/c"]})

    def test_http_and_network_errors_are_reported(self) -> None:
        assistant = VentoAssistant(VentoCredentials(url="https://bridge.example", token="t"), 2)
        http_error = urllib.error.HTTPError(
            "https://bridge.example", 401, "Unauthorized", None, BytesIO(b"token invalido")
        )

        with patch("urllib.request.urlopen", side_effect=http_error):
            with self.assertRaisesRegex(RuntimeError, r"\(401\): token invalido"):
                assistant.ask("Hola", ConversationContext())
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("sin red")):
            with self.assertRaisesRegex(RuntimeError, "No se pudo contactar con Jarvis: sin red"):
                assistant.ask("Hola", ConversationContext())


if __name__ == "__main__":
    unittest.main()
