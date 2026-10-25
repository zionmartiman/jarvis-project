import json
import unittest
import urllib.parse
from unittest.mock import MagicMock, patch

from bridge.vento_bridge import VentoBridge
from config.settings import BridgeCredentials


def sse(*events: dict) -> str:
    return "\n\n".join(f"data: {json.dumps(event)}" for event in events)


class ExtractReplyTest(unittest.TestCase):
    def extract(self, body: str, content_type: str = "") -> str:
        return VentoBridge._extract_reply(body, content_type)

    def test_plain_text(self) -> None:
        self.assertEqual(self.extract("  Hola, señor.\n", "text/plain"), "Hola, señor.")

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
                self.assertEqual(self.extract(json.dumps(payload), "application/json"), "uno")

    def test_json_string_payload(self) -> None:
        self.assertEqual(self.extract(json.dumps("directo"), "application/json"), "directo")

    def test_json_without_text_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            self.extract(json.dumps({"reply": {}}), "application/json")

    def test_invalid_json_falls_back_to_body(self) -> None:
        self.assertEqual(self.extract("{no es json", "application/json"), "{no es json")

    def test_sse_uses_terminal_event(self) -> None:
        body = sse(
            {"type": "progress", "reply": {"content": "pensando"}},
            {"type": "completed", "reply": {"content": "respuesta final"}},
        )
        self.assertEqual(self.extract(body, "text/event-stream"), "respuesta final")

    def test_sse_detected_from_body_prefix(self) -> None:
        body = sse({"type": "completed", "reply": "sin cabecera"})
        self.assertEqual(self.extract(body, "text/plain"), "sin cabecera")

    def test_sse_failure_raises_with_message(self) -> None:
        body = sse({"type": "failed", "reply": {"content": "fallo del agente"}})
        with self.assertRaisesRegex(RuntimeError, "fallo del agente"):
            self.extract(body, "text/event-stream")

    def test_sse_failure_without_message_uses_default(self) -> None:
        body = sse({"type": "error"})
        with self.assertRaisesRegex(RuntimeError, "no pudo completar"):
            self.extract(body, "text/event-stream")

    def test_sse_without_terminal_event_raises(self) -> None:
        body = sse({"type": "progress"})
        with self.assertRaises(RuntimeError):
            self.extract(body, "text/event-stream")

    def test_empty_body_raises(self) -> None:
        for body in ("", "  \n "):
            with self.subTest(body=body), self.assertRaises(RuntimeError):
                self.extract(body, "text/plain")


class AskRequestTest(unittest.TestCase):
    def ask(self, history: list[dict], url: str = "https://bridge.example/api", limit: int = 2):
        bridge = VentoBridge(BridgeCredentials(url=url, token="a b/c"), history_limit=limit, timeout_seconds=7)
        response = MagicMock()
        response.read.return_value = b"respuesta"
        response.headers.get.return_value = "text/plain"
        response.__enter__.return_value = response
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            reply = bridge.ask("Hola", history)
        request = urlopen.call_args.args[0]
        return reply, request, urlopen.call_args.kwargs

    def test_sends_message_and_trimmed_history(self) -> None:
        history = [{"role": "user", "text": str(index)} for index in range(4)]

        reply, request, kwargs = self.ask(history)

        self.assertEqual(reply, "respuesta")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(kwargs["timeout"], 7)
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"message": "Hola", "history": history[-2:]},
        )
        self.assertEqual(request.get_header("Content-type"), "application/json")

    def test_token_is_added_to_query_string(self) -> None:
        _, request, _ = self.ask([])
        self.assertEqual(request.full_url, "https://bridge.example/api?token=a%20b%2Fc")

        _, request, _ = self.ask([], url="https://bridge.example/api?agent=home")
        parsed = urllib.parse.urlparse(request.full_url)
        self.assertEqual(urllib.parse.parse_qs(parsed.query), {"agent": ["home"], "token": ["a b/c"]})


if __name__ == "__main__":
    unittest.main()
