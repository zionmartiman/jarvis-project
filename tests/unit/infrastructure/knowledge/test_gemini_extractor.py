import json
import unittest
import urllib.error
from io import BytesIO
from unittest.mock import patch

from jarvis.config.credentials import GeminiCredentials
from jarvis.domain.conversation import ConversationContext
from jarvis.domain.knowledge_graph import EntityType, GraphDelta, RelationProposal
from jarvis.infrastructure.assistants.gemini import GeminiAssistant, GeminiHttpError
from jarvis.infrastructure.knowledge.gemini_extractor import (
    GRAPH_DELTA_SCHEMA,
    GeminiGraphExtractor,
)
from jarvis.ports.knowledge_graph import TransientExtractionError

VALID_REPLY = {
    "entities": [
        {"key": "ana", "name": "Ana", "type": "persona", "aliases": ["mi hermana"]},
        {"key": "valencia", "name": "Valencia", "type": "lugar", "aliases": []},
    ],
    "relations": [
        {"source": "ana", "target": "valencia", "type": "vive_en", "fact": "Ana vive en Valencia"}
    ],
    "invalidations": [],
}


def raising(error: BaseException):
    def ask(prompt: str) -> str:
        raise error

    return ask


def gemini_ask(prompt: str) -> str:
    """The real client, so the errors are the ones urlopen failures turn into."""
    gemini = GeminiAssistant(GeminiCredentials("key", "model"), 1)
    return gemini.ask(prompt, ConversationContext())


class GeminiGraphExtractorTest(unittest.TestCase):
    def test_valid_json_becomes_a_delta(self) -> None:
        prompts: list[str] = []

        def ask(prompt: str) -> str:
            prompts.append(prompt)
            return json.dumps(VALID_REPLY)

        delta = GeminiGraphExtractor(ask).extract("el prompt")

        self.assertEqual(prompts, ["el prompt"])
        self.assertEqual([entity.key for entity in delta.entities], ["ana", "valencia"])
        self.assertEqual(delta.entities[0].type, EntityType.PERSONA)
        self.assertEqual(
            delta.relations,
            (RelationProposal("ana", "valencia", "vive_en", "Ana vive en Valencia"),),
        )

    def test_broken_json_is_an_empty_delta(self) -> None:
        extractor = GeminiGraphExtractor(lambda prompt: '{"entities": [')

        with self.assertLogs("jarvis.infrastructure.knowledge.gemini_extractor", "WARNING"):
            self.assertEqual(extractor.extract("p"), GraphDelta())

    def test_json_that_is_not_a_delta_is_an_empty_delta(self) -> None:
        self.assertEqual(GeminiGraphExtractor(lambda prompt: "[1, 2]").extract("p"), GraphDelta())

    def test_busy_and_server_errors_are_transient(self) -> None:
        for status in (429, 500, 502, 503, 504):
            with self.subTest(status=status):
                error = urllib.error.HTTPError("https://x", status, "", None, BytesIO(b""))
                with patch("urllib.request.urlopen", side_effect=error):
                    with self.assertRaises(TransientExtractionError) as raised:
                        GeminiGraphExtractor(gemini_ask).extract("p")
                self.assertIsInstance(raised.exception.__cause__, GeminiHttpError)

    def test_network_errors_and_timeouts_are_transient(self) -> None:
        for error in (urllib.error.URLError("sin red"), TimeoutError("timed out")):
            with self.subTest(error=error):
                with patch("urllib.request.urlopen", side_effect=error):
                    with self.assertRaises(TransientExtractionError):
                        GeminiGraphExtractor(gemini_ask).extract("p")

    def test_other_errors_are_not_transient(self) -> None:
        bad_request = urllib.error.HTTPError("https://x", 400, "", None, BytesIO(b""))
        with patch("urllib.request.urlopen", side_effect=bad_request):
            with self.assertRaises(GeminiHttpError):
                GeminiGraphExtractor(gemini_ask).extract("p")
        with self.assertRaises(RuntimeError) as raised:
            GeminiGraphExtractor(raising(RuntimeError("gemini.env debe contener"))).extract("p")
        self.assertNotIsInstance(raised.exception, TransientExtractionError)


class GraphDeltaSchemaTest(unittest.TestCase):
    def test_uses_the_openapi_types_and_every_entity_type(self) -> None:
        entity = GRAPH_DELTA_SCHEMA["properties"]["entities"]["items"]

        self.assertEqual(GRAPH_DELTA_SCHEMA["type"], "OBJECT")
        self.assertEqual(
            GRAPH_DELTA_SCHEMA["required"], ["entities", "relations", "invalidations"]
        )
        self.assertEqual(entity["properties"]["type"]["enum"], [item.value for item in EntityType])
        self.assertEqual(entity["required"], ["key", "name", "type", "aliases"])


if __name__ == "__main__":
    unittest.main()
