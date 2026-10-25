"""Graph extraction with Gemini's structured output: the prompt goes in, a GraphDelta comes out."""

from __future__ import annotations

import json
import logging
import urllib.error
from collections.abc import Callable

from jarvis.domain.knowledge_graph import EntityType, GraphDelta
from jarvis.infrastructure.assistants.gemini import GeminiHttpError
from jarvis.ports.knowledge_graph import GraphExtractor, TransientExtractionError

LOGGER = logging.getLogger(__name__)

# OpenAPI subset of ``generateContent`` (upper-case types), checked against the real API in
# Phase 0. Gemini does not enforce length limits; GraphDelta.from_dict does.
GRAPH_DELTA_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "entities": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "key": {"type": "STRING"},
                    "name": {"type": "STRING"},
                    "type": {"type": "STRING", "enum": [item.value for item in EntityType]},
                    "aliases": {"type": "ARRAY", "items": {"type": "STRING"}},
                },
                "required": ["key", "name", "type", "aliases"],
            },
        },
        "relations": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "source": {"type": "STRING"},
                    "target": {"type": "STRING"},
                    "type": {"type": "STRING"},
                    "fact": {"type": "STRING"},
                },
                "required": ["source", "target", "type", "fact"],
            },
        },
        "invalidations": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "source": {"type": "STRING"},
                    "target": {"type": "STRING"},
                    "type": {"type": "STRING"},
                    "reason": {"type": "STRING"},
                },
                "required": ["source", "target", "type", "reason"],
            },
        },
    },
    "required": ["entities", "relations", "invalidations"],
}

_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})


class GeminiGraphExtractor(GraphExtractor):
    """``ask`` sends the prompt to a Gemini client configured for JSON and returns its text."""

    def __init__(self, ask: Callable[[str], str]) -> None:
        self._ask = ask

    def extract(self, prompt: str) -> GraphDelta:
        try:
            text = self._ask(prompt)
        except GeminiHttpError as error:
            if error.status in _TRANSIENT_STATUSES:
                raise TransientExtractionError(str(error)) from error
            raise
        except OSError as error:  # timeouts and resets that urlopen raises unwrapped
            raise TransientExtractionError(f"Gemini did not answer: {error}") from error
        except RuntimeError as error:
            if isinstance(error.__cause__, urllib.error.URLError):
                raise TransientExtractionError(str(error)) from error
            raise
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            LOGGER.warning("Gemini returned invalid JSON for the knowledge graph: %s", error)
            return GraphDelta()
        return GraphDelta.from_dict(value)
